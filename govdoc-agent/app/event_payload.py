"""SSE 事件载荷瘦身与渲染元数据辅助。

背景：
- Claude 风格 SSE 事件（message_start / content_block_* / tool_result / waiting_user / error）
  在后端还承载了完整 taskPacket / registry snapshot / raw / plannerMeta 等重字段，
  既膨胀存库体积，也让前端拿到大量无用数据。
- 本模块提供两类能力：
  1. 渲染元数据辅助：display_text_for_step / purpose_for_step / 内容块 index 分段。
  2. 事件瘦身白名单：slim_event_for_persist 对 payload/delta/content_block 做统一过滤。

完整数据仍然保留在 V4ConversationRun.input_payload_json 与
V4ConversationMessage.meta_json，便于调试与回放。
"""
from __future__ import annotations

from typing import Any

from .a2a_runtime import ExecutionStep


PLANNING_THINKING_INDEX = 0
PLANNING_SUMMARY_TEXT_INDEX = 1
STEP_INDEX_BASE = 100
STEP_INDEX_STRIDE = 10


def tool_use_index_for_step(step_index: int) -> int:
    """子步骤 tool_use 内容块 index（与 text 块相邻，便于前端就近定位）。"""
    return STEP_INDEX_BASE + max(step_index, 0) * STEP_INDEX_STRIDE


def text_index_for_step(step_index: int) -> int:
    """子步骤 text 内容块 index（tool_use+1）。"""
    return tool_use_index_for_step(step_index) + 1


_SKILL_ACTION_LABELS: dict[str, str] = {
    "retrieval": "检索",
    "writing": "起草",
    "review": "审核",
    "dedup": "查重",
    "layout": "排版",
    "general": "处理",
}


_SKILL_PURPOSE_LABELS: dict[str, str] = {
    "retrieval": "retrieval_summary",
    "writing": "article_draft",
    "review": "review_report",
    "dedup": "dedup_report",
    "layout": "layout_suggestion",
    "general": "assistant_reply",
}


_SKILL_DONE_LABELS: dict[str, str] = {
    "retrieval": "检索完成",
    "writing": "写作完成",
    "review": "审核完成",
    "dedup": "查重完成",
    "layout": "排版完成",
    "general": "处理完成",
}


def action_label_for_skill(skill_name: str) -> str:
    return _SKILL_ACTION_LABELS.get((skill_name or "").strip().lower(), "处理")


def done_label_for_skill(skill_name: str) -> str:
    return _SKILL_DONE_LABELS.get((skill_name or "").strip().lower(), "处理完成")


def purpose_for_skill(skill_name: str) -> str:
    return _SKILL_PURPOSE_LABELS.get((skill_name or "").strip().lower(), "assistant_reply")


def display_text_for_step(step: ExecutionStep, *, phase: str = "running") -> str:
    """生成“正在检索 XXX / 正在起草 XXX / 检索完成”等用于前端状态展示的短文案。

    phase: running | done
    """
    skill = (step.skill_name or "").strip().lower()
    title = (step.title or "").strip()
    if phase == "done":
        if title:
            return f"已完成：{title}"
        return done_label_for_skill(skill)
    action = action_label_for_skill(skill)
    if title:
        return f"进行中：{title}"
    objective = (step.objective or "").strip()
    target = (objective.splitlines()[0].strip()[:60] if objective else "") or "当前任务"
    return f"正在{action}：{target}".strip()


# --- 瘦身白名单 --------------------------------------------------------------

_PLAN_STEP_KEEP = {
    "index",
    "skillName",
    "title",
    "objective",
    "dependsOn",
    "subtaskRole",
    # 前端 TodoList / 步骤卡片回显专用字段（由 _plan_payload 生成）：
    "displayTitle",
    "actionLabel",
    "pendingLabel",
    "runningLabel",
    "doneLabel",
    "status",
}
_PLAN_KEEP = {"intent", "summary", "steps", "requiresUserInput", "clarificationQuestion"}


def _slim_plan(plan_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(plan_payload, dict):
        return plan_payload
    slim: dict[str, Any] = {k: v for k, v in plan_payload.items() if k in _PLAN_KEEP}
    steps = plan_payload.get("steps") or []
    if isinstance(steps, list):
        slim["steps"] = [
            {k: v for k, v in step.items() if k in _PLAN_STEP_KEEP}
            for step in steps
            if isinstance(step, dict)
        ]
    return slim


def _slim_planner_meta(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    """Planner 元数据只保留对前端有意义的少量字段，不再下发 raw/toolCalls/messages。"""
    if not isinstance(meta, dict):
        return meta
    keep = {
        "planner",
        "fallback",
        "dispatchMode",
        "modelName",
        "requestedSkill",
        "normalization",
        "assistantText",
    }
    slim = {k: v for k, v in meta.items() if k in keep}
    reasoning = meta.get("reasoningContent")
    if isinstance(reasoning, str) and reasoning.strip():
        slim["reasoningSummary"] = reasoning.strip()[:400]
    return slim


def _slim_normalized_result(skill_name: str | None, result: Any) -> Any:
    """对较大的 normalizedResult 做摘要，避免 SSE 载荷膨胀。"""
    if not isinstance(result, dict):
        return result
    skill = (skill_name or "").strip().lower()
    slim: dict[str, Any] = {}
    if "source" in result:
        slim["source"] = result["source"]
    if skill == "retrieval":
        items = result.get("items") or []
        if isinstance(items, list):
            slim["items"] = [
                _slim_retrieval_item(item) for item in items[:5] if isinstance(item, dict)
            ]
            slim["itemsTotal"] = len(items)
        return slim
    if skill == "writing":
        # 写作结果用于前端直接落稿，保留完整正文
        return result
    if skill == "review":
        issues = result.get("issues") or []
        if isinstance(issues, list):
            slim["issuesCount"] = len(issues)
            slim["issuesPreview"] = [
                _slim_review_issue(item) for item in issues[:5] if isinstance(item, dict)
            ]
        return slim
    if skill == "dedup":
        items = result.get("items") or []
        if isinstance(items, list):
            slim["itemsCount"] = len(items)
            slim["itemsPreview"] = [
                _slim_dedup_item(item) for item in items[:5] if isinstance(item, dict)
            ]
        return slim
    if skill == "layout":
        templates = result.get("templates") or []
        if isinstance(templates, list):
            slim["templatesCount"] = len(templates)
            slim["templatesPreview"] = [
                {
                    "templateTitle": item.get("templateTitle") or item.get("title"),
                    "documentType": item.get("documentType"),
                }
                for item in templates[:5]
                if isinstance(item, dict)
            ]
        return slim
    # 默认：只取前若干字段
    for key in ("text", "message", "summary"):
        value = result.get(key)
        if isinstance(value, str):
            slim[key] = value[:400]
    return slim or result


def _slim_retrieval_item(item: dict[str, Any]) -> dict[str, Any]:
    title = item.get("title") or item.get("name") or "资料"
    summary = item.get("description") or item.get("summary") or item.get("content") or ""
    if isinstance(summary, str) and len(summary) > 240:
        summary = summary[:240] + "…"
    out: dict[str, Any] = {"title": title, "description": summary}
    if item.get("source"):
        out["source"] = item["source"]
    if item.get("url"):
        out["url"] = item["url"]
    return out


def _slim_review_issue(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("message", "errorWord", "suggestion", "category"):
        if item.get(key):
            out[key] = item[key]
    return out


def _slim_dedup_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title"),
        "duplicateRate": item.get("duplicateRate") or item.get("paperDuplicateRate"),
        "duplicateSentence": (item.get("duplicateSentence") or "")[:160],
    }


_MESSAGE_START_KEEP = {"phase", "runId", "taskId", "requestedSkill"}


def slim_message_start_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload
    slim: dict[str, Any] = {k: v for k, v in payload.items() if k in _MESSAGE_START_KEEP}
    # 从 taskPacket 中抽核心标识，避免下发整个 packet
    task_packet = payload.get("taskPacket") or {}
    if isinstance(task_packet, dict):
        if "task_id" in task_packet and "taskId" not in slim:
            slim["taskId"] = task_packet["task_id"]
        if "skill_name" in task_packet and "requestedSkill" not in slim:
            slim["requestedSkill"] = task_packet["skill_name"]
    return slim


def slim_tool_result_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload
    slim: dict[str, Any] = {}
    tool = payload.get("tool")
    if tool:
        slim["tool"] = tool
    for key in (
        "taskId",
        "skillName",
        "stepIndex",
        "stepTitle",
        "displayText",
        "retryable",
        "sourceState",
        "errorDetail",
        "selectedOption",
        "promptMenuInput",
        "resumeToken",
    ):
        if key in payload:
            slim[key] = payload[key]
    if tool == "a2a_planning":
        slim["steps"] = payload.get("steps")
        slim["plan"] = _slim_plan(payload.get("plan"))
        if "plannerMeta" in payload:
            slim["plannerMeta"] = _slim_planner_meta(payload.get("plannerMeta"))
    elif "normalizedResult" in payload:
        slim["normalizedResult"] = _slim_normalized_result(
            payload.get("skillName") or slim.get("skillName"),
            payload.get("normalizedResult"),
        )
    return slim


def slim_running_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload
    keep = {"taskId", "parentTaskId", "skillName", "stepIndex", "stepTitle", "displayText"}
    return {k: v for k, v in payload.items() if k in keep}


def slim_waiting_user_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload
    slim: dict[str, Any] = {}
    for key in (
        "taskId",
        "parentTaskId",
        "resumeToken",
        "sourceState",
        "errorDetail",
        "assistantMessageId",
        "artifactIds",
        "promptMenu",
    ):
        if key in payload:
            slim[key] = payload[key]
    return slim


def slim_error_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload
    keep = {"errorDetail", "assistantMessageId", "traceback"}
    return {k: v for k, v in payload.items() if k in keep}


def slim_message_delta_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload
    delta = payload.get("delta") or {}
    if not isinstance(delta, dict):
        return payload
    keep = {"stop_reason", "stop_sequence"}
    return {"delta": {k: v for k, v in delta.items() if k in keep}}


def slim_content_block(event_type: str, block: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(block, dict):
        return block
    block_type = block.get("type")
    keep = {"type", "purpose", "stepIndex", "stepTitle", "displayText", "skillName", "name"}
    return {k: v for k, v in block.items() if k in keep or k == block_type}


def slim_delta(event_type: str, delta: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(delta, dict):
        return delta
    # text_delta / thinking_delta / input_json_delta：只保留必要字段
    keep = {"type", "text", "thinking", "partial_json"}
    slim = {k: v for k, v in delta.items() if k in keep}
    # 限制 partial_json 长度（极少数情况下工具 arguments 过大）
    if isinstance(slim.get("partial_json"), str) and len(slim["partial_json"]) > 4000:
        slim["partial_json"] = slim["partial_json"][:4000] + "…"
    return slim


_PAYLOAD_SLIMMERS: dict[str, Any] = {
    "message_start": slim_message_start_payload,
    "tool_result": slim_tool_result_payload,
    # 检索等 legacy 合成路径：正文在 content_block_stop.payload，与 tool_result 白名单一致以便落库瘦身
    "content_block_stop": slim_tool_result_payload,
    "running": slim_running_payload,
    "waiting_user": slim_waiting_user_payload,
    "error": slim_error_payload,
    "message_delta": slim_message_delta_payload,
}


def slim_payload(event_type: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    slimmer = _PAYLOAD_SLIMMERS.get(event_type)
    if slimmer is None:
        return payload
    return slimmer(payload)


# --- DB 入库瘦身（v4_conversation_message.meta_json / v4_conversation_run.input_payload_json） ----
#
# 背景：MySQL TEXT 上限 65535 字节。planner_meta.raw 与 step_outcomes.html 等字段可能上百 KB，
# 需要在写库前做保守的字段截断，既避免 Data too long for column，也保留用于前端回放的关键展示信息。
# 事件流 SSE 推送走独立的 slim_payload 链路，此处只约束"持久化副本"。

_PLANNER_META_DB_DROP = {"raw", "messages"}
_PLANNER_META_DB_MAX_TEXT = 4000
_PLANNER_META_DB_MAX_ARGS = 2000


def slim_planner_meta_for_db(meta: Any) -> Any:
    """入库用的 planner_meta 瘦身：
    - 删除 ``raw`` / ``messages`` 等完整模型响应字段（体积最大，通常含 <think> 上万字符）。
    - ``reasoningContent`` / ``assistantText`` / ``directAnswer`` / ``summary`` 超长时截断。
    - ``toolCalls[*].function.arguments`` 截断到 ``_PLANNER_META_DB_MAX_ARGS``。
    其它字段原样保留，保证前端历史面板仍可渲染 planner / dispatchMode / normalization / modelName 等信息。
    """
    if not isinstance(meta, dict):
        return meta
    slim: dict[str, Any] = {}
    for key, value in meta.items():
        if key in _PLANNER_META_DB_DROP:
            continue
        if key in ("reasoningContent", "assistantText", "directAnswer", "summary", "error"):
            if isinstance(value, str) and len(value) > _PLANNER_META_DB_MAX_TEXT:
                slim[key] = value[:_PLANNER_META_DB_MAX_TEXT] + "…(truncated)"
                slim[f"{key}Length"] = len(value)
            else:
                slim[key] = value
            continue
        if key == "toolCalls" and isinstance(value, list):
            slim[key] = [_slim_tool_call_for_db(item) for item in value]
            continue
        slim[key] = value
    return slim


def _slim_tool_call_for_db(tool_call: Any) -> Any:
    if not isinstance(tool_call, dict):
        return tool_call
    slim = dict(tool_call)
    function = tool_call.get("function")
    if isinstance(function, dict):
        fn = dict(function)
        args = fn.get("arguments")
        if isinstance(args, str) and len(args) > _PLANNER_META_DB_MAX_ARGS:
            fn["arguments"] = args[:_PLANNER_META_DB_MAX_ARGS] + "…(truncated)"
            fn["argumentsLength"] = len(args)
        slim["function"] = fn
    return slim


_STEP_HTML_MAX = 20000
_STEP_TEXT_MAX = 6000
_STEP_REASONING_MAX = 4000


def slim_step_outcome_for_db(outcome: Any) -> Any:
    """入库用的 step_outcome 瘦身：截断超长 html / document / reasoning_content / summary，
    避免 assistant_message.meta_json 超过 TEXT 列上限。"""
    if not isinstance(outcome, dict):
        return outcome
    slim: dict[str, Any] = {}
    for key, value in outcome.items():
        if key == "html" and isinstance(value, str) and len(value) > _STEP_HTML_MAX:
            slim[key] = value[:_STEP_HTML_MAX] + "…(truncated)"
            slim["html_length"] = len(value)
            continue
        if key == "summary" and isinstance(value, str) and len(value) > _STEP_TEXT_MAX:
            slim[key] = value[:_STEP_TEXT_MAX] + "…(truncated)"
            continue
        if key == "reasoning_content" and isinstance(value, str) and len(value) > _STEP_REASONING_MAX:
            slim[key] = value[:_STEP_REASONING_MAX] + "…(truncated)"
            continue
        if key == "normalized_result":
            slim[key] = _slim_normalized_result_for_db(outcome.get("skill_name"), value)
            continue
        slim[key] = value
    return slim


def _slim_normalized_result_for_db(skill_name: Any, result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    slim = dict(result)
    doc = slim.get("document")
    if isinstance(doc, str) and len(doc) > _STEP_HTML_MAX:
        slim["document"] = doc[:_STEP_HTML_MAX] + "…(truncated)"
        slim["documentLength"] = len(doc)
    summary_text = slim.get("summary_text")
    if isinstance(summary_text, str) and len(summary_text) > _STEP_TEXT_MAX:
        slim["summary_text"] = summary_text[:_STEP_TEXT_MAX] + "…(truncated)"
    items = slim.get("items")
    if isinstance(items, list) and len(items) > 20:
        slim["items"] = items[:20]
        slim["itemsTotal"] = len(items)
    return slim


def safe_text_column_json(value: Any, max_bytes: int = 60000) -> str:
    """序列化 JSON，确保 utf-8 字节长度不超过 ``max_bytes``（默认预留 5KB 给 TEXT 列的编码开销）。

    若超长，按优先级依次剔除体积最大字段（``raw`` / ``stepOutcomes`` / ``leaderPlan`` / ``plannerMeta``），
    最后仍超长则对整个 JSON 做尾部截断并附加 ``_truncated`` 标记，保证 INSERT 可成功。
    """
    import json as _json_mod

    try:
        text = _json_mod.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = _json_mod.dumps({"_error": "serialize_failed"}, ensure_ascii=False)
        return text
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    if not isinstance(value, dict):
        truncated = text[: max_bytes // 2]
        return _json_mod.dumps({"_truncated": True, "preview": truncated}, ensure_ascii=False)

    trimmed = dict(value)
    fallback_note: dict[str, Any] = {}
    for drop_key in ("plannerMeta", "stepOutcomes", "leaderPlan", "normalizedResult", "handoffTrace", "taskPacket"):
        if len(_json_mod.dumps(trimmed, ensure_ascii=False).encode("utf-8")) <= max_bytes:
            break
        if drop_key in trimmed:
            fallback_note[f"{drop_key}_dropped"] = True
            trimmed.pop(drop_key, None)
    text = _json_mod.dumps({**trimmed, **({"_trimmed": fallback_note} if fallback_note else {})}, ensure_ascii=False)
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    # 最终兜底：硬截断字节串
    encoded = text.encode("utf-8")[: max_bytes - 32]
    # 确保不在 UTF-8 字符中间切断
    safe_text = encoded.decode("utf-8", errors="ignore")
    return _json_mod.dumps({"_truncated": True, "preview": safe_text}, ensure_ascii=False)
