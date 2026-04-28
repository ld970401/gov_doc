"""
LLM 模型调用封装模块。

本模块提供与 OpenAI 兼容的 chat/completions 接口调用功能，支持：
- 流式响应处理
- 工具调用
- 模型名称解析和别名处理
- 消息构建（包含系统提示、上下文等）
- JSON 提取和错误处理
"""

import json  # 用于处理 JSON 数据
from html import escape  # 用于 HTML 转义，防止 XSS 攻击
from typing import Any, Callable  # 类型注解，提高代码可读性

import requests  # HTTP 请求库，用于调用模型 API

from agents import canonical_agent_name, system_prompt_for_agent  # Agent 相关函数
from .config import settings  # 应用配置，包含模型调用相关设置
from .debug_log import log_stage  # 调试日志记录函数


# 模型别名映射表，将常见模型别名映射到默认模型
# 仅保留「短别名 → 当前默认接入点」；真实 model id 不在此表则原样传给网关
MODEL_ALIASES = {
    "minimax": settings.llm_default_model,  # Minimax 模型别名
    "qwen 3.5": settings.llm_default_model,  # 通义千问 3.5 模型别名
    "qwen3-max": settings.llm_default_model,  # 通义千问 3.5 Max 模型别名
    "deepseek": settings.llm_default_model,  # DeepSeek 模型别名
    "deepseek-chat": settings.llm_default_model,  # DeepSeek Chat 模型别名
}


class LLMCallError(RuntimeError):
    """LLM 调用异常类，用于表示模型调用过程中的错误。"""
    pass


def _is_qwen_family(model_name: str | None) -> bool:
    """判断模型是否属于 Qwen 家族（Qwen3 / Qwen3.5 / qwen... 等）。

    仅对 Qwen 系启用关闭 thinking 的 hint，避免给 MiniMax 等不识别该约定的模型
    注入无意义字段（虽然绝大多数网关会忽略未知字段，但仍尽量保守）。
    """
    lower = (model_name or "").lower()
    return lower.startswith("qwen")


def _apply_disable_thinking(
    payload: dict[str, Any],
    model_name: str,
    messages: list[dict[str, Any]],
    *,
    include_kwargs: bool | None = None,
) -> list[dict[str, Any]]:
    """为 Qwen 系模型注入关闭 thinking 的请求参数。

    默认只做一件事（最稳妥）：
    - 在最后一条 user / system 消息尾部追加 ``/no_think``。
      Qwen3 chat template 在内部匹配该 token 并跳过 <think> 段；
      对不识别该约定的模型也是无害文本，不会触发网关参数校验错误。

    仅当 ``include_kwargs=True`` 或 settings.llm_send_chat_template_kwargs 显式开启时，
    额外在顶层注入 ``chat_template_kwargs = {"enable_thinking": false}``。该字段仅
    部分网关（官方 vLLM / SGLang 较新版本）识别；老旧私有化部署会以 400 拒绝，
    导致 planner LLMCallError 回退成 general，这是上一版出现的故障根因。

    返回用于实际发送的 messages（深拷贝，不污染调用方对象）。
    调用方已显式传入 chat_template_kwargs 时不再覆盖。
    """
    if not settings.llm_disable_thinking or not _is_qwen_family(model_name):
        return messages

    # 是否携带额外的 chat_template_kwargs —— 默认关闭以保证兼容性
    should_send_kwargs = (
        include_kwargs if include_kwargs is not None else settings.llm_send_chat_template_kwargs
    )
    if should_send_kwargs:
        payload.setdefault("chat_template_kwargs", {"enable_thinking": False})

    # 深拷贝 messages，避免修改调用方持有的对象。
    send_messages: list[dict[str, Any]] = [dict(m) for m in messages]
    no_think_tag = "/no_think"
    for item in reversed(send_messages):
        role = item.get("role")
        if role not in ("user", "system"):
            continue
        content = item.get("content")
        if isinstance(content, str):
            if no_think_tag in content:
                break
            sep = "" if content.endswith(("\n", " ")) else "\n"
            item["content"] = f"{content}{sep}{no_think_tag}"
            break
        if isinstance(content, list):
            # OpenAI multimodal 消息格式：content 为部件数组
            already = any(
                isinstance(part, dict)
                and part.get("type") in {"text", "output_text"}
                and no_think_tag in (part.get("text") or "")
                for part in content
            )
            if already:
                break
            content.append({"type": "text", "text": no_think_tag})
            item["content"] = content
            break
    return send_messages


# 辅助函数：获取完整的 chat/completions API URL
def chat_completions_post_url() -> str:
    """获取 OpenAI 兼容的 chat/completions 完整 URL。"""
    # 优先使用直接配置的 chat_completions_url
    full = (settings.llm_chat_completions_url or "").strip().rstrip("/")
    if full:
        return full
    # 如果没有直接配置，则使用 base_url 拼接
    base = (settings.llm_base_url or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/chat/completions"


# 辅助函数：解析模型名称
def resolve_model_name(requested_model: str | None) -> str:
    """解析模型名称，支持别名处理。"""
    # 规范化输入模型名称
    normalized = (requested_model or "").strip()
    if not normalized:
        # 如果未指定模型，使用默认模型
        return settings.llm_default_model
    # 查找别名映射，否则返回原始名称
    return MODEL_ALIASES.get(normalized.lower(), normalized)


# 核心函数：构建模型输入消息
def build_messages(
    content: str,  # 用户输入内容
    skill: str | None,  # 技能名称
    runtime_context: dict | None = None,  # 运行时上下文
    memory_context: dict | None = None,  # 记忆上下文
    task_packet: dict | None = None,  # 任务包
):
    """构建消息列表，包含系统提示和各种上下文信息。"""
    # 获取对应技能的系统提示词
    system_prompt = system_prompt_for_agent(canonical_agent_name(skill) or "general")
    # 初始化消息列表，添加系统提示
    messages = [{"role": "system", "content": system_prompt}]

    # 收集上下文信息
    context_lines: list[str] = []

    # 添加任务包信息（如果有）
    if task_packet:
        context_lines.extend(
            [
                "当前由 leader agent 下发结构化任务，请遵守执行契约。",
                f"- objective: {task_packet.get('objective') or ''}",  # 任务目标
                f"- scope: {task_packet.get('scope') or ''}",  # 任务范围
                f"- reporting_contract: {task_packet.get('reporting_contract') or ''}",  # 报告契约
                f"- escalation_policy: {task_packet.get('escalation_policy') or ''}",  # 升级策略
            ]
        )

    # 添加运行上下文（如果有）
    if runtime_context:
        summary = runtime_context.get("summary") or ""  # 上下文摘要
        recent_messages = runtime_context.get("recent_messages") or []  # 最近消息
        if summary:
            context_lines.append("运行上下文摘要：")
            context_lines.append(summary)
        if recent_messages:
            context_lines.append("最近消息：")
            # 只取最近 4 条消息，避免上下文过长
            for item in recent_messages[-4:]:
                role = item.get("role") or "unknown"
                text = (item.get("content") or "").strip()
                context_lines.append(f"- {role}: {text}")

    # 添加记忆上下文（如果有）
    if memory_context:
        # 用户身份偏好
        identify_md = (memory_context.get("identify_markdown") or "").strip()
        # 长期记忆
        memory_md = (memory_context.get("memory_markdown") or "").strip()
        # 最近会话摘要
        session_summary = (memory_context.get("session_summary_markdown") or "").strip()

        if identify_md:
            context_lines.append("用户身份偏好：")
            context_lines.append(identify_md)
        if memory_md:
            context_lines.append("长期记忆：")
            context_lines.append(memory_md)
        if session_summary:
            context_lines.append("最近会话摘要：")
            context_lines.append(session_summary)

    # 将上下文信息添加到消息列表
    if context_lines:
        messages.append({"role": "system", "content": "\n".join(context_lines)})

    # 添加用户消息
    messages.append({"role": "user", "content": content})
    return messages


# 辅助函数：从文本中提取 JSON 对象
def extract_json_object(text: str) -> dict:
    """从模型返回的文本中提取 JSON 对象。"""
    # 规范化输入文本
    normalized = (text or "").strip()
    if not normalized:
        raise LLMCallError("模型未返回可解析的 JSON 内容")

    # 准备候选 JSON 字符串
    candidates = [normalized]

    # 处理代码块中的 JSON
    if "```" in normalized:
        # 查找 JSON 对象的开始和结束位置
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start >= 0 and end > start:
            candidates.append(normalized[start : end + 1])
    else:
        # 直接查找 JSON 对象
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start >= 0 and end > start:
            candidates.append(normalized[start : end + 1])

    # 尝试解析每个候选字符串
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            # 解析失败，尝试下一个候选
            continue
        if isinstance(data, dict):
            # 成功解析为字典，返回结果
            return data

    # 所有候选都解析失败
    raise LLMCallError("模型返回的规划结果不是有效 JSON 对象")


# 辅助函数：处理消息内容
def _coerce_message_text(message: dict) -> str:
    """处理消息内容，支持字符串和列表格式。"""
    content = message.get("content")
    if isinstance(content, str):
        # 字符串格式，直接返回
        return content.strip()
    if isinstance(content, list):
        # 列表格式，提取文本内容
        return "\n".join(
            item.get("text", "").strip()
            for item in content
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        ).strip()
    # 其他格式，返回空字符串
    return ""


# 辅助函数：处理流式响应的 delta 文本
def _coerce_delta_text(value: Any) -> str:
    """处理流式响应的 delta 文本。"""
    if isinstance(value, str):
        # 字符串格式，直接返回
        return value
    if isinstance(value, list):
        # 列表格式，提取文本内容
        return "".join(
            item.get("text", "")
            for item in value
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        )
    # 其他格式，返回空字符串
    return ""


def _coerce_choice_text(choice: dict[str, Any]) -> str:
    """从单个 choice 中尽可能提取文本，兼容非标准网关字段。"""
    if not isinstance(choice, dict):
        return ""
    message = choice.get("message")
    if isinstance(message, dict):
        msg_text = _coerce_message_text(message)
        if msg_text:
            return msg_text
    delta = choice.get("delta")
    if isinstance(delta, dict):
        delta_text = _coerce_delta_text(
            delta.get("content")
            or delta.get("text")
            or delta.get("output_text")
        )
        if delta_text:
            return delta_text
    for key in ("text", "output_text", "content"):
        raw = choice.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw
        if isinstance(raw, list):
            list_text = _coerce_delta_text(raw)
            if list_text:
                return list_text
    return ""


# 辅助函数：合并工具调用块
def _merge_tool_call_chunks(existing: list[dict], delta_calls: list[dict]) -> list[dict]:
    """合并工具调用块，处理流式响应中的工具调用信息。"""
    # 复制现有工具调用列表
    merged = list(existing or [])

    # 处理每个 delta 工具调用
    for delta_call in delta_calls or []:
        if not isinstance(delta_call, dict):
            # 不是字典格式，跳过
            continue

        # 获取工具调用索引
        index = delta_call.get("index")
        if not isinstance(index, int):
            # 没有索引，添加到末尾
            index = len(merged)

        # 确保 merged 列表长度足够
        while len(merged) <= index:
            # 添加默认工具调用结构
            merged.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})

        # 更新工具调用信息
        current = merged[index]
        current["id"] = delta_call.get("id") or current.get("id") or ""
        current["type"] = delta_call.get("type") or current.get("type") or "function"

        # 更新函数信息
        current_function = current.setdefault("function", {})
        delta_function = delta_call.get("function") or {}
        current_function["name"] = delta_function.get("name") or current_function.get("name") or ""
        # 拼接参数（流式响应中参数可能分块返回）
        current_function["arguments"] = (
            (current_function.get("arguments") or "") + (delta_function.get("arguments") or "")
        )

    return merged


# 核心函数：原始模型调用
def call_chat_model_with_messages_raw(
    messages: list[dict],  # 消息列表
    requested_model: str | None,  # 请求的模型名称
    *,
    purpose: str = "chat",  # 调用目的
    temperature: float = 0.4,  # 温度参数，控制生成文本的随机性
    extra_payload: dict | None = None,  # 额外的请求参数
    stream: bool = False,  # 是否使用流式响应
    on_stream_event: Callable[[dict[str, Any]], None] | None = None,  # 流式事件回调
):
    """原始调用模型，返回完整响应。"""
    # 解析模型名称
    model_name = resolve_model_name(requested_model)

    # 构建请求负载
    payload = {
        "model": model_name,  # 模型名称
        "messages": messages,  # 消息列表
        "temperature": temperature,  # 温度参数
        "stream": stream,  # 是否使用流式响应
    }

    # 添加额外参数
    if extra_payload:
        payload.update(extra_payload)

    # 关闭 Qwen3 的 thinking 模式（仅对 Qwen 家族生效）：
    # 显著提升 tool_call 的触发率，并避免前端看到 <think>...</think> 的重复输出。
    send_messages = _apply_disable_thinking(payload, model_name, messages)
    payload["messages"] = send_messages

    # 获取 API URL
    post_url = chat_completions_post_url()

    # 记录调试日志
    log_stage(
        f"llm.request.{purpose}",
        {
            "url": post_url,
            "model": model_name,
            "requested_model": requested_model,
            "purpose": purpose,
            "timeoutSeconds": settings.llm_timeout_seconds,
            "payload": payload,
        },
        enabled=settings.debug_runtime_logs,
        max_chars=settings.debug_log_max_chars,
        max_string_chars=settings.debug_log_max_string_chars,
    )

    # 检查 URL 是否配置
    if not post_url:
        raise LLMCallError("model.json 未配置 llm.base_url 或 llm.chat_completions_url，无法调用模型")

    try:
        # 发送 HTTP 请求
        response = requests.post(
            post_url,
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",  # API 密钥
                "Content-Type": "application/json",  # 内容类型
            },
            json=payload,  # 请求体
            timeout=settings.llm_timeout_seconds,  # 超时设置
            stream=stream,  # 是否流式响应
        )

        # 检查响应状态
        response.raise_for_status()

        # 处理编码问题
        enc = (response.encoding or "").lower()
        if not enc or enc in ("iso-8859-1", "latin-1"):
            response.encoding = "utf-8"

        # 处理流式响应
        if stream:
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls: list[dict] = []
            chunks: list[dict] = []

            thinking_block_active = False
            text_block_active = False
            tool_blocks: dict[int, dict] = {}

            for raw in response.iter_lines(decode_unicode=False):
                if not raw:
                    continue
                try:
                    line = raw.decode("utf-8").strip()
                except UnicodeDecodeError:
                    line = raw.decode("utf-8", errors="replace").strip()

                if not line.startswith("data:"):
                    continue

                chunk_text = line[5:].strip()
                if not chunk_text or chunk_text == "[DONE]":
                    if chunk_text == "[DONE]":
                        break
                    continue

                try:
                    data = json.loads(chunk_text)
                except json.JSONDecodeError as exc:
                    log_stage(
                        "llm.stream.chunk_json_skip",
                        {
                            "purpose": purpose,
                            "model": model_name,
                            "error": str(exc),
                            "preview": (chunk_text[:240] + "…") if len(chunk_text) > 240 else chunk_text,
                        },
                        enabled=True,
                        max_chars=settings.debug_log_max_chars,
                        max_string_chars=settings.debug_log_max_string_chars,
                    )
                    continue

                chunks.append(data)
                choices = data.get("choices") or []
                if not choices:
                    continue

                choice0 = choices[0] if isinstance(choices[0], dict) else {}
                delta = choice0.get("delta") or {}
                delta_text = _coerce_delta_text(delta.get("content"))
                if not delta_text:
                    delta_text = _coerce_delta_text(delta.get("text") or delta.get("output_text"))
                if not delta_text:
                    delta_text = _coerce_choice_text(choice0)
                delta_reasoning = _coerce_delta_text(
                    delta.get("reasoning_content") or delta.get("reasoning") or delta.get("reasoningContent")
                )
                delta_tool_calls = delta.get("tool_calls") or []

                if delta_reasoning:
                    if not thinking_block_active:
                        thinking_block_active = True
                        if on_stream_event:
                            on_stream_event({
                                "type": "content_block_start",
                                "index": 0,
                                "content_block": {"type": "thinking"},
                            })
                    if on_stream_event:
                        reasoning_parts.append(delta_reasoning)
                        on_stream_event({
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "thinking_delta", "thinking": delta_reasoning},
                        })

                if delta_text:
                    if thinking_block_active:
                        thinking_block_active = False
                        if on_stream_event:
                            on_stream_event({"type": "content_block_stop", "index": 0})
                    if not text_block_active:
                        text_block_active = True
                        if on_stream_event:
                            on_stream_event({
                                "type": "content_block_start",
                                "index": 1,
                                "content_block": {"type": "text"},
                            })
                    # 无论是否向上游透传流式事件，都必须累积正文；否则 compact 模式会被误判为空响应。
                    text_parts.append(delta_text)
                    if on_stream_event:
                        on_stream_event({
                            "type": "content_block_delta",
                            "index": 1,
                            "delta": {"type": "text_delta", "text": delta_text},
                        })

                for tc in delta_tool_calls:
                    index = tc.get("index", 0)
                    function = tc.get("function") or {}
                    if index not in tool_blocks and function.get("name"):
                        tool_blocks[index] = {
                            "name": function.get("name"),
                            "args": "",
                            "id": tc.get("id"),
                        }
                        if on_stream_event:
                            on_stream_event({
                                "type": "content_block_start",
                                "index": index,
                                "content_block": {
                                    "type": "tool_use",
                                    "id": tc.get("id"),
                                    "name": function.get("name"),
                                },
                            })
                    if function.get("arguments"):
                        if index in tool_blocks:
                            tool_blocks[index]["args"] += function["arguments"]
                        if on_stream_event:
                            on_stream_event({
                                "type": "content_block_delta",
                                "index": index,
                                "delta": {"type": "input_json_delta", "partial_json": function.get("arguments")},
                            })

                tool_calls = _merge_tool_call_chunks(tool_calls, delta_tool_calls)

            if thinking_block_active and on_stream_event:
                on_stream_event({"type": "content_block_stop", "index": 0})
            if text_block_active and on_stream_event:
                on_stream_event({"type": "content_block_stop", "index": 1})
            for idx in tool_blocks:
                if on_stream_event:
                    on_stream_event({"type": "content_block_stop", "index": idx})

            text = "".join(text_parts).strip()
            reasoning_content = "".join(reasoning_parts).strip()
            # 某些兼容网关在 stream 模式不走标准 delta.content，而只在 choice.message/text 回传正文。
            # 若增量拼接结果为空，回退到 chunks 中做一次聚合提取，避免误判为“模型返回内容为空”。
            if not text:
                fallback_parts: list[str] = []
                for chunk in chunks:
                    chunk_choices = chunk.get("choices") or []
                    if not chunk_choices:
                        continue
                    piece = _coerce_choice_text(chunk_choices[0])
                    if piece:
                        fallback_parts.append(piece)
                if fallback_parts:
                    text = "".join(fallback_parts).strip()
            message = {
                "role": "assistant",
                "content": text,
                "reasoning_content": reasoning_content,
            }
            if tool_calls:
                message["tool_calls"] = tool_calls

            data = {"object": "chat.completion.chunk.stream", "chunks": chunks, "message": message}
        else:
            # 处理非流式响应
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                raise LLMCallError("模型返回空结果")
            message = choices[0].get("message") or {}

        # 提取文本和工具调用
        text = _coerce_message_text(message)
        tool_calls = message.get("tool_calls") or []

        # 检查返回内容
        if not text and not tool_calls:
            raise LLMCallError("模型返回内容为空")

        # 记录响应日志
        log_stage(
            f"llm.response.{purpose}",
            {
                "statusCode": response.status_code,
                "model": model_name,
                "text": text,
                "toolCalls": tool_calls,
                "message": message,
                "raw": data,
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )

        # 返回响应结果
        return {
            "model_name": model_name,  # 使用的模型名称
            "text": text,  # 模型返回的文本
            "message": message,  # 完整消息
            "tool_calls": tool_calls,  # 工具调用
            "raw": data,  # 原始响应数据
        }
    except requests.RequestException as exc:
        # 记录错误日志
        log_stage(
            f"llm.error.{purpose}",
            {
                "model": model_name,
                "purpose": purpose,
                "error": str(exc),
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        # 抛出异常
        raise LLMCallError(f"模型调用失败: {exc}") from exc


# 核心函数：调用模型并确保返回非空内容
def call_chat_model_with_messages(
    messages: list[dict],  # 消息列表
    requested_model: str | None,  # 请求的模型名称
    *,
    purpose: str = "chat",  # 调用目的
    temperature: float = 0.4,  # 温度参数
    extra_payload: dict | None = None,  # 额外参数
    stream: bool = False,  # 是否使用流式响应
    on_stream_event: Callable[[dict[str, Any]], None] | None = None,  # 流式事件回调
):
    """调用模型，确保返回非空内容。"""
    # 调用原始模型函数
    response = call_chat_model_with_messages_raw(
        messages,
        requested_model,
        purpose=purpose,
        temperature=temperature,
        extra_payload=extra_payload,
        stream=stream,
        on_stream_event=on_stream_event,
    )

    # 彻底清除返回结果中的思考内容（某些 Qwen3 部署即使 disable_thinking 仍会返回 reasoning_content）
    if response.get("message"):
        response["message"].pop("reasoning_content", None)
        response["message"].pop("reasoning", None)
        response["message"].pop("reasoningContent", None)

    # 检查返回内容是否为空
    if not response["text"]:
        raise LLMCallError("模型返回内容为空")

    return response


# 核心函数：完整模型调用流程
def call_chat_model(
    content: str,  # 用户输入内容
    skill: str | None,  # 技能名称
    requested_model: str | None,  # 请求的模型名称
    runtime_context: dict | None = None,  # 运行时上下文
    memory_context: dict | None = None,  # 记忆上下文
    task_packet: dict | None = None,  # 任务包
    *,
    stream: bool = False,  # 是否使用流式响应
    on_stream_event: Callable[[dict[str, Any]], None] | None = None,  # 流式事件回调
):
    """完整调用模型流程，包括消息构建。"""
    # 构建消息列表
    messages = build_messages(content, skill, runtime_context, memory_context, task_packet)

    # 调用模型
    return call_chat_model_with_messages(
        messages,
        requested_model,
        purpose=f"skill.{skill or 'general'}",  # 构建调用目的
        temperature=0.4,  # 温度参数
        stream=stream,  # 是否使用流式响应
        on_stream_event=on_stream_event,  # 流式事件回调
    )


# 辅助函数：将纯文本转换为 HTML
def text_to_html(text: str) -> str:
    """将纯文本转换为 HTML 格式。"""
    # 处理文本块
    blocks = [block.strip() for block in text.replace("\r\n", "\n").split("\n\n") if block.strip()]
    html_parts = []

    # 处理每个文本块
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]

        # 检测是否为列表
        if all(line.startswith(("-", "*", "1.", "2.", "3.")) for line in lines):
            # 生成无序列表
            html_parts.append(
                "<ul>" + "".join(f"<li>{escape(line.lstrip('-*1234567890. '))}</li>" for line in lines) + "</ul>"
            )
        else:
            # 生成段落
            html_parts.append(f"<p>{escape(' '.join(lines))}</p>")

    # 返回 HTML 内容，确保至少返回一个空段落
    return "".join(html_parts) or "<p></p>"
