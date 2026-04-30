from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from .registry import AgentRegistry, canonical_agent_name, get_agent_spec
from app.a2a_runtime import ExecutionPlan, ExecutionStep, build_execution_plan as build_fallback_execution_plan
from app.config import settings
from app.debug_log import log_stage
from app.llm import LLMCallError, call_chat_model_with_messages_raw
from tools.agent_tool import AgentTool


_THINK_TAG_RE = re.compile(r"<think>\s*(.*?)\s*</think>\s*", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_RE = re.compile(r"<\s*think\s*>\s*", re.IGNORECASE)
_CLOSE_THINK_RE = re.compile(r"<\s*/\s*think\s*>\s*", re.IGNORECASE)


def split_think_content(content: str) -> tuple[str, str]:
    """分离 ``<think>...</think>`` 推理段与真正的助手回复。

    兼容：
    - 完整闭合：``<think>R</think>A`` → ``("R", "A")``
    - 多段 think：依次累加到 reasoning
    - 未闭合（流式中间态）：``<think>R...`` → ``("R...", "")``
    - 漂移的尾部 ``</think>``：直接剔除
    - 无标签：返回 ``("", content)``
    """
    if not isinstance(content, str) or not content:
        return "", ""
    reasoning_parts: list[str] = []
    cleaned = content
    while True:
        m = _THINK_TAG_RE.search(cleaned)
        if not m:
            break
        reasoning_parts.append(m.group(1).strip())
        cleaned = cleaned[: m.start()] + cleaned[m.end():]
    open_match = _OPEN_THINK_RE.search(cleaned)
    if open_match:
        tail = cleaned[open_match.end():]
        # 尾部可能仍带 </think>（边界异常），一并剥离
        tail = _CLOSE_THINK_RE.sub("", tail)
        reasoning_parts.append(tail.strip())
        cleaned = cleaned[: open_match.start()]
    else:
        cleaned = _CLOSE_THINK_RE.sub("", cleaned)
    reasoning = "\n\n".join(part for part in reasoning_parts if part).strip()
    return reasoning, cleaned.strip()


class MainAgent:
    def __init__(self) -> None:
        self.registry = AgentRegistry
        self.agent_tool = AgentTool()

    def plan(
        self,
        user_message: str,
        requested_model: str | None,
        *,
        attachments: list[dict[str, Any]] | None = None,
        runtime_context: dict | None = None,
        memory_context: dict | None = None,
        direct_agent: str | None = None,
        on_planner_stream: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[ExecutionPlan, dict[str, Any]]:
        attachments = attachments or []
        canonical_direct_agent = canonical_agent_name(direct_agent)
        if direct_agent and not canonical_direct_agent:
            raise ValueError(f"未知 skill: {direct_agent}")
        if canonical_direct_agent and canonical_direct_agent != "general":
            plan = build_fallback_execution_plan(user_message, canonical_direct_agent, attachments)
            return plan, {
                "planner": "direct_subagent_dispatch",
                "fallback": False,
                "requestedSkill": canonical_direct_agent,
                "dispatchMode": "direct_subagent",
            }
        if not settings.enable_model_planner:
            plan = build_fallback_execution_plan(user_message, None, attachments)
            return plan, {
                "planner": "main_agent_direct_disabled",
                "fallback": True,
                "dispatchMode": "main_agent_direct",
            }

        messages = self._build_messages(user_message, attachments, runtime_context, memory_context)
        tool_schema = self.agent_tool.get_tool_schema()
        log_stage(
            "planner.request",
            {
                "requestedModel": settings.planner_model or requested_model,
                "messages": messages,
                "toolSchema": tool_schema,
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        try:
            # Planner 固定非流式：部分私有化网关对 stream=true + tools 仅返回空 delta，导致误判为空响应。
            # Skill 执行仍由各 skill LLM（call_chat_model 等）按需 stream:true，不受影响。
            def _call_planner(*, strip_hint: bool = False, tool_choice: str = "auto") -> dict[str, Any]:
                """实际发起 planner 请求。

                - ``strip_hint`` 为 True 时临时关闭 disable_thinking / chat_template_kwargs，
                  规避部分网关对未知字段或 /no_think 附加文本不兼容而返回 400/422。
                - ``tool_choice`` 通常为 ``auto``；对写作类意图可尝试 ``required`` 强制至少一次 tool call
                  （网关不支持时由外层重试回退为 ``auto``）。
                """
                purpose = "planner.retry_no_think_hint" if strip_hint else "planner"
                if not strip_hint:
                    return call_chat_model_with_messages_raw(
                        messages,
                        settings.planner_model or requested_model,
                        purpose=purpose,
                        temperature=settings.planner_temperature,
                        extra_payload={
                            "tools": [tool_schema],
                            "tool_choice": tool_choice,
                        },
                        stream=False,
                        on_stream_event=None,
                    )
                _prev = settings.llm_disable_thinking
                _prev_kwargs = settings.llm_send_chat_template_kwargs
                try:
                    settings.llm_disable_thinking = False
                    settings.llm_send_chat_template_kwargs = False
                    return call_chat_model_with_messages_raw(
                        messages,
                        settings.planner_model or requested_model,
                        purpose=purpose,
                        temperature=settings.planner_temperature,
                        extra_payload={
                            "tools": [tool_schema],
                            "tool_choice": tool_choice,
                        },
                        stream=False,
                        on_stream_event=None,
                    )
                finally:
                    settings.llm_disable_thinking = _prev
                    settings.llm_send_chat_template_kwargs = _prev_kwargs

            writing_intent = self._looks_like_writing_request(user_message)
            preferred_tool_choice = (
                "required"
                if (settings.planner_force_tool_for_writing and writing_intent)
                else "auto"
            )
            # 分步重试：写作意图优先 required；失败则 auto + 正常 hint；再失败则 auto + 去掉 hint。
            trial_plan: list[tuple[str, bool, str]] = []
            if preferred_tool_choice == "required":
                trial_plan.append(("required", False, "planner.tool_choice.required"))
            trial_plan.append(("auto", False, "planner.tool_choice.auto"))
            trial_plan.append(("auto", True, "planner.strip_hint_then_auto"))

            last_exc: LLMCallError | None = None
            response: dict[str, Any] | None = None
            for tc, strip_hint, strategy in trial_plan:
                try:
                    response = _call_planner(strip_hint=strip_hint, tool_choice=tc)
                    last_exc = None
                    break
                except LLMCallError as exc:
                    last_exc = exc
                    log_stage(
                        "planner.retry",
                        {
                            "reason": str(exc),
                            "strategy": strategy,
                            "toolChoice": tc,
                            "stripHint": strip_hint,
                        },
                        enabled=settings.debug_runtime_logs,
                        max_chars=settings.debug_log_max_chars,
                        max_string_chars=settings.debug_log_max_string_chars,
                    )
            if response is None:
                if last_exc is not None:
                    raise last_exc
                raise LLMCallError("planner: 无可用响应")
            message = response.get("message") or {}
            if on_planner_stream:
                raw_content_flush = self._message_text(message)
                raw_reasoning_flush = self._message_reasoning(message).strip()
                # Qwen3 等将推理写入 content 内的 <think>...</think>；
                # flush 前把推理与正文拆开，避免 thinking_delta 混入 <think> 标签或重复打印正文。
                embedded_reasoning_flush, body_flush = split_think_content(raw_content_flush)
                on_planner_stream(
                    {
                        "reasoning": raw_reasoning_flush or embedded_reasoning_flush,
                        "text": body_flush,
                        "flush": True,
                    }
                )
            plan, planner_meta = self._plan_from_response(user_message, response, attachments)
            log_stage(
                "planner.response",
                {
                    "normalizedPlan": {
                        "intent": plan.intent,
                        "summary": plan.summary,
                        "steps": [
                            {
                                "index": step.index,
                                "skillName": step.skill_name,
                                "title": step.title,
                                "objective": step.objective,
                                "scope": step.scope,
                                "dependsOn": step.depends_on,
                                "subtaskRole": step.subtask_role,
                            }
                            for step in plan.steps
                        ],
                    },
                    "plannerMeta": planner_meta,
                    "modelName": response["model_name"],
                },
                enabled=settings.debug_runtime_logs,
                max_chars=settings.debug_log_max_chars,
                max_string_chars=settings.debug_log_max_string_chars,
            )
            return plan, planner_meta
        except (LLMCallError, ValueError, json.JSONDecodeError) as exc:
            fallback_plan = build_fallback_execution_plan(user_message, None, attachments)
            log_stage(
                "planner.fallback",
                {
                    "reason": str(exc),
                    "fallbackPlan": {
                        "intent": fallback_plan.intent,
                        "summary": fallback_plan.summary,
                        "steps": [step.skill_name for step in fallback_plan.steps],
                    },
                },
                enabled=settings.debug_runtime_logs,
                max_chars=settings.debug_log_max_chars,
                max_string_chars=settings.debug_log_max_string_chars,
            )
            return fallback_plan, {
                "planner": "main_agent_fallback",
                "fallback": True,
                "error": str(exc),
                "dispatchMode": "main_agent_direct",
            }

    def leader_step(
        self,
        messages: list[dict[str, Any]],
        requested_model: str | None,
        *,
        on_stream_event: Callable[[dict[str, Any]], None] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Leader 闭环：在完整 messages（含 tool 结果）上再调一次 Planner 模型以决策下一步。"""
        tool_schema = self.agent_tool.get_tool_schema()
        return call_chat_model_with_messages_raw(
            messages,
            settings.planner_model or requested_model,
            purpose="leader_step",
            temperature=settings.planner_temperature,
            extra_payload={
                "tools": [tool_schema],
                "tool_choice": "auto",
            },
            stream=stream,
            on_stream_event=on_stream_event,
        )

    def _build_messages(
        self,
        user_message: str,
        attachments: list[dict[str, Any]],
        runtime_context: dict | None,
        memory_context: dict | None,
    ) -> list[dict[str, str]]:
        recent_messages = runtime_context.get("recent_messages") if runtime_context else []
        context_lines = [f"当前用户输入：{user_message}", f"附件数量：{len(attachments)}"]
        if attachments:
            attachment_names = [item.get("name") or item.get("title") or "附件" for item in attachments]
            context_lines.append("附件列表：" + "、".join(attachment_names))
        if runtime_context and runtime_context.get("summary"):
            context_lines.append("运行摘要：")
            context_lines.append(runtime_context["summary"])
        pending_task = runtime_context.get("pending_task") if runtime_context else None
        if pending_task:
            context_lines.append("存在等待中的任务：")
            context_lines.append(
                "- skill: "
                f"{pending_task.get('skillName') or 'unknown'}"
                f" | title: {pending_task.get('title') or '待处理任务'}"
                f" | resume_mode: {pending_task.get('resumeMode') or 'unknown'}"
            )
        pending_question = runtime_context.get("pending_question") if runtime_context else None
        if pending_question:
            context_lines.append("上一轮待回答的问题：")
            context_lines.append(str(pending_question))
        pending_answer = runtime_context.get("user_answer_to_pending") if runtime_context else None
        if pending_answer:
            context_lines.append("当前消息可能是在回答上一轮澄清，请优先判断是否应继续 pending task：")
            context_lines.append(str(pending_answer))
        if recent_messages:
            context_lines.append("最近消息：")
            for item in recent_messages[-4:]:
                context_lines.append(f"- {(item.get('role') or 'unknown')}: {(item.get('content') or '').strip()}")
        if memory_context:
            identify_md = (memory_context.get("identify_markdown") or "").strip()
            memory_md = (memory_context.get("memory_markdown") or "").strip()
            session_summary_md = (memory_context.get("session_summary_markdown") or "").strip()
            if identify_md:
                context_lines.append("identify.md：")
                context_lines.append(identify_md)
            if memory_md:
                context_lines.append("memory.md：")
                context_lines.append(memory_md)
            if session_summary_md:
                context_lines.append("session_summary.md：")
                context_lines.append(session_summary_md)
        return [
            {"role": "system", "content": self._build_main_system_prompt()},
            {"role": "user", "content": "\n".join(context_lines)},
        ]

    def _build_main_system_prompt(self) -> str:
        prompt = get_agent_spec("general").prompt_path.parent.parent / "main_system.md"
        base = prompt.read_text(encoding="utf-8").strip()
        return base.replace("{{AGENT_REGISTRY_CONTEXT}}", self.registry.to_prompt_context())

    def _plan_from_response(
        self,
        user_message: str,
        response: dict[str, Any],
        attachments: list[dict[str, Any]],
    ) -> tuple[ExecutionPlan, dict[str, Any]]:
        message = response.get("message") or {}
        tool_calls = message.get("tool_calls") or []
        raw_content = self._message_text(message)
        raw_reasoning = self._message_reasoning(message).strip()
        # Qwen3 / DeepSeek-R1 风格：推理可能嵌在 content 的 <think>...</think> 中，
        # 需要剥离后再作为 assistant_text，否则会导致"思考过程反复出现在多个事件里"。
        embedded_reasoning, assistant_text_body = split_think_content(raw_content)
        assistant_text = assistant_text_body.strip()
        reasoning_content = raw_reasoning or embedded_reasoning
        if tool_calls:
            steps: list[ExecutionStep] = []
            previous_step_ids: list[str] = []
            for index, tool_call in enumerate(tool_calls, start=1):
                function = tool_call.get("function") or {}
                if function.get("name") != self.agent_tool.tool_name:
                    continue
                arguments = json.loads(function.get("arguments") or "{}")
                step = self.agent_tool.to_execution_step(
                    arguments,
                    index=index,
                    previous_step_ids=previous_step_ids,
                )
                steps.append(step)
                previous_step_ids.append(f"step_{index:02d}_{step.skill_name}")
            if not steps:
                raise ValueError("主 Agent 返回了空的 sub-agent 调度计划")
            steps, normalization = self._normalize_document_steps(user_message, steps, reasoning_content)
            summary = assistant_text or f"主 Agent 已规划 {len(steps)} 个 sub-agent 步骤。"
            return (
                ExecutionPlan(
                    intent="document_workflow",
                    summary=summary,
                    steps=steps,
                ),
                {
                    "planner": "main_agent_tool_calls",
                    "fallback": False,
                    "dispatchMode": "tool_call_dispatch",
                    "modelName": response["model_name"],
                    "toolCalls": tool_calls,
                    "assistantText": assistant_text,
                    "reasoningContent": reasoning_content,
                    "normalization": normalization,
                    "raw": response["raw"],
                },
            )

        # 模型未触发 tool_call：
        # 1) 若是明确的公文写作意图，兜底构造 retrieval + writing 两步计划，
        #    避免"想得很好但一步都没执行"的退化体验；
        # 2) 否则按 direct answer 处理，但只用剥离 <think> 后的正文，
        #    若正文为空（模型只输出了 reasoning），直接走 general sub agent。
        if self._looks_like_writing_request(user_message):
            retrieval_spec = get_agent_spec("retrieval")
            writing_spec = get_agent_spec("writing")
            retrieval_depends_sid = "step_01_retrieval"
            steps = [
                ExecutionStep(
                    index=1,
                    skill_name=retrieval_spec.name,
                    title=retrieval_spec.title,
                    objective=(
                        f"围绕用户需求「{(user_message or '').strip()[:80]}」检索可用范例、政策依据与写作要点，"
                        "产出结构化要点，供后续写作引用。"
                    ),
                    scope=retrieval_spec.scope,
                    subtask_role=retrieval_spec.default_subtask_role,
                ),
                ExecutionStep(
                    index=2,
                    skill_name=writing_spec.name,
                    title=writing_spec.title,
                    objective=(
                        "整合前序检索得到的要点与用户原始需求，起草符合公文格式的完整正文。"
                    ),
                    scope=writing_spec.scope,
                    depends_on=[retrieval_depends_sid],
                    subtask_role=writing_spec.default_subtask_role,
                ),
            ]
            plan_summary = (
                assistant_text
                or "模型未主动调度工具，按公文写作意图回退至检索 + 写作两步计划。"
            )
            return (
                ExecutionPlan(
                    intent="document_workflow",
                    summary=plan_summary,
                    steps=steps,
                ),
                {
                    "planner": "main_agent_writing_fallback",
                    "fallback": True,
                    "dispatchMode": "auto_retrieval_writing",
                    "modelName": response["model_name"],
                    "assistantText": assistant_text,
                    "reasoningContent": reasoning_content,
                    "raw": response["raw"],
                    "normalization": {
                        "type": "writing_fallback_on_missing_tool_call",
                        "reason": "planner_returned_text_only_for_writing_request",
                        "dependsOn": [retrieval_depends_sid],
                    },
                },
            )

        direct_plan = build_fallback_execution_plan(user_message, None, attachments)
        effective_summary = assistant_text or "模型未返回直接可用的答复，已切换到默认处理流程。"
        direct_plan.summary = effective_summary
        return (
            direct_plan,
            {
                "planner": "main_agent_direct_answer",
                "fallback": False,
                "dispatchMode": "main_agent_direct",
                "modelName": response["model_name"],
                "assistantText": assistant_text,
                "reasoningContent": reasoning_content,
                # 仅当模型剥离 <think> 后确实给出了正文才作为 directAnswer 下发，
                # 否则下游不会把"空字符串"或"纯思考内容"直接展示给用户。
                "directAnswer": assistant_text or None,
                "raw": response["raw"],
            },
        )

    @staticmethod
    def _message_text(message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            )
        return ""

    @staticmethod
    def _message_reasoning(message: dict[str, Any]) -> str:
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str):
            return reasoning
        if isinstance(reasoning, list):
            return "\n".join(
                item.get("text", "")
                for item in reasoning
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            )
        return ""

    @staticmethod
    def _looks_like_writing_request(user_message: str) -> bool:
        text = (user_message or "").strip()
        if not text:
            return False
        strong_markers = (
            "不是只检索",
            "不只是检索",
            "帮我写",
            "写一篇",
            "写一份",
            "写个",
            "写篇",
            "起草",
            "撰写",
            "拟写",
            "拟一份",
            "拟一篇",
            "拟发",
            "拟稿",
            "生成",
            "生草",
            "起稿",
            "形成文稿",
            # 口语里常说「准备一篇/一份…」而不出现「写」字，易被误判为非写作请求，
            # 导致仅 retrieval 的步骤计划不会自动补上 writing。
            "准备一篇",
            "准备一份",
            "正式文稿",
        )
        doc_markers = (
            "报告",
            "通知",
            "方案",
            "请示",
            "批复",
            "决定",
            "函",
            "意见",
            "总结",
            "汇报",
            "发言稿",
            "讲话稿",
            "致辞",
            "倡议书",
            "动员令",
            "公告",
            "公文",
            "正文",
            "纪要",
            "情况说明",
            "安排",
            "工作部署",
            "实施方案",
        )
        if any(marker in text for marker in strong_markers):
            return True
        if (
            ("准备" in text or "整一篇" in text or "弄一篇" in text)
            and ("篇" in text or "份" in text)
            and any(marker in text for marker in doc_markers)
        ):
            return True
        return bool(
            any(marker in text for marker in ("写", "起草", "撰写", "生成", "拟"))
            and any(marker in text for marker in doc_markers)
        )

    def _normalize_document_steps(
        self,
        user_message: str,
        steps: list[ExecutionStep],
        reasoning_content: str = "",
    ) -> tuple[list[ExecutionStep], dict[str, Any] | None]:
        if not steps or not self._looks_like_writing_request(user_message):
            return steps, None
        if any(step.skill_name == "writing" for step in steps):
            return steps, None
        if not any(step.skill_name == "retrieval" for step in steps):
            return steps, None

        writing_spec = get_agent_spec("writing")
        depends_on = [f"step_{steps[-1].index:02d}_{steps[-1].skill_name}"]
        normalized_steps = list(steps)
        normalized_steps.append(
            ExecutionStep(
                index=len(normalized_steps) + 1,
                skill_name=writing_spec.name,
                title=writing_spec.title,
                objective=(
                    "根据前序检索结果与用户需求，起草完整公文正文；"
                    "若用户明确要求的是报告，则输出报告草稿。"
                ),
                scope=writing_spec.scope,
                depends_on=depends_on,
                subtask_role=writing_spec.default_subtask_role,
            )
        )
        return normalized_steps, {
            "type": "append_writing_after_retrieval",
            "reason": "user_requires_document_draft",
            "dependsOn": depends_on,
            "reasoningMentionsWriting": "writing" in reasoning_content.lower() or "写" in reasoning_content,
        }
