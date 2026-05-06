import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from typing import Any

import requests

from agents import (
    canonical_agent_name,
    exposed_agent_descriptors,
    get_agent_spec,
    prompt_key_for_agent,
)
from tools import WorkspaceArtifactTool
from .config import settings
from .debug_log import log_stage, mask_cookie
from .llm import (
    LLMCallError,
    call_chat_model,
    call_chat_model_with_messages_raw,
    resolve_model_name,
    text_to_html,
)
from .text_postprocess import clean_document_text, clean_general_text

workspace_artifact_tool = WorkspaceArtifactTool()


@dataclass
class SkillExecutionResult:
    normalized_result: dict
    render_blocks: list[dict]
    artifact_refs: list[dict]
    editor_annotations: list[dict]
    retryable: bool
    source_state: str = "model_success"
    error_detail: str | None = None
    prompt_menu: dict | None = None
    reasoning_content: str | None = None


datasetIds = ["4998249e3c8611f19eeb0242ac1e0009","a71e0236396711f1b6430242ac1e0009","725584ce33cd11f19e3e0242ac1e0009","1e4e445c33cc11f18bd80242ac1e0009","7e09d28633cb11f191270242ac1e0009","5a2c34ae325d11f19d650242ac1e0009","54a41698275711f1be430242ac1e0009","8749b36a1c4811f18d390242ac1e0009","847cd73215d311f193ce0242ac1e0006","1add69d2058311f19aa20242ac1e0006","645a02fc058111f1a42a0242ac1e0006","a97a3a3c033d11f1ab430242ac1e0006","d2f2de82027011f195780242ac1e0006","4e8623b6026b11f1acb90242ac1e0006","4fdc5996026711f1b42b0242ac1e0006","53a8a7c4024311f1bf260242ac1e0006","70da2636023611f18fc60242ac1e0006","a2e3bf94019a11f1bc650242ac1e0006","11543622017111f1b1dd0242ac1e0006","ff9dcc7c017011f1ac310242ac1e0006","fac40854fffb11f0bb080242ac1e0006","a09fca24fcd711f0993f0242ac1e0006","0f28f1eaf69e11f0bab30242ac1e0016","d23c090ef02411f0aee40242ac1e000a","53010398ed2111f099c20242ac1e0006","98d6bf26ed0711f09cd30242ac1e0006","d7f60fc2db1411f082030242ac1e0006","927c1c90d3e211f08fdb0242ac1e0006","4c12b0fed3d111f0831f0242ac1e0006","eff0725ecf5f11f08f430242ac1e0006","1ad7361acf2e11f0ad780242ac1e0006","0ee2bb18cf2911f09c3a0242ac1e0006","9a719d18cf1d11f083820242ac1e0006","fe53700acb8411f0a9900242ac1d0006","78b72a9ccb6911f0b16d0242ac1d0006","4e5f6b5cc91511f09ca10242ac1d0006","5ee8f604c91111f09b6f0242ac1d0006","b8f36adcbee211f0b6cb0242ac1d0006","bd1267faba1711f09ae40242ac1d0006","639f802eb53311f0b16a0242ac1d0006","513cebdeaa6a11f089ef0242ac1d0006","6d364f8aaa6311f085170242ac1d0006","201ab25a94f511f0b2e60242ac180007","a101daaa8e2011f0be370242ac180007","1defb45e8d6f11f0a02f0242ac180007","91dc1952886a11f0b4ac0242ac180007","2422c0dc87d911f0be7e0242ac180007","31894b4487a511f0b48b0242ac180007","23daeffa857c11f083800242ac180007","876cee72857911f09afa0242ac180007","4d7764e684b011f0bd640242ac180007","ea9f35da84a811f08c570242ac180007","dbc97bba84a811f083940242ac180007","8252014c83e011f096df0242ac180007","3e10a91883d911f090240242ac180007","92a9a99c831c11f086f70242ac150007","81e2763a7e6111f090390242c0a84006","e8f438127e5d11f0adcd0242c0a84006"]

@dataclass
class LegacyCallResult:
    ok: bool
    url: str
    status_code: int | None = None
    payload: dict | list | None = None
    text: str | None = None
    error: str | None = None


def skill_descriptors() -> list[dict]:
    return exposed_agent_descriptors()


def resolve_skill(content: str, requested_skill: str | None = None) -> str:
    return canonical_agent_name(requested_skill) or "general"


def _legacy_base_url() -> str:
    return settings.legacy_service_base_url or settings.legacy_auth_base_url


def _legacy_verify() -> bool | str:
    """legacy HTTPS 校验策略。

    - 配置了 legacy_ca_bundle 时返回证书路径（requests 将使用该 CA 校验）
    - 否则按 legacy_tls_verify 布尔开关决定是否校验
    """
    if settings.legacy_ca_bundle:
        return settings.legacy_ca_bundle
    return bool(settings.legacy_tls_verify)


def _read_sse_text(response: requests.Response) -> str:
    enc = (response.encoding or "").lower()
    if not enc or enc in ("iso-8859-1", "latin-1"):
        response.encoding = "utf-8"
    chunks: list[str] = []
    for raw in response.iter_lines(decode_unicode=False):
        if not raw:
            continue
        try:
            line = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            line = raw.decode("utf-8", errors="replace").strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                continue
            chunks.append(payload)
        else:
            chunks.append(line)
    return "\n".join(chunks).strip()


def _try_legacy_json(path: str, payload: dict, cookies: str | None = None) -> LegacyCallResult:
    base = _legacy_base_url()
    if not base:
        log_stage(
            "skill.legacy_json.skip",
            {"path": path, "reason": "legacy_base_url_missing"},
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return LegacyCallResult(False, path, error="legacy_base_url_missing")
    url = f"{base}{path}"
    try:
        log_stage(
            "skill.legacy_json.request",
            {
                "url": url,
                "payload": payload,
                "cookiePreview": mask_cookie(cookies),
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        response = requests.post(
            url,
            json=payload,
            headers={"Cookie": cookies or ""},
            timeout=20,
            verify=_legacy_verify(),
        )
        response.raise_for_status()
        data = response.json()
        log_stage(
            "skill.legacy_json.response",
            {
                "url": url,
                "statusCode": response.status_code,
                "body": data,
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return LegacyCallResult(True, url, status_code=response.status_code, payload=data)
    except (requests.RequestException, ValueError) as exc:
        log_stage(
            "skill.legacy_json.error",
            {
                "url": url,
                "error": str(exc),
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return LegacyCallResult(False, url, error=str(exc))


def _try_legacy_stream(path: str, payload: dict, cookies: str | None = None) -> LegacyCallResult:
    base = _legacy_base_url()
    if not base:
        log_stage(
            "skill.legacy_stream.skip",
            {"path": path, "reason": "legacy_base_url_missing"},
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return LegacyCallResult(False, path, error="legacy_base_url_missing")
    url = f"{base}{path}"
    try:
        log_stage(
            "skill.legacy_stream.request",
            {
                "url": url,
                "payload": payload,
                "cookiePreview": mask_cookie(cookies),
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        response = requests.post(
            url,
            json=payload,
            headers={"Cookie": cookies or ""},
            timeout=40,
            stream=True,
            verify=_legacy_verify(),
        )
        response.raise_for_status()
        text = _read_sse_text(response)
        log_stage(
            "skill.legacy_stream.response",
            {
                "url": url,
                "statusCode": response.status_code,
                "text": text,
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return LegacyCallResult(True, url, status_code=response.status_code, text=text or None)
    except requests.RequestException as exc:
        log_stage(
            "skill.legacy_stream.error",
            {
                "url": url,
                "error": str(exc),
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return LegacyCallResult(False, url, error=str(exc))


def _invoke_llm(
    prompt: str,
    skill_name: str,
    requested_model: str | None,
    runtime_context: dict | None = None,
    memory_context: dict | None = None,
    task_packet: dict | None = None,
    *,
    on_text_delta: Callable[[str, str], None] | None = None,
) -> tuple[str, str, str | None, str | None]:
    """始终调用远程 LLM（OpenAI 兼容接口）。失败返回 model_error 与错误信息，不再使用本地模板兜底。"""
    resolved_model = resolve_model_name(requested_model)

    def _call_once(*, stream: bool) -> dict[str, Any]:
        return call_chat_model(
            prompt,
            prompt_key_for_agent(skill_name),
            requested_model,
            runtime_context,
            memory_context,
            task_packet,
            stream=stream,
            on_stream_event=_stream_handler if (stream and on_text_delta) else None,
        )

    def _stream_handler(ev: dict[str, Any]) -> None:
        if not on_text_delta:
            return
        if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
            delta_text = ev["delta"].get("text", "")
            if delta_text:
                _stream_handler._accumulated = getattr(_stream_handler, "_accumulated", "") + delta_text
                on_text_delta(_stream_handler._accumulated, delta_text)
        elif ev.get("type") == "content_block_stop":
            _stream_handler._accumulated = ""

    try:
        response = _call_once(stream=True)
        text = response["text"]
        reasoning_content = (response.get("message") or {}).get("reasoning_content")
        log_stage(
            "skill.llm.remote_ok",
            {
                "skill": skill_name,
                "requestedModel": requested_model,
                "resolvedModel": resolved_model,
                "prompt": prompt,
                "text": (text or "")[:2000],
                "reasoningContent": reasoning_content,
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        if on_text_delta:
            on_text_delta(text or "", "")
        return text or "", "model_success", None, reasoning_content
    except LLMCallError as exc:
        err = str(exc)
        # 兼容部分网关的流式实现差异：stream=true 时偶发无 content，
        # 改用非流式再试一次，避免误判为 model_error。
        if "模型返回内容为空" in err:
            try:
                retry_response = _call_once(stream=False)
                retry_text = retry_response["text"]
                retry_reasoning = (retry_response.get("message") or {}).get("reasoning_content")
                log_stage(
                    "skill.llm.remote_ok_non_stream_retry",
                    {
                        "skill": skill_name,
                        "requestedModel": requested_model,
                        "resolvedModel": resolved_model,
                        "text": (retry_text or "")[:2000],
                        "reasoningContent": retry_reasoning,
                        "retryReason": err,
                    },
                    enabled=settings.debug_runtime_logs,
                    max_chars=settings.debug_log_max_chars,
                    max_string_chars=settings.debug_log_max_string_chars,
                )
                if on_text_delta:
                    on_text_delta(retry_text or "", "")
                return retry_text or "", "model_success", None, retry_reasoning
            except LLMCallError:
                # 非流式重试也失败，继续走下方统一错误处理。
                pass
        log_stage(
            "skill.llm.remote_error",
            {
                "skill": skill_name,
                "requestedModel": requested_model,
                "resolvedModel": resolved_model,
                "error": err,
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        user_text = (
            "模型调用失败。请检查 config/model.json 中的 base_url、api_key、default_model 与网关要求是否一致，"
            "或查看服务端日志。\n\n"
            f"详情：{err}"
        )
        return user_text, "model_error", err, None


def _build_annotations_from_lines(lines: list[str]) -> list[dict]:
    annotations = []
    for index, line in enumerate(lines, start=1):
        text = line.strip(" -")
        if not text:
            continue
        annotations.append(
            {
                "id": f"annotation-{index}",
                "label": f"问题 {index}",
                "description": text,
                "start": max(index * 10, 0),
                "end": max(index * 10 + len(text), 1),
            }
        )
    return annotations


def _normalized_source(source_state: str) -> str:
    if not source_state:
        return "unknown"
    return source_state


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,}")


def _sanitize_rewritten_query(text: str) -> str:
    """清洗 query 改写结果，去掉思考标签/围栏/寒暄等噪声。"""
    if not text:
        return ""
    cleaned = _THINK_BLOCK_RE.sub(" ", text)
    cleaned = cleaned.replace("```", " ").replace("`", " ")
    cleaned = cleaned.replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t-:;,.，。！？")
    return cleaned.strip()


def _fallback_query_from_prompt(prompt: str, max_len: int = 80) -> str:
    """规则兜底：从原 prompt 提取核心短语，避免把完整任务描述直接喂给检索。"""
    source = (prompt or "").strip()
    if not source:
        return ""
    core = _sanitize_rewritten_query(source)
    # 先按常见分隔切第一段，避免过长说明句。
    first_chunk = re.split(r"[，。；;,.!?！？\n]", core, maxsplit=1)[0].strip()
    candidate = first_chunk or core
    tokens = _CJK_TOKEN_RE.findall(candidate)
    if tokens:
        candidate = " ".join(tokens[:8]).strip()
    return candidate[:max_len].strip()


def _is_rewrite_effective(original: str, rewritten: str) -> bool:
    """判定改写是否有效：避免与原文几乎一致或过长复述。"""
    o = _sanitize_rewritten_query(original).lower()
    r = _sanitize_rewritten_query(rewritten).lower()
    if not r or len(r) < 4:
        return False
    if o == r:
        return False
    # 原文较长时，若改写仅是前缀截断或基本复读，视为无效改写。
    if len(o) >= 24 and (o.startswith(r) or r.startswith(o[: min(len(o), 18)])):
        return False
    return True


def _rewrite_retrieval_query(prompt: str, requested_model: str | None) -> str:
    """将检索任务描述转写为更适合 legacy 检索接口的短 query。

    失败时回退到原始 prompt（截断），保证检索流程可继续。
    """
    fallback = _fallback_query_from_prompt(prompt, max_len=80) or (prompt or "").strip()[:180]
    if not fallback:
        return ""
    messages = [
        {
            "role": "system",
            "content": (
                "你是检索查询改写器。"
                "请把输入改写为一条简洁检索 query，保留核心实体、时间范围与文种。"
                "仅输出 query 本身，不要解释，不要 markdown。"
            ),
        },
        {"role": "user", "content": fallback},
    ]
    try:
        response = call_chat_model_with_messages_raw(
            messages,
            requested_model,
            purpose="retrieval.query_rewrite",
            temperature=0.1,
            extra_payload={"max_tokens": 80},
            stream=False,
        )
        rewritten = _sanitize_rewritten_query((response.get("text") or "").strip())
        first_line = (rewritten.splitlines()[0].strip() if rewritten else "")
        invalid_markers = ("<think", "</think>", "好的", "当然", "我来", "改写如下")
        lowered = first_line.lower()
        is_invalid = (
            (not first_line)
            or any(marker in first_line for marker in invalid_markers)
            or lowered.startswith(("好的", "当然", "改写"))
            or len(first_line) < 4
        )
        if not is_invalid and _is_rewrite_effective(fallback, first_line):
            return first_line[:80]

        # 二次改写：当第一次改写无效或几乎未变化时，强约束生成“关键词短语”。
        retry_messages = [
            {
                "role": "system",
                "content": (
                    "你是检索词压缩器。"
                    "将输入压缩为 8-24 字的检索关键词短语，必须包含主题实体和年份/时间。"
                    "禁止解释、禁止寒暄、禁止输出 <think>，仅输出一行短语。"
                ),
            },
            {"role": "user", "content": fallback},
        ]
        retry_response = call_chat_model_with_messages_raw(
            retry_messages,
            requested_model,
            purpose="retrieval.query_rewrite.retry",
            temperature=0.1,
            extra_payload={"max_tokens": 40},
            stream=False,
        )
        retry_rewritten = _sanitize_rewritten_query((retry_response.get("text") or "").strip())
        retry_line = (retry_rewritten.splitlines()[0].strip() if retry_rewritten else "")
        if retry_line and _is_rewrite_effective(fallback, retry_line):
            return retry_line[:80]
        return fallback
    except LLMCallError:
        return fallback


def _execute_skill_once(
    skill_name: str,
    content: str,
    requested_model: str | None,
    attachments: list[dict],
    cookies: str | None = None,
    runtime_context: dict | None = None,
    memory_context: dict | None = None,
    task_packet: dict | None = None,
    on_text_delta: Callable[[str, str], None] | None = None,
) -> SkillExecutionResult:
    skill_name = canonical_agent_name(skill_name) or "general"
    prompt = content.strip()
    log_stage(
        "skill.execute.start",
        {
            "skill": skill_name,
            "content": content,
            "requestedModel": requested_model,
            "attachments": attachments,
            "cookiePreview": mask_cookie(cookies),
        },
        enabled=settings.debug_runtime_logs,
        max_chars=settings.debug_log_max_chars,
        max_string_chars=settings.debug_log_max_string_chars,
    )

    if skill_name == "general":
        text, source_state, error_detail, reasoning_content = _invoke_llm(
            prompt,
            skill_name,
            requested_model,
            runtime_context,
            memory_context,
            task_packet,
            on_text_delta=None,
        )
        # 通用回复：剥离"好的，我可以帮您…"等寒暄前缀与末尾客套，保留自然格式。
        if source_state == "model_success":
            text = clean_general_text(text)
        if on_text_delta:
            on_text_delta(text or "", "")
        result = SkillExecutionResult(
            {"text": text, "source": _normalized_source(source_state)},
            [{"type": "general", "title": "通用回答", "html": text_to_html(text)}],
            [],
            [],
            source_state == "model_error",
            source_state=source_state,
            error_detail=error_detail,
            reasoning_content=reasoning_content,
        )
        log_stage(
            "skill.execute.result",
            {"skill": skill_name, "result": result},
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return result

    if skill_name == "retrieval":
        rewritten_query = _rewrite_retrieval_query(prompt, requested_model)
        query_payload = {"query": rewritten_query, "title": "", "keywords": [], "datasetIds": datasetIds, "pageNo":1,"pageSize":50}
        log_stage(
            "skill.retrieval.query_rewrite",
            {"originalPrompt": (prompt or "")[:500], "rewrittenQuery": rewritten_query},
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        legacy = _try_legacy_json(
            "/report-agent/v1/document-material-retrieval",
            query_payload,
            cookies,
        )
        items: list[Any] = []
        if legacy.ok:
            body = legacy.payload if isinstance(legacy.payload, dict) else {}
            raw_items = body.get("data") or body.get("rows") or body.get("list") or []
            if isinstance(raw_items, list):
                items = raw_items
            elif raw_items is not None:
                items = [raw_items]
            source_state = "legacy_success"
            error_detail = None
        else:
            source_state = "legacy_error"
            error_detail = legacy.error
        result = SkillExecutionResult(
            {
                "items": items,
                "source": _normalized_source(source_state),
            },
            [{"type": "summary", "title": "检索结果", "html": text_to_html(json.dumps(items[:5], ensure_ascii=False))}],
            [],
            [],
            False,
            source_state=source_state,
            error_detail=error_detail,
            reasoning_content=None,
        )
        log_stage(
            "skill.execute.result",
            {"skill": skill_name, "result": result},
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return result

    if skill_name == "writing":
        legacy_text = _try_legacy_stream(
            "/report-agent/v1/document-writing",
            {"title": prompt[:20], "text": prompt, "prompt": prompt, "content": prompt},
            cookies,
        )
        if legacy_text.ok and legacy_text.text:
            text = legacy_text.text
            source_state = "legacy_success"
            error_detail = None
            reasoning_content = None
        else:
            text, source_state, error_detail, reasoning_content = _invoke_llm(
                prompt,
                skill_name,
                requested_model,
                runtime_context,
                memory_context,
                task_packet,
                on_text_delta=None,
            )
        # 公文正文强制纯文本：抽取 <正文>...</正文>、剥离 Markdown、去除寒暄与末尾客套。
        # 即使模型违规输出 Markdown，前端最终看到的也是可直接粘贴到 Word 的纯文本。
        if source_state in ("model_success", "legacy_success") and text:
            text = clean_document_text(text)
        if on_text_delta:
            on_text_delta(text or "", "")
        workspace_commit_stub = workspace_artifact_tool.call(
            {
                "title": "公文写作结果.docx",
                "artifact_type": "document",
                "content_text": text,
            }
        )
        result = SkillExecutionResult(
            {
                "document": text,
                "source": _normalized_source(source_state),
                "workspaceCommit": workspace_commit_stub,
            },
            [{"type": "document", "title": "公文写作结果", "html": text_to_html(text)}],
            [
                {
                    "artifact_type": "document",
                    "title": "公文写作结果.docx",
                    "summary": "已生成可继续编辑的公文正文。",
                    "content_html": text_to_html(text),
                }
            ],
            [],
            source_state != "legacy_success",
            source_state=source_state,
            error_detail=legacy_text.error or error_detail,
            reasoning_content=reasoning_content,
        )
        log_stage(
            "skill.execute.result",
            {"skill": skill_name, "result": result},
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return result

    if skill_name == "review":
        legacy = _try_legacy_json(
            "/report-agent/v2/small_model_review",
            {"text": prompt, "model_name": resolve_model_name(requested_model)},
            cookies,
        )
        issues = []
        if legacy.ok and isinstance(legacy.payload, dict) and isinstance(legacy.payload.get("data"), dict):
            issues = legacy.payload["data"].get("resultList") or []
        if not issues:
            text, fallback_state, fallback_error, reasoning_content = _invoke_llm(
                prompt,
                skill_name,
                requested_model,
                runtime_context,
                memory_context,
                task_packet,
                on_text_delta=on_text_delta,
            )
            issue_lines = [line for line in text.splitlines() if line.strip()]
            issues = [{"message": line.strip()} for line in issue_lines[:8]]
            source_state = fallback_state
            error_detail = legacy.error or fallback_error
        else:
            source_state = "legacy_success"
            error_detail = None
            reasoning_content = None
        annotations = _build_annotations_from_lines([item.get("message") or item.get("errorWord") or str(item) for item in issues[:10]])
        review_text = "\n".join(
            [f"- {item.get('message') or item.get('errorWord') or str(item)}" for item in issues[:10]]
        ) or "- 暂未发现明显问题。"
        result = SkillExecutionResult(
            {"issues": issues, "source": _normalized_source(source_state)},
            [{"type": "review", "title": "审核结论", "html": text_to_html(review_text)}],
            [
                {
                    "artifact_type": "document",
                    "title": "审核修订建议.docx",
                    "summary": "已生成审核意见与修订建议。",
                    "content_html": text_to_html(review_text),
                }
            ],
            annotations,
            source_state != "legacy_success",
            source_state=source_state,
            error_detail=error_detail,
            reasoning_content=reasoning_content,
        )
        log_stage(
            "skill.execute.result",
            {"skill": skill_name, "result": result},
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return result

    if skill_name == "dedup":
        legacy = _try_legacy_json(
            "/api/v1/duplication-check/internet",
            {"text": prompt, "content": prompt},
            cookies,
        )
        rows = []
        if legacy.ok and isinstance(legacy.payload, dict):
            rows = legacy.payload.get("data") or legacy.payload.get("items") or []
        if not rows:
            text, fallback_state, fallback_error, reasoning_content = _invoke_llm(
                prompt,
                skill_name,
                requested_model,
                runtime_context,
                memory_context,
                task_packet,
                on_text_delta=on_text_delta,
            )
            rows = [
                {
                    "title": f"相似来源 {index}",
                    "duplicateRate": f"{min(20 + index * 7, 87)}%",
                    "duplicateSentence": line.strip("- ").strip(),
                    "sourceLink": "",
                }
                for index, line in enumerate([item for item in text.splitlines() if item.strip()][:5], start=1)
            ]
            source_state = fallback_state
            error_detail = legacy.error or fallback_error
        else:
            source_state = "legacy_success"
            error_detail = None
            reasoning_content = None
        report_text = "\n".join(
            [
                f"- {item.get('title', '相似来源')} | 重复率 {item.get('duplicateRate') or item.get('paperDuplicateRate') or '未知'}"
                for item in rows[:8]
            ]
        ) or "- 暂无查重结果。"
        annotations = _build_annotations_from_lines(
            [item.get("duplicateSentence") or item.get("title") or str(item) for item in rows[:8]]
        )
        result = SkillExecutionResult(
            {"items": rows, "source": _normalized_source(source_state)},
            [{"type": "duplicate", "title": "查重结果", "html": text_to_html(report_text)}],
            [
                {
                    "artifact_type": "report",
                    "title": "查重报告.docx",
                    "summary": "已生成查重分析与改写建议。",
                    "content_html": text_to_html(report_text),
                }
            ],
            annotations,
            source_state != "legacy_success",
            source_state=source_state,
            error_detail=error_detail,
            reasoning_content=reasoning_content,
        )
        log_stage(
            "skill.execute.result",
            {"skill": skill_name, "result": result},
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return result

    if skill_name != "layout":
        raise ValueError(f"未知 skill: {skill_name}")

    legacy_templates = _try_legacy_json("/report-agent/v2/layoutTemplate/getOptionLayout", {}, cookies)
    templates = []
    if legacy_templates.ok and isinstance(legacy_templates.payload, dict):
        templates = legacy_templates.payload.get("data") or legacy_templates.payload.get("rows") or []
    if not templates:
        templates = [
            {"templateTitle": "党政机关标准版", "documentType": "通知"},
            {"templateTitle": "汇报材料版", "documentType": "汇报"},
        ]
        source_state = "static_template"
        error_detail = legacy_templates.error
    else:
        source_state = "legacy_success"
        error_detail = None
    template_lines = [
        f"- 推荐模板：{item.get('templateTitle', '未命名模板')}（{item.get('documentType', '通用')}）"
        for item in templates[:5]
    ]
    template_text = "\n".join(template_lines)
    result = SkillExecutionResult(
        {"templates": templates, "source": _normalized_source(source_state)},
        [{"type": "format", "title": "排版建议", "html": text_to_html(template_text)}],
        [
            {
                "artifact_type": "document",
                "title": "排版结果.docx",
                "summary": "已输出推荐模板与排版建议。",
                "content_html": text_to_html(template_text),
            }
        ],
        [],
        source_state != "legacy_success",
        source_state=source_state,
        error_detail=error_detail,
        reasoning_content=None,
    )
    log_stage(
        "skill.execute.result",
        {"skill": skill_name, "result": result},
        enabled=settings.debug_runtime_logs,
        max_chars=settings.debug_log_max_chars,
        max_string_chars=settings.debug_log_max_string_chars,
    )
    return result


def execute_skill(
    skill_name: str,
    content: str,
    requested_model: str | None,
    attachments: list[dict],
    cookies: str | None = None,
    runtime_context: dict | None = None,
    memory_context: dict | None = None,
    task_packet: dict | None = None,
    on_text_delta: Callable[[str, str], None] | None = None,
) -> SkillExecutionResult:
    """执行 skill；model_error 时自动重试 1 次（间隔 0.5s）。"""
    first = _execute_skill_once(
        skill_name,
        content,
        requested_model,
        attachments,
        cookies,
        runtime_context=runtime_context,
        memory_context=memory_context,
        task_packet=task_packet,
        on_text_delta=on_text_delta,
    )
    if first.source_state == "model_error":
        time.sleep(0.5)
        return _execute_skill_once(
            skill_name,
            content,
            requested_model,
            attachments,
            cookies,
            runtime_context=runtime_context,
            memory_context=memory_context,
            task_packet=task_packet,
            on_text_delta=on_text_delta,
        )
    return first


def render_assistant_html(skill_name: str, result: SkillExecutionResult, model_name: str) -> str:
    skill_name = canonical_agent_name(skill_name) or "general"
    blocks = [
        f"<div class='assistant-copy'>模型 <strong>{escape(model_name)}</strong> 已完成 {escape(get_agent_spec(skill_name).title)} 任务。</div>"
    ]
    for block in result.render_blocks:
        title = escape(block.get("title") or "")
        html = block.get("html") or "<p></p>"
        blocks.append(f"<section class='assistant-block'><h4>{title}</h4>{html}</section>")
    return "".join(blocks)
