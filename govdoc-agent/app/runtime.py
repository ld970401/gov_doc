import json
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .a2a_runtime import (
    ExecutionPlan,
    ExecutionStep,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    a2a_task_registry,
    build_handoff_content,
    build_root_task_packet,
    build_synthetic_dispatch_tool_calls,
    build_subtask_packet,
    format_dispatch_tool_result_json,
    title_for_skill,
)
from .event_payload import (
    PLANNING_SUMMARY_TEXT_INDEX,
    PLANNING_THINKING_INDEX,
    display_text_for_step,
    done_label_for_skill,
    purpose_for_skill,
    safe_text_column_json,
    slim_content_block,
    slim_delta,
    slim_payload,
    slim_planner_meta_for_db,
    slim_step_outcome_for_db,
    text_index_for_step,
    tool_use_index_for_step,
)
from .compression import (
    SummaryCompressionBudget,
    apply_leader_context_guard,
    build_structured_summary,
    compress_summary_text,
    estimate_tokens,
    summarize_memory_for_context,
)
from .config import settings
from .debug_log import log_stage, mask_cookie
from .models import (
    V4CompressionSnapshot,
    V4Conversation,
    V4ConversationArtifact,
    V4ConversationMessage,
    V4ConversationRun,
    V4TaskEvent,
    V4UserProfile,
    V4WorkspaceAttachmentLink,
    V4WorkspaceNode,
    V4WorkspaceVersion,
)
from .planner import build_model_execution_plan
from agents.main_agent import MainAgent
from .agent_capability_adapter import (
    SkillExecutionResult,
    execute_skill,
    render_assistant_html,
)
from .storage import (
    clear_user_memory_subdir,
    read_user_doc,
    write_memory_doc,
    write_workspace_version,
)
from .llm import text_to_html
from tools.agent_tool import AgentTool


@dataclass
class RuntimeTaskEvent:
    """内容块级流式事件。"""
    type: str
    index: int = 0
    delta: dict | None = None
    content_block: dict | None = None
    payload: dict | None = None


INTERACTIVE_SKILLS = {"retrieval", "writing", "review", "dedup", "layout"}  # 交互型技能集合
MEMORY_MANUAL_HEADING = "## 手工备注"  # 记忆文件中的手工备注标题
GENERIC_ASSISTANT_CONTENTS = {
    "主 Agent 回复",
    "检索结果",
    "审核结果",
    "查重报告",
    "排版结果",
    "公文写作结果",
    "任务未执行",
    "执行失败",
}  # 通用助手内容集合


class TaskRegistry:
    """任务注册表，用于生成唯一的任务 ID。"""
    def __init__(self) -> None:
        """初始化任务注册表。"""
        self._counters: dict[str, int] = {}  # 按会话 ID 存储任务计数器

    def next_task_id(self, conversation_id: str) -> str:
        """生成下一个任务 ID。"""
        value = self._counters.get(conversation_id, 0) + 1  # 自增计数器
        self._counters[conversation_id] = value  # 更新计数器
        return f"task_{conversation_id[:8]}_{value:04d}"  # 生成任务 ID 格式：task_会话ID前8位_4位序号


task_registry = TaskRegistry()  # 全局任务注册表实例


def clip_title(text: str) -> str:
    """裁剪标题长度，最多24个字符。"""
    return (text or "新对话").strip()[:24] or "新对话"


def _json(value) -> str:
    """将对象转换为 JSON 字符串。"""
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None, fallback):
    """从 JSON 字符串加载对象，失败时返回默认值。"""
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _trim_prompt_text(value: str, limit: int = 320) -> str:
    """裁剪提示文本长度。"""
    text = re.sub(r"\s+", " ", (value or "").strip())  # 替换连续空白为单个空格
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"  # 超出限制时添加省略号


def _index_relative_paths(markdown: str | None, *, prefix: str) -> list[str]:
    """从 Markdown 中提取相对路径。"""
    if not markdown:
        return []
    found: list[str] = []
    for line in markdown.splitlines():
        match = re.search(r"->\s*见\s+([^\s]+)", line.strip())  # 匹配 "-> 见 路径" 格式
        if not match:
            continue
        relative = match.group(1).strip()
        if not relative.startswith(prefix):  # 过滤指定前缀的路径
            continue
        if relative not in found:
            found.append(relative)
    return found


def _expand_memory_index_markdown(
    user_id: str,
    index_markdown: str,
    *,
    prefix: str,
    max_files: int,
    max_chars_per_file: int,
    section_title: str,
) -> str:
    """展开内存索引 Markdown，加载引用的文件内容。"""
    if not index_markdown.strip():
        return ""
    parts = [index_markdown.strip()]
    expanded: list[tuple[str, str]] = []
    for relative in _index_relative_paths(index_markdown, prefix=prefix)[:max_files]:
        content = read_user_doc(user_id, f"memory/{relative}")  # 读取内存文件
        if not content.strip():
            continue
        expanded.append((relative, content.strip()[:max_chars_per_file].rstrip()))  # 限制文件大小
    if not expanded:
        return "\n".join(parts).strip()
    parts.extend(["", f"## {section_title}", ""])
    for relative, content in expanded:
        parts.append(f"### {relative}")
        parts.append("")
        parts.append(content)
        parts.append("")
    return "\n".join(parts).strip()


def _assistant_prompt_preview(message: V4ConversationMessage) -> str:
    """生成助手消息的预览文本，用于提示构建。"""
    content = (message.content or "").strip()
    if content and content not in GENERIC_ASSISTANT_CONTENTS and content != "执行中":
        return _trim_prompt_text(content, 240)

    meta = _loads(message.meta_json, {})
    step_outcomes = meta.get("stepOutcomes") or []
    fragments: list[str] = []
    for step in step_outcomes[:2]:  # 最多取前2个步骤结果
        title = (step.get("title") or step.get("summary") or "步骤").strip()
        html_text = _strip_html(step.get("html") or "")
        excerpt = _trim_prompt_text(html_text, 220) if html_text else ""
        if excerpt:
            fragments.append(f"{title}: {excerpt}")
        elif title:
            fragments.append(title)
    if fragments:
        return _trim_prompt_text(" | ".join(fragments), 320)

    html_preview = _trim_prompt_text(_strip_html(message.content_html or ""), 260)
    if html_preview:
        return html_preview
    if content:
        return _trim_prompt_text(content, 160)
    return "助手已回复。"


def _message_prompt_content(message: V4ConversationMessage) -> str:
    """生成消息的提示内容。"""
    if message.role == "assistant":
        return _assistant_prompt_preview(message)
    return _trim_prompt_text(message.content or "", 240)


def _default_memory_state() -> dict:
    """获取默认的内存状态。"""
    return {
        "skillUsage": {},  # 技能使用统计
        "stylePreferences": [],  # 风格偏好
        "recentFocus": [],  # 最近关注
        "commonFeedback": [],  # 常见反馈
        "manualNotes": "",  # 手工备注
    }


def _normalize_memory_state(value) -> dict:
    """标准化内存状态数据。"""
    normalized = _default_memory_state()
    if not isinstance(value, dict):
        return normalized
    for key, item in value.items():
        if key not in normalized:
            normalized[key] = item

    # 处理技能使用统计
    skill_usage = {}
    for key, item in (value.get("skillUsage") or {}).items():
        try:
            score = int(item)
        except (TypeError, ValueError):
            continue
        if score > 0:
            skill_usage[str(key)] = score
    normalized["skillUsage"] = skill_usage

    # 处理风格偏好
    style_preferences: list[str] = []
    for item in value.get("stylePreferences") or []:
        text = str(item).strip()
        if text and text not in style_preferences:
            style_preferences.append(text)
    normalized["stylePreferences"] = style_preferences[-5:]  # 保留最近5个

    # 处理最近关注
    recent_focus: list[dict] = []
    for item in value.get("recentFocus") or []:
        if not isinstance(item, dict):
            continue
        conversation_id = str(item.get("conversationId") or "").strip()
        title = str(item.get("title") or "").strip()
        skill = str(item.get("skill") or "").strip()
        updated_at = str(item.get("updatedAt") or "").strip()
        if not conversation_id and not title:
            continue
        recent_focus.append(
            {
                "conversationId": conversation_id,
                "title": title,
                "skill": skill,
                "updatedAt": updated_at,
            }
        )
    normalized["recentFocus"] = recent_focus[:8]  # 保留最近8个

    # 处理常见反馈
    common_feedback: list[str] = []
    for item in value.get("commonFeedback") or []:
        text = str(item).strip()
        if text and text not in common_feedback:
            common_feedback.append(text)
    normalized["commonFeedback"] = common_feedback[:20]  # 保留最近20个

    normalized["manualNotes"] = str(value.get("manualNotes") or "").strip()
    return normalized


def _extract_manual_notes_from_memory_markdown(markdown: str | None) -> str:
    """从内存 Markdown 中提取手工备注。"""
    if not markdown:
        return ""
    if MEMORY_MANUAL_HEADING in markdown:
        return markdown.split(MEMORY_MANUAL_HEADING, 1)[1].strip()

    cleaned: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "# memory":
            continue
        if stripped.startswith("- 这是用户长期记忆入口文件"):
            continue
        if stripped.startswith("- 暂无。可在设置页补充个人注记或入口说明。"):
            continue
        if stripped.startswith(("- 推荐摘要:", "- 技能使用统计:", "- 风格偏好:")):
            continue
        if "-> 见 topics/" in stripped or "-> 见 sessions/" in stripped:
            continue
        if stripped.startswith("## ") and "手工备注" not in stripped:
            continue
        cleaned.append(line.rstrip())
    return "\n".join(cleaned).strip()


def _trim_memory_line(value: str, limit: int = 140) -> str:
    """裁剪内存行长度。"""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _format_time(value: str | None) -> str:
    """格式化时间字符串。"""
    if not value:
        return "未知"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")  # 转换为标准格式
    except ValueError:
        return value


def _render_memory_index(manual_notes: str) -> str:
    """渲染内存索引 Markdown。"""
    lines = [
        "# memory",
        "",
        "- 这是用户长期记忆入口文件，具体内容见下列主题文件。",
        "",
        "## 用户习惯",
        "- 工作习惯与处理路径 -> 见 topics/habits.md",
        "",
        "## 常用技能与工作偏好",
        "- 常用技能统计与入口偏好 -> 见 topics/skill_preferences.md",
        "",
        "## 写作与模型风格",
        "- 默认模型与近期模型偏好 -> 见 topics/style_preferences.md",
        "",
        "## 近期高频主题",
        "- 最近会话主题与跟进方向 -> 见 topics/recent_focus.md",
        "",
        "## 常见反馈",
        "- 手工补充的注意事项与常见反馈 -> 见 topics/common_feedback.md",
        "",
        MEMORY_MANUAL_HEADING,
    ]
    if manual_notes:
        lines.extend(["", manual_notes])
    else:
        lines.extend(["", "- 暂无。可在设置页补充个人注记或入口说明。"])
    return "\n".join(lines).strip() + "\n"


def _render_topic_markdown(title: str, lines: list[str]) -> str:
    """渲染主题 Markdown。"""
    content = [f"# {title}", ""]
    if lines:
        content.extend(lines)
    else:
        content.append("- 暂无记录。")
    return "\n".join(content).strip() + "\n"


def _build_memory_topics(profile: V4UserProfile, memory: dict, preferred_skills: list[str]) -> dict[str, str]:
    """构建内存主题文件内容。"""
    skill_usage = memory.get("skillUsage") or {}
    ordered_skills = sorted(skill_usage.items(), key=lambda item: (-item[1], item[0]))  # 按使用次数降序排序
    top_skills = [name for name, _ in ordered_skills[:3]]  # 取前3个高频技能
    recent_focus = memory.get("recentFocus") or []
    latest_focus = recent_focus[0] if recent_focus else {}
    latest_title = latest_focus.get("title") or "暂无"

    # 构建习惯主题
    habits_lines = []
    if top_skills:
        habits_lines.append(f"- 高频技能：{'、'.join(top_skills)}")
    if profile.recommendation_summary:
        habits_lines.append(f"- 当前推荐方向：{_trim_memory_line(profile.recommendation_summary)}")
    habits_lines.append(f"- 最近会话关注：{_trim_memory_line(latest_title)}")

    # 构建技能偏好主题
    skill_lines = []
    if preferred_skills:
        skill_lines.append(f"- 常用技能入口：{'、'.join(preferred_skills)}")
    for name, score in ordered_skills[:8]:  # 取前8个技能
        skill_lines.append(f"- {name}：{score} 次")

    # 构建风格偏好主题
    style_lines = [
        f"- 默认模型：{profile.default_model or '未设置'}",
    ]
    style_preferences = memory.get("stylePreferences") or []
    if style_preferences:
        style_lines.append(f"- 近期模型偏好：{'、'.join(style_preferences)}")

    # 构建最近关注主题
    focus_lines = []
    for item in recent_focus[:8]:  # 取前8个最近关注
        title = item.get("title") or item.get("conversationId") or "未命名会话"
        skill = item.get("skill") or "unknown"
        updated_at = _format_time(item.get("updatedAt"))
        focus_lines.append(f"- {_trim_memory_line(title, 80)}｜技能：{skill}｜更新：{updated_at}")

    # 构建常见反馈主题
    feedback_lines = []
    for item in memory.get("commonFeedback") or []:
        feedback_lines.append(f"- {_trim_memory_line(str(item), 120)}")
    manual_notes = memory.get("manualNotes") or ""
    if manual_notes:
        for line in manual_notes.splitlines():
            text = line.strip()
            if text:
                feedback_lines.append(f"- {_trim_memory_line(text, 120)}")
    if not feedback_lines:
        feedback_lines.append("- 暂无反馈记录。")

    return {
        "topics/habits.md": _render_topic_markdown("habits", habits_lines),
        "topics/skill_preferences.md": _render_topic_markdown("skill_preferences", skill_lines),
        "topics/style_preferences.md": _render_topic_markdown("style_preferences", style_lines),
        "topics/recent_focus.md": _render_topic_markdown("recent_focus", focus_lines),
        "topics/common_feedback.md": _render_topic_markdown("common_feedback", feedback_lines),
    }


def _render_identify_markdown(profile: V4UserProfile, current_user, preferred_skills: list[str], recent_title: str | None) -> str:
    """渲染身份标识 Markdown。"""
    identity = _loads(profile.identity_json, {})
    lines = [
        "# identify",
        "",
        f"- 用户姓名: {identity.get('name') or current_user.name}",
        f"- 账号: {identity.get('account') or current_user.account}",
        f"- 单位: {identity.get('orgName') or current_user.org_name or '未知'}",
        f"- 默认模型: {profile.default_model or current_user.default_model or '未设置'}",
        f"- 常用技能: {', '.join(preferred_skills) or '待学习'}",
    ]
    if recent_title:
        lines.append(f"- 最近会话: {recent_title}")
    return "\n".join(lines).strip() + "\n"


def _sync_profile_memory_projection(
    db: Session,
    current_user,
    profile: V4UserProfile,
    *,
    conversation: V4Conversation | None = None,
) -> V4UserProfile:
    """同步用户配置文件的内存投影。"""
    preferred_skills = _loads(profile.preferred_skills_json, [])
    memory = _normalize_memory_state(_loads(profile.memory_json, {}))
    existing_memory_md = read_user_doc(current_user.user_id, profile.memory_md_path)
    if not memory.get("manualNotes"):
        memory["manualNotes"] = _extract_manual_notes_from_memory_markdown(existing_memory_md)
    profile.memory_json = _json(memory)

    recent_title = None
    if conversation is not None:
        recent_title = conversation.title
    elif memory.get("recentFocus"):
        recent_title = memory["recentFocus"][0].get("title")

    # 写入身份标识文件
    profile.identify_md_path = write_memory_doc(
        current_user.user_id,
        "identify.md",
        _render_identify_markdown(profile, current_user, preferred_skills, recent_title),
    )
    # 写入内存主题文件
    for relative_path, content in _build_memory_topics(profile, memory, preferred_skills).items():
        write_memory_doc(current_user.user_id, relative_path, content)
    # 写入内存索引文件
    profile.memory_md_path = write_memory_doc(
        current_user.user_id,
        "memory.md",
        _render_memory_index(memory.get("manualNotes") or ""),
    )
    # 初始化会话摘要文件
    if not profile.last_session_summary_md_path:
        profile.last_session_summary_md_path = write_memory_doc(
            current_user.user_id,
            "session_summary.md",
            "# session_summary\n\n- 暂无会话摘要。\n",
        )
    db.flush()
    return profile


def _render_session_detail_markdown(conversation: V4Conversation, summary: str, pending_question: str | None) -> str:
    """渲染会话详情 Markdown。"""
    lines = [
        "# session",
        "",
        "## 会话信息",
        f"- 标题: {conversation.title}",
        f"- 会话ID: {conversation.id}",
        f"- 更新时间: {_format_time(conversation.updated_at.isoformat())}",
        "",
        "## 关键摘要",
        summary or "暂无摘要。",
        "",
        "## 待续事项",
    ]
    if pending_question:
        lines.append(f"- {_trim_memory_line(pending_question, 120)}")
    else:
        lines.append("- 暂无。")
    return "\n".join(lines).strip() + "\n"


def _sync_session_summary_projection(db: Session, current_user, profile: V4UserProfile) -> V4UserProfile:
    """同步会话摘要投影。"""
    # 获取最近的压缩快照
    snapshots = db.execute(
        select(V4CompressionSnapshot)
        .where(V4CompressionSnapshot.user_id == current_user.user_id)
        .order_by(V4CompressionSnapshot.created_at.desc())
    ).scalars().all()

    # 按会话ID分组，取最新的快照
    latest_by_conversation: dict[str, V4CompressionSnapshot] = {}
    for snapshot in snapshots:
        latest_by_conversation.setdefault(snapshot.conversation_id, snapshot)

    if not latest_by_conversation:
        # 无快照时创建默认会话摘要文件
        profile.last_session_summary_md_path = write_memory_doc(
            current_user.user_id,
            "session_summary.md",
            "# session_summary\n\n- 暂无会话摘要。\n",
        )
        db.flush()
        return profile

    # 获取相关会话
    conversation_ids = list(latest_by_conversation.keys())
    conversations = db.execute(
        select(V4Conversation).where(V4Conversation.id.in_(conversation_ids))
    ).scalars().all()
    conversation_map = {item.id: item for item in conversations}

    # 构建会话摘要索引
    index_lines = [
        "# session_summary",
        "",
        "- 这是近期会话摘要入口文件，按更新时间倒序查看。",
        "",
    ]
    for conversation_id, snapshot in list(latest_by_conversation.items())[:8]:  # 取前8个会话
        conversation = conversation_map.get(conversation_id)
        if conversation is None:
            continue
        runtime_state = _read_runtime_state(conversation)
        pending_prompt = runtime_state.get("pendingPromptMenu") or {}
        pending_question = pending_prompt.get("question") or pending_prompt.get("description")
        # 写入会话详情文件
        write_memory_doc(
            current_user.user_id,
            f"sessions/{conversation_id}.md",
            _render_session_detail_markdown(conversation, snapshot.summary_markdown, pending_question),
        )
        index_lines.append(
            f"- {clip_title(conversation.title)}（{snapshot.created_at.strftime('%m-%d %H:%M')}） -> 见 sessions/{conversation_id}.md"
        )
    if len(index_lines) == 4:
        index_lines.append("- 暂无会话摘要。")
    # 写入会话摘要索引文件
    profile.last_session_summary_md_path = write_memory_doc(
        current_user.user_id,
        "session_summary.md",
        "\n".join(index_lines).strip() + "\n",
    )
    db.flush()
    return profile


def _get_or_create_profile(db: Session, current_user) -> V4UserProfile:
    """获取或创建用户配置文件。"""
    profile = db.execute(
        select(V4UserProfile).where(V4UserProfile.user_id == current_user.user_id)
    ).scalar_one_or_none()
    if profile is None:
        # 创建新的用户配置文件
        profile = V4UserProfile(
            user_id=current_user.user_id,
            default_model=current_user.default_model,
            preferred_skills_json=_json([]),
            identity_json=_json(
                {
                    "name": current_user.name,
                    "account": current_user.account,
                    "orgName": current_user.org_name,
                    "orgCode": current_user.org_code,
                }
            ),
            memory_json=_json(_default_memory_state()),
        )
        db.add(profile)
        db.flush()
    return profile


def _ensure_memory_docs(db: Session, current_user) -> V4UserProfile:
    """确保内存文档存在。"""
    profile = _get_or_create_profile(db, current_user)
    _sync_profile_memory_projection(db, current_user, profile)
    _sync_session_summary_projection(db, current_user, profile)
    return profile


def build_runtime_context(db: Session, conversation: V4Conversation) -> dict:
    messages = db.execute(
        select(V4ConversationMessage)
        .where(V4ConversationMessage.conversation_id == conversation.id)
        .order_by(V4ConversationMessage.created_at.asc())
    ).scalars().all()
    simplified = [
        {
            "id": message.id,
            "role": message.role,
            "content": _message_prompt_content(message),
            "skill_name": message.skill_name,
            "meta": _loads(message.meta_json, {}),
        }
        for message in messages
    ]
    recent = simplified[-settings.compaction_preserve_recent_messages :]
    summary = conversation.running_context_summary or ""
    return {
        "summary": summary,
        "recent_messages": recent,
        "message_count": len(simplified),
    }


def maybe_compact_conversation(db: Session, conversation: V4Conversation, current_user) -> None:
    messages = db.execute(
        select(V4ConversationMessage)
        .where(V4ConversationMessage.conversation_id == conversation.id)
        .order_by(V4ConversationMessage.created_at.asc())
    ).scalars().all()
    simplified = [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "meta": _loads(message.meta_json, {}),
        }
        for message in messages
    ]
    if len(simplified) <= settings.compaction_preserve_recent_messages:
        log_stage(
            "runtime.compaction.skip",
            {
                "conversationId": conversation.id,
                "reason": "message_count_not_enough",
                "messageCount": len(simplified),
                "preserveRecentMessages": settings.compaction_preserve_recent_messages,
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return

    total_chars = sum(len(item["content"]) for item in simplified)
    if total_chars < settings.compaction_max_chars:
        log_stage(
            "runtime.compaction.skip",
            {
                "conversationId": conversation.id,
                "reason": "total_chars_below_threshold",
                "totalChars": total_chars,
                "threshold": settings.compaction_max_chars,
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        return

    older = simplified[: -settings.compaction_preserve_recent_messages]
    recent = simplified[-settings.compaction_preserve_recent_messages :]
    tool_names = []
    key_files = []
    for item in older + recent:
        meta = item.get("meta") or {}
        tool_names.extend(meta.get("tools", []))
        key_files.extend(meta.get("keyFiles", []))

    summary = build_structured_summary(older, recent, tool_names, key_files)
    compressed, stats = compress_summary_text(
        summary,
        SummaryCompressionBudget(
            max_chars=settings.compaction_summary_max_chars,
            max_lines=settings.compaction_summary_max_lines,
            max_line_chars=settings.compaction_summary_max_line_chars,
        ),
    )
    snapshot = V4CompressionSnapshot(
        conversation_id=conversation.id,
        user_id=current_user.user_id,
        summary=compressed,
        summary_markdown=compressed,
        source_message_ids_json=_json([item["id"] for item in older]),
        stats_json=_json(stats),
    )
    conversation.running_context_summary = compressed
    conversation.running_context_json = _json(
        {
            "summary": compressed,
            "recentMessages": recent,
            "stats": stats,
        }
    )
    db.add(snapshot)
    db.flush()
    log_stage(
        "runtime.compaction.created",
        {
            "conversationId": conversation.id,
            "summary": compressed,
            "stats": stats,
            "sourceMessageIds": [item["id"] for item in older],
            "recentMessages": recent,
        },
        enabled=settings.debug_runtime_logs,
        max_chars=settings.debug_log_max_chars,
        max_string_chars=settings.debug_log_max_string_chars,
    )

    profile = _ensure_memory_docs(db, current_user)
    _sync_session_summary_projection(db, current_user, profile)


def _create_artifact_and_workspace_entry(
    db: Session,
    current_user,
    conversation: V4Conversation,
    run: V4ConversationRun,
    assistant_message: V4ConversationMessage,
    artifact: dict,
    annotations: list[dict],
) -> V4ConversationArtifact:
    node = V4WorkspaceNode(
        owner_user_id=current_user.user_id,
        owner_name=current_user.name,
        parent_id=None,
        node_type="document",
        source="conversation",
        name=artifact["title"],
        summary=artifact.get("summary"),
    )
    db.add(node)
    db.flush()

    version_path = write_workspace_version(
        current_user.user_id,
        node.id,
        1,
        artifact["title"],
        artifact.get("content_html"),
        artifact.get("summary"),
        annotations,
    )
    version = V4WorkspaceVersion(
        node_id=node.id,
        version_no=1,
        title=artifact["title"],
        content_text=artifact.get("summary"),
        content_html=artifact.get("content_html"),
        file_rel_path=version_path,
        annotations_json=_json(annotations),
    )
    node.relative_path = version_path
    db.add(version)
    db.add(
        V4WorkspaceAttachmentLink(
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            node_id=node.id,
            attachment_role="artifact",
        )
    )
    saved = V4ConversationArtifact(
        conversation_id=conversation.id,
        run_id=run.id,
        message_id=assistant_message.id,
        user_id=current_user.user_id,
        artifact_type=artifact["artifact_type"],
        title=artifact["title"],
        summary=artifact.get("summary"),
        content_html=artifact.get("content_html"),
        workspace_node_id=node.id,
        meta_json=_json({"relativePath": version_path}),
    )
    db.add(saved)
    db.flush()
    return saved


def _next_event_seq_no(db: Session, run_id: str) -> int:
    row = db.execute(
        select(func.coalesce(func.max(V4TaskEvent.seq_no), 0)).where(V4TaskEvent.run_id == run_id)
    ).scalar_one()
    return int(row or 0) + 1


def _save_events(
    db: Session,
    run: V4ConversationRun,
    current_user,
    runtime_events: list[RuntimeTaskEvent],
    *,
    start_seq_no: int = 1,
) -> list[V4TaskEvent]:
    """持久化事件；统一经瘦身白名单过滤再落库，避免 taskPacket / raw / registry 等重字段膨胀存储。

    完整数据仍保留在 V4ConversationRun.input_payload_json 与 V4ConversationMessage.meta_json，
    供调试与回放；这里只做“前端可见的流式事件”的精简。
    """
    saved = []
    slim_enabled = settings.slim_event_payload
    for seq_no, event in enumerate(runtime_events, start=start_seq_no):
        if slim_enabled:
            delta = slim_delta(event.type, event.delta) if event.delta else None
            block = slim_content_block(event.type, event.content_block) if event.content_block else None
            payload = slim_payload(event.type, event.payload) if event.payload else None
        else:
            delta = event.delta
            block = event.content_block
            payload = event.payload
        item = V4TaskEvent(
            run_id=run.id,
            conversation_id=run.conversation_id,
            user_id=current_user.user_id,
            task_id=run.task_id,
            parent_task_id=run.parent_task_id,
            seq_no=seq_no,
            event_type=event.type,
            event_index=event.index,
            delta_json=_json(delta) if delta else None,
            block_json=_json(block) if block else None,
            payload_json=_json(payload) if payload else None,
        )
        db.add(item)
        saved.append(item)
    db.flush()
    return saved


def _save_new_events(
    db: Session,
    run: V4ConversationRun,
    current_user,
    runtime_events: list[RuntimeTaskEvent],
    saved_count: int,
) -> tuple[list[V4TaskEvent], int]:
    pending = runtime_events[saved_count:]
    if not pending:
        return [], saved_count
    next_seq = _next_event_seq_no(db, run.id)
    saved = _save_events(
        db,
        run,
        current_user,
        pending,
        start_seq_no=next_seq,
    )
    db.commit()
    return saved, len(runtime_events)


def _touch_profile_after_run(
    db: Session,
    current_user,
    conversation: V4Conversation,
    skill_name: str,
    requested_model: str | None,
) -> V4UserProfile:
    profile = _ensure_memory_docs(db, current_user)
    preferred_skills = _loads(profile.preferred_skills_json, [])
    if skill_name not in preferred_skills:
        preferred_skills = [skill_name, *preferred_skills][:5]
    memory = _normalize_memory_state(_loads(profile.memory_json, {}))
    skill_usage = memory.setdefault("skillUsage", {})
    skill_usage[skill_name] = int(skill_usage.get(skill_name, 0)) + 1
    if requested_model:
        memory.setdefault("stylePreferences", [])
        if requested_model not in memory["stylePreferences"]:
            memory["stylePreferences"].append(requested_model)
            memory["stylePreferences"] = memory["stylePreferences"][-5:]
    recent_focus = [item for item in memory.get("recentFocus", []) if item.get("conversationId") != conversation.id]
    recent_focus.insert(
        0,
        {
            "conversationId": conversation.id,
            "title": conversation.title,
            "skill": skill_name,
            "updatedAt": datetime.utcnow().isoformat(),
        },
    )
    memory["recentFocus"] = recent_focus[:8]
    profile.default_model = requested_model or profile.default_model or current_user.default_model
    profile.preferred_skills_json = _json(preferred_skills)
    profile.memory_json = _json(memory)
    profile.recommendation_summary = (
        f"近期更常使用 {skill_name} 能力，建议继续围绕高频公文场景提供快捷入口。"
    )
    profile.updated_at = datetime.utcnow()
    _sync_profile_memory_projection(db, current_user, profile, conversation=conversation)
    return profile


def _plan_payload(plan) -> dict:
    from app.event_payload import (
        action_label_for_skill,
        display_text_for_step,
        done_label_for_skill,
    )

    steps_payload: list[dict] = []
    for step in plan.steps:
        skill = (step.skill_name or "").strip().lower()
        # displayTitle：前端"待办任务列表"卡片主文案（短语），
        # 例：「检索写作参考资料」「起草 五一放假通知」。
        base_title = (step.title or "").strip() or "待执行任务"
        objective = (step.objective or "").strip()
        # 优先展示和用户问题更贴近的 objective 片段，让计划卡片语义更直观。
        display_title = objective[:60] if objective else base_title
        running_label = display_text_for_step(step, phase="running")
        done_label = display_text_for_step(step, phase="done")
        steps_payload.append(
            {
                "index": step.index,
                "skillName": step.skill_name,
                "title": base_title,
                "objective": objective,
                "scope": step.scope,
                "dependsOn": step.depends_on,
                "subtaskRole": step.subtask_role,
                # 以下字段专供前端 TodoList / 步骤进度条回显使用：
                "displayTitle": display_title,
                "actionLabel": action_label_for_skill(skill),
                "pendingLabel": f"待{action_label_for_skill(skill)}",
                "runningLabel": running_label,
                "doneLabel": done_label_for_skill(skill),
                "status": "pending",
            }
        )

    return {
        "intent": plan.intent,
        "summary": plan.summary,
        "requiresUserInput": plan.requires_user_input,
        "clarificationQuestion": plan.clarification_question,
        "steps": steps_payload,
    }


def _step_payload(step: ExecutionStep) -> dict:
    from app.event_payload import (
        action_label_for_skill,
        display_text_for_step,
        done_label_for_skill,
    )

    skill = (step.skill_name or "").strip().lower()
    base_title = (step.title or "").strip() or "待执行任务"
    return {
        "index": step.index,
        "skillName": step.skill_name,
        "title": base_title,
        "objective": step.objective,
        "scope": step.scope,
        "dependsOn": step.depends_on,
        "subtaskRole": step.subtask_role,
        # 前端步骤卡片回显字段：
        "displayTitle": base_title,
        "actionLabel": action_label_for_skill(skill),
        "pendingLabel": f"待{action_label_for_skill(skill)}",
        "runningLabel": display_text_for_step(step, phase="running"),
        "doneLabel": done_label_for_skill(skill),
    }


def _plan_from_payload(plan_payload: dict) -> ExecutionPlan:
    steps = [
        ExecutionStep(
            index=item.get("index", index),
            skill_name=item.get("skillName") or "general",
            title=item.get("title") or title_for_skill(item.get("skillName") or "general"),
            objective=item.get("objective") or "完成当前子任务。",
            scope=item.get("scope") or "完成当前任务。",
            depends_on=item.get("dependsOn") or [],
            subtask_role=item.get("subtaskRole") or "skill_worker",
        )
        for index, item in enumerate(plan_payload.get("steps") or [], start=1)
    ]
    return ExecutionPlan(
        intent=plan_payload.get("intent") or "document_workflow",
        summary=plan_payload.get("summary") or "leader 执行计划",
        steps=steps,
        requires_user_input=bool(plan_payload.get("requiresUserInput")),
        clarification_question=plan_payload.get("clarificationQuestion"),
    )


def _collect_task_tree(task_ids: list[str]) -> list[dict]:
    snapshots: list[dict] = []
    for task_id in task_ids:
        snapshot = a2a_task_registry.get_snapshot(task_id)
        if snapshot:
            snapshots.append(snapshot)
    return snapshots


def _read_runtime_state(conversation: V4Conversation) -> dict:
    state = _loads(conversation.running_context_json, {})
    if not isinstance(state, dict):
        return {}
    return state


def _merge_runtime_state(conversation: V4Conversation, runtime_context: dict, updates: dict) -> dict:
    current = _read_runtime_state(conversation)
    merged = {
        "summary": runtime_context.get("summary") or current.get("summary") or "",
        "recentMessages": runtime_context.get("recent_messages") or current.get("recentMessages") or [],
        "messageCount": runtime_context.get("message_count") or current.get("messageCount") or 0,
    }
    merged.update({key: value for key, value in current.items() if key not in merged})
    merged.update(updates)
    conversation.running_context_json = _json(merged)
    return merged


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value or "").replace("&nbsp;", " ").strip()


def _collect_followup_texts(skill_result: SkillExecutionResult) -> list[str]:
    lines: list[str] = []
    for block in skill_result.render_blocks:
        plain = _strip_html(block.get("html") or "")
        for line in plain.splitlines():
            text = line.strip(" -*#\t")
            if text:
                lines.append(text)

    def walk(value):
        if isinstance(value, str):
            text = _strip_html(value)
            if text:
                lines.append(text)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(skill_result.normalized_result)
    deduped: list[str] = []
    seen = set()
    for line in lines:
        key = line[:200]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(line)
    return deduped


def _clarification_fallback(skill_name: str) -> str:
    mapping = {
        "retrieval": "当前还缺少更具体的检索范围，请补充资料方向、侧重点或项目名称后继续。",
        "writing": "当前还缺少更明确的写作要求，请补充文种、对象、重点或语气后继续。",
        "review": "当前还缺少审核范围，请补充需要重点检查的部分后继续。",
        "dedup": "当前还缺少查重范围，请补充目标文本或查重侧重点后继续。",
        "layout": "当前还缺少排版要求，请补充模板、格式或特殊约束后继续。",
    }
    return mapping.get(skill_name, "当前还缺少关键信息，请补充后继续。")


def _extract_followup_question(skill_result: SkillExecutionResult) -> str | None:
    markers = ("请补充", "请说明", "请确认", "请问", "可否", "是指什么", "需要哪方面", "请提供", "请告知")
    for line in _collect_followup_texts(skill_result):
        parts = re.split(r"[。！？?!]", line)
        candidates = [item.strip() for item in parts if item.strip()]
        for candidate in candidates:
            if candidate.endswith(("？", "?")) or any(marker in candidate for marker in markers):
                if len(candidate) <= 90 and not candidate.startswith(("您好", "我是")):
                    return candidate[:160]
        if line.endswith(("？", "?")) or any(marker in line for marker in markers):
            if len(line) <= 90 and not line.startswith(("您好", "我是")):
                return line[:160]
    return None


def _build_pending_context(runtime_context: dict, runtime_state: dict, user_message: str) -> dict:
    pending = runtime_state.get("pendingPromptMenu")
    if not pending:
        return runtime_context
    prompt_menu = pending.get("promptMenu") or {}
    enriched = dict(runtime_context)
    enriched["pending_task"] = {
        "skillName": pending.get("skillName"),
        "title": pending.get("title"),
        "resumeMode": pending.get("resumeMode"),
        "sourceState": pending.get("sourceState"),
    }
    enriched["pending_question"] = (
        prompt_menu.get("question")
        or prompt_menu.get("description")
        or prompt_menu.get("title")
        or pending.get("title")
    )
    enriched["user_answer_to_pending"] = (user_message or "").strip() or None
    return enriched


def _message_actions() -> dict:
    return {
        "canCopy": True,
        "canLike": True,
        "canDislike": True,
        "canRegenerate": True,
    }


def _build_prompt_menu(
    step: ExecutionStep,
    normalized_result: dict,
    annotations: list[dict],
    skill_result: SkillExecutionResult,
) -> dict:
    if step.skill_name == "review":
        return {
            "type": "review_actions",
            "title": "共审核出以下问题，接下来怎么处理？",
            "description": "可以全部修改、让我核对，或补充新的要求。",
            "options": [
                {"key": "accept_all", "label": "全部修改", "recommended": True},
                {"key": "manual_review", "label": "让我核对", "recommended": False},
                {"key": "custom_input", "label": "都不是，我来补充", "recommended": False},
            ],
            "annotations": annotations,
            "resultPreview": normalized_result,
        }
    if step.skill_name == "dedup":
        return {
            "type": "duplicate_actions",
            "title": "是否继续生成查重报告？",
            "description": "可以直接生成报告，也可以补充改写要求。",
            "options": [
                {"key": "generate_report", "label": "是", "recommended": True},
                {"key": "skip_report", "label": "否", "recommended": False},
                {"key": "custom_input", "label": "都不是，我来补充", "recommended": False},
            ],
            "annotations": annotations,
            "resultPreview": normalized_result,
        }
    if step.skill_name == "layout":
        templates = normalized_result.get("templates") or []
        return {
            "type": "format_actions",
            "title": "是否应用推荐模板，或手动选择模板？",
            "description": "可以直接套用推荐模板，也可以手动选择或补充特殊要求。",
            "options": [
                {"key": "apply_recommended", "label": "推荐模板", "recommended": True},
                {"key": "choose_template", "label": "手动选择模板", "recommended": False},
                {"key": "custom_input", "label": "都不是，我来补充", "recommended": False},
            ],
            "templates": templates,
            "resultPreview": normalized_result,
        }
    if skill_result.prompt_menu:
        return skill_result.prompt_menu

    # 阶段 4：显式触发 waiting_user
    # - retrieval 在 items 与 summary_text 均为空时：不再打断流程，直接继续后续步骤
    # - writing 在 document 明显过短（<40 字）时，邀请用户补充背景或重试
    if step.skill_name == "retrieval":
        items = normalized_result.get("items") or []
        summary_text = (normalized_result.get("summary_text") or "").strip()
        if not items and not summary_text:
            return {}
    if step.skill_name == "writing":
        document = (normalized_result.get("document") or "").strip()
        if document and len(document) < 40 and skill_result.source_state != "model_error":
            return {
                "type": "clarification",
                "title": "写作内容过于简短",
                "description": "模型可能未拿到足够信息。请补充文种、结构或素材，我会再试一次。",
                "question": "能否补充文种、受文对象、主要事项或已有素材？",
                "options": [
                    {"key": "custom_input", "label": "补充写作要求", "recommended": True},
                ],
                "resultPreview": normalized_result,
                "resumeMode": "rerun_current_step",
            }

    question = _extract_followup_question(skill_result)
    if question and (skill_result.retryable or step.skill_name in INTERACTIVE_SKILLS):
        return {
            "type": "clarification",
            "title": f"{title_for_skill(step.skill_name)}需要补充信息",
            "description": question,
            "question": question,
            "options": [
                {"key": "custom_input", "label": "补充信息", "recommended": True},
            ],
            "resultPreview": normalized_result,
            "resumeMode": "rerun_current_step",
        }
    return {}


def _resolve_prompt_menu_choice(
    menu_state: dict,
    selected_option: str | None,
    prompt_menu_input: str | None,
) -> tuple[dict, list[dict], list[dict], list[dict], dict | None]:
    skill_name = menu_state.get("skillName") or "general"
    title = menu_state.get("title") or title_for_skill(skill_name)
    normalized_result = menu_state.get("normalizedResult") or {}
    annotations = menu_state.get("annotations") or []
    selected = selected_option or ""
    custom_text = (prompt_menu_input or "").strip()
    prompt_menu = menu_state.get("promptMenu") or {}

    if prompt_menu.get("type") == "clarification":
        answer_text = custom_text or selected or "已补充信息。"
        question_text = prompt_menu.get("question") or prompt_menu.get("description") or title
        return (
            {
                "question": question_text,
                "user_clarification": answer_text,
                "mode": "clarification_reply",
            },
            [
                {
                    "type": "clarification",
                    "title": title,
                    "html": (
                        f"<p>已补充信息：{escape(answer_text)}</p>"
                        f"<p>针对问题：{escape(question_text)}</p>"
                    ),
                }
            ],
            [],
            annotations,
            None,
        )

    if skill_name == "review":
        if selected == "manual_review":
            return (
                {
                    "issues": normalized_result.get("issues") or [],
                    "mode": "manual_review",
                    "message": "已进入人工核对模式，可在编辑器中逐条核对问题。",
                },
                [
                    {
                        "type": "review",
                        "title": "人工核对模式",
                        "html": "<p>已切换到人工核对模式，请在右侧联动编辑器中逐条核对问题。</p>",
                    }
                ],
                [
                    {
                        "artifact_type": "document",
                        "title": "审核联动核对稿.docx",
                        "summary": "已生成带审核标注的联动核对稿。",
                        "content_html": "<p>已切换到人工核对模式，请在编辑器中处理审核问题。</p>",
                    }
                ],
                annotations,
                None,
            )
        revised_text = custom_text or "已根据审核意见自动修订正文，并生成修订稿。"
        return (
            {
                "issues": normalized_result.get("issues") or [],
                "mode": "apply_review",
                "message": revised_text,
            },
            [
                {
                    "type": "document",
                    "title": "审核修订结果",
                    "html": f"<p>{escape(revised_text)}</p>",
                }
            ],
            [
                {
                    "artifact_type": "document",
                    "title": "审核修订稿.docx",
                    "summary": "已根据审核意见生成修订稿。",
                    "content_html": f"<p>{escape(revised_text)}</p>",
                }
            ],
            [],
            None,
        )

    if skill_name == "dedup":
        if selected == "skip_report":
            return (
                {
                    "items": normalized_result.get("items") or [],
                    "mode": "skip_report",
                    "message": "已保留查重明细，不生成正式查重报告。",
                },
                [{"type": "duplicate", "title": "查重后续处理", "html": "<p>已保留查重明细，不生成正式报告。</p>"}],
                [],
                annotations,
                None,
            )
        report_text = custom_text or "已根据查重结果生成结构化查重报告。"
        return (
            {
                "items": normalized_result.get("items") or [],
                "mode": "generate_report",
                "message": report_text,
            },
            [{"type": "duplicate", "title": "查重报告", "html": f"<p>{escape(report_text)}</p>"}],
            [
                {
                    "artifact_type": "report",
                    "title": "查重报告.docx",
                    "summary": "已生成正式查重报告。",
                    "content_html": f"<p>{escape(report_text)}</p>",
                }
            ],
            annotations,
            None,
        )

    if skill_name == "layout":
        templates = normalized_result.get("templates") or []
        if selected == "choose_template" and not custom_text:
            template_options = [
                {
                    "key": f"template::{index}",
                    "label": item.get("templateTitle") or item.get("title") or f"模板 {index}",
                    "recommended": index == 1,
                }
                for index, item in enumerate(templates[:8], start=1)
            ]
            return (
                {},
                [],
                [],
                [],
                {
                    "type": "template_picker",
                    "title": "请选择一个排版模板",
                    "description": "可直接选择模板，或在输入框中补充模板要求。",
                    "options": template_options,
                },
            )
        template_name = custom_text or "党政机关标准版"
        if selected.startswith("template::"):
            try:
                template_index = int(selected.split("::", 1)[1]) - 1
                template = templates[template_index]
                template_name = template.get("templateTitle") or template.get("title") or template_name
            except (IndexError, ValueError):
                template_name = template_name
        return (
            {
                "templates": templates,
                "mode": "apply_template",
                "templateName": template_name,
            },
            [{"type": "format", "title": "排版结果", "html": f"<p>已应用模板：{escape(template_name)}</p>"}],
            [
                {
                    "artifact_type": "document",
                    "title": "排版完成稿.docx",
                    "summary": f"已应用模板：{template_name}",
                    "content_html": f"<p>已应用模板：{escape(template_name)}</p>",
                }
            ],
            [],
            None,
        )

    return (
        {
            "message": custom_text or f"已处理 {title} 的后续操作。",
        },
        [{"type": "general", "title": title, "html": f"<p>{escape(custom_text or f'已处理 {title} 的后续操作。')}</p>"}],
        [],
        annotations,
        None,
    )


def _build_final_assistant_output(
    requested_model: str | None,
    plan,
    step_outcomes: list[dict],
) -> tuple[str, str]:
    if not step_outcomes:
        return "任务未执行", "<p>当前未生成有效结果。</p>"

    if len(step_outcomes) == 1:
        outcome = step_outcomes[0]
        return outcome["summary"], outcome["html"]

    completed_titles = [item["title"] for item in step_outcomes]
    summary = "已完成" + "、".join(completed_titles)
    sections = [
        (
            "<div class='assistant-copy'>模型 "
            f"<strong>{escape(requested_model or '')}</strong> 已按 A2A 执行计划完成 "
            f"{len(step_outcomes)} 个子任务。</div>"
        ),
        f"<section class='assistant-block'><h4>Leader Plan</h4><p>{escape(plan.summary)}</p></section>",
    ]
    for outcome in step_outcomes:
        sections.append(
            (
                "<section class='assistant-block'>"
                f"<h4>Step {outcome['index']} · {escape(outcome['title'])}</h4>"
                f"{outcome['html']}"
                "</section>"
            )
        )
    return summary, "".join(sections)


def _merge_annotations(step_outcomes: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for outcome in step_outcomes:
        merged.extend(outcome.get("annotations") or [])
    return merged


def _subtask_trace(step_outcomes: list[dict]) -> list[dict]:
    return [
        {
            "taskId": item["task_id"],
            "skillName": item["skill_name"],
            "title": item["title"],
            "summary": item["summary"],
            "retryable": item["retryable"],
            "normalizedResult": item["normalized_result"],
        }
        for item in step_outcomes
    ]


def _step_sid(step: ExecutionStep) -> str:
    return f"step_{step.index:02d}_{step.skill_name}"


def _extract_synthetic_text(skill_name: str, skill_result: SkillExecutionResult) -> str:
    """在未走流式通道（如 legacy JSON 成功）时，从 normalized_result / render_blocks 中提取一段可展示正文。

    仅用于补发合成的 content_block_start(text)/delta/stop 三连，让前端编辑器联动仍能拿到可渲染文本。
    """
    result = skill_result.normalized_result or {}
    if skill_name == "writing":
        document = result.get("document")
        if isinstance(document, str) and document.strip():
            return document
    if skill_name == "retrieval":
        items = result.get("items") or []
        lines: list[str] = []
        for item in items[:8] if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or item.get("name") or "资料").strip()
            description = (item.get("description") or item.get("summary") or item.get("content") or "").strip()
            if description:
                lines.append(f"- {title}: {description}")
            else:
                lines.append(f"- {title}")
        if lines:
            return "\n".join(lines)
    # 通用兜底：取第一个 render_block 的纯文本摘要
    for block in skill_result.render_blocks or []:
        plain = _strip_html(block.get("html") or "")
        if plain.strip():
            return plain.strip()
    text = result.get("text") if isinstance(result, dict) else None
    if isinstance(text, str) and text.strip():
        return text
    return ""


def _execution_step_waves(steps: list[ExecutionStep]) -> list[list[ExecutionStep]]:
    """按 depends_on 分层；同波次内无未满足依赖的步骤可并行执行（opt5）。"""
    if not steps:
        return []
    pending = sorted(steps, key=lambda s: s.index)
    by_sid = {_step_sid(s): s for s in pending}
    completed: set[str] = set()
    waves: list[list[ExecutionStep]] = []
    remaining = list(pending)
    while remaining:
        ready: list[ExecutionStep] = []
        for s in list(remaining):
            deps = s.depends_on or []
            blocked = False
            for d in deps:
                if d in by_sid and d not in completed:
                    blocked = True
                    break
            if not blocked:
                ready.append(s)
        if not ready:
            s = min(remaining, key=lambda x: x.index)
            ready = [s]
        ready.sort(key=lambda x: x.index)
        waves.append(ready)
        for s in ready:
            remaining.remove(s)
            completed.add(_step_sid(s))
    return waves


def _html_from_blocks(
    requested_model: str | None,
    summary: str,
    blocks: list[dict],
    *,
    lead_copy: str,
) -> str:
    sections = [f"<div class='assistant-copy'>{lead_copy}</div>"]
    for block in blocks:
        sections.append(
            "<section class='assistant-block'>"
            f"<h4>{escape(block.get('title') or summary)}</h4>"
            f"{block.get('html') or '<p></p>'}"
            "</section>"
        )
    if not blocks:
        sections.append(f"<section class='assistant-block'><h4>{escape(summary)}</h4><p>暂无内容。</p></section>")
    return "".join(sections)


def _make_planner_stream_batcher(
    push_event: Callable[[RuntimeTaskEvent], None],
) -> Callable[[dict[str, Any]], None]:
    """Batch planner SSE chunks into planner_reasoning_delta DB events for early UI updates."""
    last_flush_len = 0
    last_t = time.monotonic()
    batch_chars = 72
    flush_interval = 0.35
    thinking_started = False

    def _emit(display: str) -> None:
        nonlocal thinking_started
        if not thinking_started:
            thinking_started = True
            push_event(RuntimeTaskEvent(
                type="content_block_start",
                index=0,
                content_block={"type": "thinking"},
            ))
        push_event(RuntimeTaskEvent(
            type="content_block_delta",
            index=0,
            delta={"type": "thinking_delta", "thinking": display[-12000:]},
        ))

    def on_planner(ev: dict[str, Any]) -> None:
        nonlocal last_flush_len, last_t
        if ev.get("flush"):
            reasoning = (ev.get("reasoning") or "").strip()
            text = (ev.get("text") or "").strip()
            display = reasoning or text
            if len(display) > last_flush_len or display:
                _emit(display)
                last_flush_len = len(display)
                last_t = time.monotonic()
            return
        reasoning = ev.get("reasoning") or ""
        text = ev.get("text") or ""
        display = reasoning.strip() and reasoning or text
        if not display:
            return
        now = time.monotonic()
        n = len(display)
        if n - last_flush_len >= batch_chars or (now - last_t) >= flush_interval:
            _emit(display)
            last_flush_len = n
            last_t = now

    return on_planner


def prepare_run_conversation(
    db: Session,
    conversation: V4Conversation,
    current_user,
    content: str,
    requested_skill: str | None,
    requested_model: str | None,
    attachments: list[dict],
    cookies: str | None,
    resume_from_waiting: bool = False,
    selected_option: str | None = None,
    prompt_menu_input: str | None = None,
) -> dict:
    requested_model = requested_model or current_user.default_model
    runtime_state = _read_runtime_state(conversation)
    pending_prompt_menu = runtime_state.get("pendingPromptMenu")
    auto_resume_waiting = (
        bool(pending_prompt_menu)
        and not resume_from_waiting
        and not selected_option
        and not (prompt_menu_input or "").strip()
        and (pending_prompt_menu.get("resumeMode") == "rerun_current_step")
        and bool((content or "").strip())
    )
    if auto_resume_waiting:
        resume_from_waiting = True
        selected_option = "custom_input"
        prompt_menu_input = content

    if resume_from_waiting and not pending_prompt_menu:
        raise ValueError("当前会话没有等待中的任务")
    if resume_from_waiting and not (selected_option or (prompt_menu_input or "").strip()):
        raise ValueError("请先选择一个后续操作，或输入补充要求")

    task_id = task_registry.next_task_id(conversation.id)
    run = V4ConversationRun(
        conversation_id=conversation.id,
        user_id=current_user.user_id,
        task_id=task_id,
        objective=content,
        requested_skill=requested_skill or (pending_prompt_menu or {}).get("skillName"),
        status="queued",
        model_name=requested_model,
        input_payload_json=_json(
            {
                "content": content,
                "requestedSkill": requested_skill,
                "requestedModel": requested_model,
                "attachments": attachments,
                "resumeFromWaiting": resume_from_waiting,
                "selectedOption": selected_option,
                "promptMenuInput": prompt_menu_input,
                "cookiePreview": mask_cookie(cookies),
            }
        ),
        context_snapshot_json=_json(runtime_state),
    )
    db.add(run)
    conversation.last_run_id = run.id
    conversation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    # 尽早落库一条 created，使前端在规划完成前即可拉 SSE 看到反馈（opt3）
    _save_events(
        db,
        run,
        current_user,
        [
            RuntimeTaskEvent(
                type="message_start",
                payload={
                    "phase": "prepared",
                    "runId": run.id,
                    "taskId": task_id,
                    "requestedSkill": requested_skill,
                },
            )
        ],
        start_seq_no=1,
    )
    db.commit()
    return {
        "run": run,
        "request": {
            "content": content,
            "requestedSkill": requested_skill,
            "requestedModel": requested_model,
            "attachments": attachments,
            "resumeFromWaiting": resume_from_waiting,
            "selectedOption": selected_option,
            "promptMenuInput": prompt_menu_input,
        },
    }


def run_conversation(
    db: Session,
    conversation: V4Conversation,
    current_user,
    content: str,
    requested_skill: str | None,
    requested_model: str | None,
    attachments: list[dict],
    cookies: str | None,
    resume_from_waiting: bool = False,
    selected_option: str | None = None,
    prompt_menu_input: str | None = None,
    prepared_run_id: str | None = None,
    prepared_task_id: str | None = None,
) -> dict:
    requested_model = requested_model or current_user.default_model
    runtime_state = _read_runtime_state(conversation)
    pending_prompt_menu = runtime_state.get("pendingPromptMenu")
    auto_resume_waiting = (
        bool(pending_prompt_menu)
        and not resume_from_waiting
        and not selected_option
        and not (prompt_menu_input or "").strip()
        and (pending_prompt_menu.get("resumeMode") == "rerun_current_step")
        and bool((content or "").strip())
    )
    if auto_resume_waiting:
        resume_from_waiting = True
        selected_option = "custom_input"
        prompt_menu_input = content

    if resume_from_waiting and not pending_prompt_menu:
        raise ValueError("当前会话没有等待中的任务")
    if resume_from_waiting and not (selected_option or (prompt_menu_input or "").strip()):
        raise ValueError("请先选择一个后续操作，或输入补充要求")

    log_stage(
        "runtime.run.start",
        {
            "conversationId": conversation.id,
            "conversationTitle": conversation.title,
            "user": {
                "userId": current_user.user_id,
                "name": current_user.name,
                "account": current_user.account,
                "orgName": current_user.org_name,
            },
            "request": {
                "content": content,
                "requestedSkill": requested_skill,
                "resolvedSkill": requested_skill or "pending_model_planner",
                "requestedModel": requested_model,
                "attachments": attachments,
                "cookiePreview": mask_cookie(cookies),
                "resumeFromWaiting": resume_from_waiting,
                "selectedOption": selected_option,
                "promptMenuInput": prompt_menu_input,
            },
        },
        enabled=settings.debug_runtime_logs,
        max_chars=settings.debug_log_max_chars,
        max_string_chars=settings.debug_log_max_string_chars,
    )

    profile = _ensure_memory_docs(db, current_user)
    memory_context = build_prompt_profile_docs(current_user, profile)
    runtime_context = build_runtime_context(db, conversation)
    runtime_context = _build_pending_context(runtime_context, runtime_state, content)

    if resume_from_waiting:
        resume_mode = pending_prompt_menu.get("resumeMode") or "prompt_menu_choice"
        plan_steps_payload = pending_prompt_menu.get("remainingSteps") or []
        if resume_mode == "rerun_current_step" and pending_prompt_menu.get("resumeCurrentStep"):
            plan_steps_payload = [pending_prompt_menu["resumeCurrentStep"], *plan_steps_payload]
        plan = ExecutionPlan(
            intent=(pending_prompt_menu.get("plan") or {}).get("intent") or "document_workflow",
            summary=f"恢复执行：{pending_prompt_menu.get('title') or '待处理任务'}",
            steps=[
                ExecutionStep(
                    index=item.get("index", index),
                    skill_name=item.get("skillName") or "general",
                    title=item.get("title") or title_for_skill(item.get("skillName") or "general"),
                    objective=item.get("objective") or "完成当前子任务。",
                    scope=item.get("scope") or "完成当前任务。",
                    depends_on=item.get("dependsOn") or [],
                    subtask_role=item.get("subtaskRole") or "skill_worker",
                )
                for index, item in enumerate(plan_steps_payload, start=1)
            ],
        )
        planner_meta = {
            "planner": "resume_from_waiting",
            "fallback": False,
            "resumeToken": pending_prompt_menu.get("resumeToken"),
            "sourceSkill": pending_prompt_menu.get("skillName"),
            "resumeMode": resume_mode,
        }
        primary_skill = (
            (pending_prompt_menu.get("resumeCurrentStep") or {}).get("skillName")
            or pending_prompt_menu.get("skillName")
            or requested_skill
            or "general"
        )
        content = (prompt_menu_input or selected_option or content or "").strip() or "继续执行"
        planning_pre_events = None
        planning_saved_count = 0
        planning_run: V4ConversationRun | None = None
    else:
        planning_pre_events = None
        planning_saved_count = 0
        planning_run = None
        if prepared_run_id:
            planning_run = db.execute(
                select(V4ConversationRun).where(
                    V4ConversationRun.id == prepared_run_id,
                    V4ConversationRun.conversation_id == conversation.id,
                    V4ConversationRun.user_id == current_user.user_id,
                )
            ).scalar_one()
            pre_events: list[RuntimeTaskEvent] = []
            saved_pre = 0

            def push_planning_event(event: RuntimeTaskEvent) -> None:
                nonlocal saved_pre
                pre_events.append(event)
                _, saved_pre = _save_new_events(db, planning_run, current_user, pre_events, saved_pre)

            on_planner = _make_planner_stream_batcher(push_planning_event)
            plan, planner_meta = build_model_execution_plan(
                content,
                requested_skill,
                attachments,
                requested_model,
                runtime_context=runtime_context,
                memory_context=memory_context,
                on_planner_stream=on_planner,
            )
            primary_skill = plan.primary_skill
            planning_pre_events = pre_events
            planning_saved_count = saved_pre
        else:
            plan, planner_meta = build_model_execution_plan(
                content,
                requested_skill,
                attachments,
                requested_model,
                runtime_context=runtime_context,
                memory_context=memory_context,
            )
            primary_skill = plan.primary_skill

    log_stage(
        "runtime.memory.refs",
        {
            "conversationId": conversation.id,
            "identifyMdPath": profile.identify_md_path,
            "memoryMdPath": profile.memory_md_path,
            "sessionSummaryMdPath": profile.last_session_summary_md_path,
            "recommendationSummary": profile.recommendation_summary,
            "memoryContext": memory_context,
        },
        enabled=settings.debug_runtime_logs,
        max_chars=settings.debug_log_max_chars,
        max_string_chars=settings.debug_log_max_string_chars,
    )
    log_stage(
        "runtime.context.built",
        {
            "conversationId": conversation.id,
            "runtimeContext": runtime_context,
            "runningContextJson": runtime_state,
            "plannerMeta": planner_meta,
            "leaderPlan": _plan_payload(plan),
        },
        enabled=settings.debug_runtime_logs,
        max_chars=settings.debug_log_max_chars,
        max_string_chars=settings.debug_log_max_string_chars,
    )

    task_id = task_registry.next_task_id(conversation.id)
    user_memory_refs = [
        value
        for value in [
            profile.identify_md_path,
            profile.memory_md_path,
            profile.last_session_summary_md_path,
        ]
        if value
    ]
    packet = build_root_task_packet(
        task_id=task_id,
        conversation_id=conversation.id,
        objective=content if not resume_from_waiting else f"恢复执行：{content}",
        requested_model=requested_model,
        plan=plan,
        attachments=attachments,
        runtime_context_summary=runtime_context["summary"],
        user_memory_refs=user_memory_refs,
    )
    if resume_from_waiting:
        packet.resume_token = pending_prompt_menu.get("resumeToken")
        packet.prompt_menu_contract = pending_prompt_menu.get("promptMenu") or {}

    root_task = a2a_task_registry.register(
        packet,
        "Leader Agent Root Task",
        team_id="leader-agent",
    )
    a2a_task_registry.append_message(task_id, "user", content)
    log_stage(
        "runtime.task_packet",
        {
            "conversationId": conversation.id,
            "taskPacket": packet,
            "leaderPlan": _plan_payload(plan),
            "plannerMeta": planner_meta,
            "rootTask": root_task.snapshot(),
        },
        enabled=settings.debug_runtime_logs,
        max_chars=settings.debug_log_max_chars,
        max_string_chars=settings.debug_log_max_string_chars,
    )

    user_message = V4ConversationMessage(
        conversation_id=conversation.id,
        user_id=current_user.user_id,
        role="user",
        skill_name=primary_skill,
        model_name=requested_model,
        content=content,
        content_html=f"<p>{escape(content)}</p>",
        meta_json=safe_text_column_json(
            {
                "attachments": attachments,
                "tools": ["lead_agent"],
                "leaderPlan": _plan_payload(plan),
                "plannerMeta": slim_planner_meta_for_db(planner_meta),
                "resumeFromWaiting": resume_from_waiting,
                "selectedOption": selected_option,
            }
        ),
    )
    db.add(user_message)
    db.flush()

    if planning_run is not None:
        run = planning_run
        run.task_id = prepared_task_id or run.task_id or task_id
        run.objective = content
        run.requested_skill = primary_skill
        run.status = "running"
        run.model_name = requested_model
        run.input_payload_json = safe_text_column_json(
            {
                "taskPacket": packet.model_dump(),
                "leaderPlan": _plan_payload(plan),
                "plannerMeta": slim_planner_meta_for_db(planner_meta),
                "pendingPromptMenu": pending_prompt_menu if resume_from_waiting else None,
            }
        )
        run.context_snapshot_json = _json(runtime_context)
        run.updated_at = datetime.utcnow()
    elif prepared_run_id:
        run = db.execute(
            select(V4ConversationRun).where(
                V4ConversationRun.id == prepared_run_id,
                V4ConversationRun.conversation_id == conversation.id,
                V4ConversationRun.user_id == current_user.user_id,
            )
        ).scalar_one()
        run.task_id = prepared_task_id or run.task_id or task_id
        run.objective = content
        run.requested_skill = primary_skill
        run.status = "running"
        run.model_name = requested_model
        run.input_payload_json = safe_text_column_json(
            {
                "taskPacket": packet.model_dump(),
                "leaderPlan": _plan_payload(plan),
                "plannerMeta": slim_planner_meta_for_db(planner_meta),
                "pendingPromptMenu": pending_prompt_menu if resume_from_waiting else None,
            }
        )
        run.context_snapshot_json = _json(runtime_context)
        run.updated_at = datetime.utcnow()
    else:
        run = V4ConversationRun(
            conversation_id=conversation.id,
            user_id=current_user.user_id,
            task_id=task_id,
            objective=content,
            requested_skill=primary_skill,
            status="running",
            model_name=requested_model,
            input_payload_json=safe_text_column_json(
                {
                    "taskPacket": packet.model_dump(),
                    "leaderPlan": _plan_payload(plan),
                    "plannerMeta": slim_planner_meta_for_db(planner_meta),
                    "pendingPromptMenu": pending_prompt_menu if resume_from_waiting else None,
                }
            ),
            context_snapshot_json=_json(runtime_context),
        )
        db.add(run)
    db.flush()

    planning_tool_use_index = PLANNING_SUMMARY_TEXT_INDEX
    planning_public_plan_payload = _plan_payload(plan)
    planning_public_plan_payload.pop("requiresUserInput", None)
    planning_public_plan_payload.pop("clarificationQuestion", None)
    for step_item in planning_public_plan_payload.get("steps") or []:
        if not isinstance(step_item, dict):
            continue
        step_item.pop("objective", None)
        step_item.pop("actionLabel", None)
        step_item.pop("pendingLabel", None)
        step_item.pop("runningLabel", None)
        step_item.pop("doneLabel", None)
        step_item.pop("status", None)
    planning_tool_result_payload = {
        "tool": "a2a_planning",
        "steps": len(plan.steps),
        "taskPacket": packet.model_dump(),
        "plan": planning_public_plan_payload,
        "displayText": f"已规划 {len(plan.steps)} 个执行步骤",
    }

    if planning_pre_events is not None:
        runtime_events = planning_pre_events
        saved_events_count = planning_saved_count
        has_planning_thinking_start = any(
            ev.type == "content_block_start" and ev.index == PLANNING_THINKING_INDEX
            for ev in runtime_events
        )
        if has_planning_thinking_start:
            runtime_events.append(
                RuntimeTaskEvent(
                    type="content_block_stop",
                    index=PLANNING_THINKING_INDEX,
                )
            )
        runtime_events.append(
            RuntimeTaskEvent(
                type="content_block_start",
                index=planning_tool_use_index,
                content_block={
                    "type": "tool_use",
                    "name": "a2a_planning",
                    "skillName": "a2a_planning",
                    "stepIndex": 0,
                    "stepTitle": "执行规划",
                    "displayText": "进行中：执行规划",
                },
            )
        )
        runtime_events.append(
            RuntimeTaskEvent(
                type="content_block_stop",
                index=planning_tool_use_index,
                payload=planning_tool_result_payload,
            )
        )
    else:
        runtime_events = [
            RuntimeTaskEvent(
                type="message_start",
                payload={
                    "taskPacket": packet.model_dump(),
                    "registry": root_task.snapshot(),
                    "taskId": task_id,
                    "requestedSkill": primary_skill,
                },
            ),
            RuntimeTaskEvent(
                type="content_block_start",
                index=PLANNING_THINKING_INDEX,
                content_block={"type": "thinking"},
            ),
            RuntimeTaskEvent(
                type="content_block_delta",
                index=PLANNING_THINKING_INDEX,
                delta={"type": "thinking_delta", "thinking": planner_meta.get("reasoningContent") or "正在生成执行计划..."},
            ),
            RuntimeTaskEvent(
                type="content_block_stop",
                index=PLANNING_THINKING_INDEX,
            ),
            RuntimeTaskEvent(
                type="content_block_start",
                index=planning_tool_use_index,
                content_block={
                    "type": "tool_use",
                    "name": "a2a_planning",
                    "skillName": "a2a_planning",
                    "stepIndex": 0,
                    "stepTitle": "执行规划",
                    "displayText": "进行中：执行规划",
                },
            ),
            RuntimeTaskEvent(
                type="content_block_stop",
                index=planning_tool_use_index,
                payload=planning_tool_result_payload,
            ),
        ]
        saved_events_count = 0
    db.commit()
    _, saved_events_count = _save_new_events(db, run, current_user, runtime_events, saved_events_count)

    def push_event(event: RuntimeTaskEvent) -> None:
        nonlocal saved_events_count
        runtime_events.append(event)
        _, saved_events_count = _save_new_events(db, run, current_user, runtime_events, saved_events_count)

    def make_step_stream_callback(
        step: ExecutionStep,
        push: Callable[[RuntimeTaskEvent], None],
    ) -> tuple[Callable[[str, str], None], Callable[[], bool]]:
        """为单个子步骤生成流式 text_delta 回调。

        返回 (on_text_delta, has_started)。
        - has_started(): 调用方在执行完 skill 后检查；若未 started 且结果含正文，可补发一次合成 text 块。
        - 首次产生 text_delta 时懒发 content_block_start(type=text, purpose=...)；结束时补发 content_block_stop。
        """
        text_index = text_index_for_step(step.index)
        purpose = purpose_for_skill(step.skill_name)
        tool_name = "main_agent" if step.subtask_role == "main_agent" else step.skill_name
        running_display = display_text_for_step(step, phase="running")
        state = {
            "started": False,
            "stopped": False,
            "last_flush_len": 0,
            "last_flush_t": time.monotonic(),
        }
        batch_chars = 80
        flush_interval = 0.4

        def on_text_delta(full_text: str, delta: str) -> None:
            if state["stopped"]:
                return
            text = full_text or ""
            now = time.monotonic()
            is_final = delta == ""
            n = len(text)
            should_push = False
            if is_final and n > 0:
                should_push = n > state["last_flush_len"]
            elif n > 0:
                grown = n - state["last_flush_len"]
                if grown >= batch_chars or (now - state["last_flush_t"]) >= flush_interval:
                    should_push = True
            if should_push:
                if not state["started"]:
                    state["started"] = True
                    push(
                        RuntimeTaskEvent(
                            type="content_block_start",
                            index=text_index,
                            content_block={
                                "type": "text",
                                "purpose": purpose,
                                "name": tool_name,
                                "displayText": running_display,
                                "stepIndex": step.index,
                                "stepTitle": step.title,
                                "skillName": step.skill_name,
                            },
                        )
                    )
                push(
                    RuntimeTaskEvent(
                        type="content_block_delta",
                        index=text_index,
                        delta={"type": "text_delta", "text": text[state["last_flush_len"]:]},
                    )
                )
                state["last_flush_len"] = n
                state["last_flush_t"] = now
            if is_final and state["started"] and not state["stopped"]:
                # writing 步骤的最终 stop 需携带完整 payload，统一在主流程拿到 skill_result 后再发送。
                if step.skill_name != "writing":
                    state["stopped"] = True
                    push(
                        RuntimeTaskEvent(
                            type="content_block_stop",
                            index=text_index,
                        )
                    )

        def has_started() -> bool:
            return state["started"]

        return on_text_delta, has_started

    a2a_task_registry.set_status(task_id, TASK_STATUS_RUNNING)
    current_input = pending_prompt_menu.get("resumeInput") if resume_from_waiting and pending_prompt_menu else content
    step_outcomes: list[dict] = []
    pending_artifacts: list[dict] = []
    task_ids = [task_id]
    agent_tool = AgentTool()
    pending_direct_answer = planner_meta.get("directAnswer") if not resume_from_waiting else None

    def persist_run(status: str, pending_state: dict | None = None) -> dict:
        assistant_summary, assistant_html = _build_final_assistant_output(
            requested_model,
            plan,
            step_outcomes,
        )
        merged_annotations = _merge_annotations(step_outcomes)
        assistant_message = V4ConversationMessage(
            conversation_id=conversation.id,
            run_id=run.id,
            user_id=current_user.user_id,
            role="assistant",
            skill_name=primary_skill,
            model_name=requested_model,
            content=assistant_summary or ("等待你的下一步选择" if pending_state else "任务已完成"),
            content_html=assistant_html,
            annotations_json=_json(merged_annotations),
            meta_json=safe_text_column_json(
                {
                    "tools": ["lead_agent", *[item["skill_name"] for item in step_outcomes]],
                    "keyFiles": [],
                    "leaderPlan": _plan_payload(plan),
                    "plannerMeta": slim_planner_meta_for_db(planner_meta),
                    "plannerReasoning": (planner_meta.get("reasoningContent") or "")[:4000] or None,
                    "normalizedResult": [item.get("normalized_result") for item in step_outcomes],
                    "handoffTrace": _subtask_trace(step_outcomes),
                    "stepOutcomes": [slim_step_outcome_for_db(item) for item in step_outcomes],
                    "pendingPromptMenu": pending_state["promptMenu"] if pending_state else None,
                    "messageActions": _message_actions(),
                }
            ),
        )
        db.add(assistant_message)
        db.flush()

        artifacts = [
            _create_artifact_and_workspace_entry(
                db,
                current_user,
                conversation,
                run,
                assistant_message,
                artifact,
                merged_annotations,
            )
            for artifact in pending_artifacts
        ]

        a2a_task_registry.set_output(task_id, assistant_summary or "任务已完成")
        a2a_task_registry.set_status(
            task_id,
            TASK_STATUS_RUNNING if pending_state else TASK_STATUS_COMPLETED,
        )

        run.status = status
        run.assistant_message_id = assistant_message.id
        run.result_summary = assistant_summary or ("等待用户继续选择" if pending_state else "任务已完成")
        run.updated_at = datetime.utcnow()
        conversation.title = clip_title(
            conversation.title if conversation.title != "新对话" else content
        )
        conversation.last_run_id = run.id
        conversation.updated_at = datetime.utcnow()
        conversation.last_message_at = conversation.updated_at
        _merge_runtime_state(
            conversation,
            runtime_context,
            {
                "pendingPromptMenu": pending_state,
                "taskTree": _collect_task_tree(task_ids),
            },
        )
        maybe_compact_conversation(db, conversation, current_user)
        current_profile = _touch_profile_after_run(
            db,
            current_user,
            conversation,
            primary_skill,
            requested_model,
        )
        db.commit()
        model_error_pending = (
            isinstance(pending_state, dict)
            and (pending_state.get("sourceState") == "model_error")
        )
        if pending_state and not model_error_pending:
            prompt_menu = pending_state.get("promptMenu") if isinstance(pending_state, dict) else None
            push_event(
                RuntimeTaskEvent(
                    type="waiting_user",
                    payload={
                        "taskId": pending_state.get("taskId"),
                        "resumeToken": pending_state["resumeToken"],
                        "promptMenu": prompt_menu,
                    },
                )
            )
            push_event(RuntimeTaskEvent(type="message_stop"))
        elif model_error_pending:
            # 模型失败场景直接结束流，不再额外下发 waiting_user / end_turn。
            push_event(RuntimeTaskEvent(type="message_stop"))
        else:
            push_event(RuntimeTaskEvent(type="message_stop"))
        return {
            "run": run,
            "events": db.execute(
                select(V4TaskEvent).where(V4TaskEvent.run_id == run.id).order_by(V4TaskEvent.seq_no.asc())
            ).scalars().all(),
            "assistant_message": assistant_message,
            "artifacts": artifacts,
            "profile": current_profile,
        }

    def persist_failure(exc: Exception) -> dict:
        import traceback as _traceback
        failure_text = str(exc) or "执行失败"
        tb_text = _traceback.format_exc()
        log_stage(
            "runtime.run.failed",
            {
                "conversationId": conversation.id,
                "runId": run.id,
                "error": failure_text,
                "traceback": tb_text,
            },
            enabled=settings.debug_runtime_logs,
            max_chars=settings.debug_log_max_chars,
            max_string_chars=settings.debug_log_max_string_chars,
        )
        assistant_message = V4ConversationMessage(
            conversation_id=conversation.id,
            run_id=run.id,
            user_id=current_user.user_id,
            role="assistant",
            skill_name=primary_skill,
            model_name=requested_model,
            content="执行失败",
            content_html=f"<section class='assistant-block'><h4>执行失败</h4><p>{escape(failure_text)}</p></section>",
            annotations_json=_json([]),
            meta_json=safe_text_column_json(
                {
                    "tools": ["lead_agent", *[item["skill_name"] for item in step_outcomes]],
                    "keyFiles": [],
                    "leaderPlan": _plan_payload(plan),
                    "plannerMeta": slim_planner_meta_for_db(planner_meta),
                    "plannerReasoning": (planner_meta.get("reasoningContent") or "")[:4000] or None,
                    "normalizedResult": [],
                    "handoffTrace": _subtask_trace(step_outcomes),
                    "stepOutcomes": [slim_step_outcome_for_db(item) for item in step_outcomes],
                    "pendingPromptMenu": None,
                    "messageActions": _message_actions(),
                }
            ),
        )
        db.add(assistant_message)
        db.flush()
        a2a_task_registry.set_output(task_id, failure_text)
        a2a_task_registry.set_status(task_id, TASK_STATUS_FAILED)
        run.status = "failed"
        run.assistant_message_id = assistant_message.id
        run.result_summary = failure_text
        run.updated_at = datetime.utcnow()
        conversation.last_run_id = run.id
        conversation.updated_at = datetime.utcnow()
        conversation.last_message_at = conversation.updated_at
        _merge_runtime_state(
            conversation,
            runtime_context,
            {
                "pendingPromptMenu": None,
                "taskTree": _collect_task_tree(task_ids),
            },
        )
        db.commit()
        error_payload: dict[str, Any] = {
            "errorDetail": failure_text,
            "assistantMessageId": assistant_message.id,
        }
        if settings.include_error_traceback:
            error_payload["traceback"] = tb_text
        push_event(
            RuntimeTaskEvent(
                type="error",
                payload=error_payload,
            )
        )
        push_event(RuntimeTaskEvent(type="message_stop"))
        return {
            "run": run,
            "events": db.execute(
                select(V4TaskEvent).where(V4TaskEvent.run_id == run.id).order_by(V4TaskEvent.seq_no.asc())
            ).scalars().all(),
            "assistant_message": assistant_message,
            "artifacts": [],
            "profile": profile,
        }

    try:
        if resume_from_waiting:
            choice_result, choice_blocks, choice_artifacts, choice_annotations, next_prompt_menu = _resolve_prompt_menu_choice(
                pending_prompt_menu,
                selected_option,
                prompt_menu_input,
            )
            choice_title = pending_prompt_menu.get("title") or title_for_skill(primary_skill)
            choice_task_id = task_registry.next_task_id(conversation.id)
            choice_step = ExecutionStep(
                index=0,
                skill_name=primary_skill,
                title=choice_title,
                objective="根据用户对 Prompt Menu 的选择继续执行。",
                scope="恢复等待中的多阶段任务。",
            )
            choice_packet = build_subtask_packet(
                task_id=choice_task_id,
                parent_task_id=task_id,
                conversation_id=conversation.id,
                step=choice_step,
                requested_model=requested_model,
                step_input=current_input,
                attachments=attachments,
                runtime_context_summary=runtime_context["summary"],
                user_memory_refs=user_memory_refs,
                handoff_trace=[],
            )
            a2a_task_registry.register(
                choice_packet,
                f"Resume Step · {choice_title}",
                parent_task_id=task_id,
                team_id=f"resume-{primary_skill}",
            )
            a2a_task_registry.set_status(choice_task_id, TASK_STATUS_RUNNING)
            a2a_task_registry.append_message(choice_task_id, "user", content)
            a2a_task_registry.set_output(choice_task_id, json.dumps(choice_result, ensure_ascii=False))
            a2a_task_registry.set_status(choice_task_id, TASK_STATUS_COMPLETED)
            task_ids.append(choice_task_id)
            push_event(
                RuntimeTaskEvent(
                    type="tool_result",
                    payload={
                        "tool": "prompt_menu_resume",
                        "selectedOption": selected_option,
                        "promptMenuInput": prompt_menu_input,
                        "resumeToken": pending_prompt_menu.get("resumeToken"),
                        "taskPacket": choice_packet.model_dump(),
                    },
                )
            )
            choice_summary = choice_blocks[0].get("title") if choice_blocks else choice_title
            step_outcomes.append(
                {
                    "index": 0,
                    "task_id": choice_task_id,
                    "skill_name": primary_skill,
                    "title": choice_title,
                    "summary": choice_summary,
                    "html": _html_from_blocks(
                        requested_model,
                        choice_summary,
                        choice_blocks,
                        lead_copy="已根据你的选择继续执行。",
                    ),
                    "normalized_result": choice_result,
                    "annotations": choice_annotations,
                    "retryable": False,
                    "source_state": "workflow_resume",
                    "error_detail": None,
                    "reasoning_content": None,
                }
            )
            pending_artifacts.extend(choice_artifacts)
            current_input = build_handoff_content(
                current_input,
                primary_skill,
                choice_result,
            )
            if next_prompt_menu:
                return persist_run(
                    "waiting_user",
                    {
                        "resumeToken": f"{run.id}:{choice_task_id}",
                        "taskId": choice_task_id,
                        "parentTaskId": task_id,
                        "skillName": primary_skill,
                        "stepIndex": 0,
                        "title": choice_title,
                        "promptMenu": next_prompt_menu,
                        "normalizedResult": choice_result,
                        "annotations": choice_annotations,
                        "remainingSteps": [_step_payload(step) for step in plan.steps],
                        "plan": _plan_payload(plan),
                        "resumeInput": current_input,
                        "sourceState": "workflow_resume",
                        "errorDetail": None,
                    },
                )

        main_agent_inst = MainAgent()
        leader_messages: list[dict] | None = None
        if plan.steps:
            leader_messages = main_agent_inst._build_messages(
                content, attachments, runtime_context, memory_context
            )
            last_user = leader_messages[-1]
            u = last_user.get("content", "")
            last_user["content"] = (
                (u if isinstance(u, str) else str(u))
                + "\n\n【Leader 闭环】sub-agent 的结构化结果将以 OpenAI tool 消息追加；每波执行后 Leader 将再读上下文（opt1）。"
            )

        event_lock = threading.Lock()

        def safe_push(ev: RuntimeTaskEvent) -> None:
            with event_lock:
                push_event(ev)

        def drive_step(step: ExecutionStep, cin: str) -> tuple[dict | None, SkillExecutionResult, str, str]:
            """执行单步；若有提前结束则返回 persist_run 结果字典。"""
            nonlocal pending_direct_answer
            subtask_id = task_registry.next_task_id(conversation.id)
            task_ids.append(subtask_id)
            handoff_trace = _subtask_trace(step_outcomes)
            is_main_agent_step = step.subtask_role == "main_agent"
            subtask_packet = build_subtask_packet(
                task_id=subtask_id,
                parent_task_id=task_id,
                conversation_id=conversation.id,
                step=step,
                requested_model=requested_model,
                step_input=cin,
                attachments=attachments,
                runtime_context_summary=runtime_context["summary"],
                user_memory_refs=user_memory_refs,
                handoff_trace=handoff_trace,
            )
            subtask_record = a2a_task_registry.register(
                subtask_packet,
                f"{'Leader Agent' if is_main_agent_step else 'Sub Agent'} · {step.title}",
                parent_task_id=task_id,
                team_id=subtask_packet.team_id,
            )
            a2a_task_registry.append_message(subtask_id, "leader", cin)
            a2a_task_registry.set_status(subtask_id, TASK_STATUS_RUNNING)

            tool_use_index = tool_use_index_for_step(step.index)
            text_index = text_index_for_step(step.index)
            running_display = display_text_for_step(step, phase="running")
            done_display = display_text_for_step(step, phase="done")
            tool_name = "main_agent" if is_main_agent_step else step.skill_name

            compact_stream = step.skill_name in {"retrieval","general"}
            text_only_stream = step.skill_name in {"writing"}
            # 检索步骤采用紧凑事件：仅保留 tool_use start/stop，不再推送 input_json_delta 与 running。
            # 写作步骤仅保留 text start/delta/stop 一套事件，避免与 tool_use 形成双轨重复。
            if compact_stream:
                safe_push(
                    RuntimeTaskEvent(
                        type="content_block_start",
                        index=tool_use_index,
                        content_block={
                            "type": "tool_use",
                            "name": tool_name,
                            "skillName": step.skill_name,
                            "stepIndex": step.index,
                            "stepTitle": step.title,
                            "displayText": running_display,
                        },
                    )
                )
            elif not text_only_stream:
                safe_push(
                    RuntimeTaskEvent(
                        type="content_block_start",
                        index=tool_use_index,
                        content_block={
                            "type": "tool_use",
                            "name": tool_name,
                            "skillName": step.skill_name,
                            "stepIndex": step.index,
                            "stepTitle": step.title,
                            "displayText": running_display,
                        },
                    )
                )
                safe_push(
                    RuntimeTaskEvent(
                        type="content_block_delta",
                        index=tool_use_index,
                        delta={
                            "type": "input_json_delta",
                            "partial_json": json.dumps({
                                "subtask": subtask_id,
                                "skill": step.skill_name,
                                "depends_on": step.depends_on or [],
                                "objective": step.objective,
                            }, ensure_ascii=False),
                        },
                    )
                )
                safe_push(
                    RuntimeTaskEvent(
                        type="content_block_stop",
                        index=tool_use_index,
                    )
                )
                safe_push(
                    RuntimeTaskEvent(
                        type="running",
                        payload={
                            "taskId": subtask_id,
                            "parentTaskId": task_id,
                            "taskPacket": subtask_packet.model_dump(),
                            "skillName": step.skill_name,
                            "stepIndex": step.index,
                            "stepTitle": step.title,
                            "displayText": running_display,
                        },
                    )
                )

            step_stream_cb, stream_has_started = make_step_stream_callback(step, safe_push)
            stream_callback = None if compact_stream else step_stream_cb

            if is_main_agent_step and pending_direct_answer:
                skill_result = SkillExecutionResult(
                    normalized_result={"text": pending_direct_answer, "source": "planner_direct_answer"},
                    render_blocks=[{"type": "general", "title": "主 Agent 回复", "html": text_to_html(pending_direct_answer)}],
                    artifact_refs=[],
                    editor_annotations=[],
                    retryable=False,
                    source_state="planner_direct_answer",
                    error_detail=None,
                )
                pending_direct_answer = None
            elif is_main_agent_step:
                skill_result = execute_skill(
                    step.skill_name,
                    cin,
                    requested_model,
                    attachments,
                    cookies,
                    runtime_context=runtime_context,
                    memory_context=memory_context,
                    task_packet=subtask_packet.model_dump(),
                    on_text_delta=stream_callback,
                )
            else:
                skill_result = agent_tool.call(
                    agent_name=step.skill_name,
                    task_prompt=cin,
                    requested_model=requested_model,
                    attachments=attachments,
                    cookies=cookies,
                    runtime_context=runtime_context,
                    memory_context=memory_context,
                    task_packet=subtask_packet.model_dump(),
                    on_text_delta=stream_callback,
                )

            # 如果本步骤未走流式通道（例如 retrieval/writing 的 legacy JSON 成功），
            # 但仍有可展示的正文/摘要，则补发一次合成的 text 块，便于前端编辑器联动。
            retrieval_summary_on_stop = False
            if not compact_stream and not stream_has_started():
                synthetic_text = _extract_synthetic_text(step.skill_name, skill_result)
                if synthetic_text:
                    purpose = purpose_for_skill(step.skill_name)
                    safe_push(
                        RuntimeTaskEvent(
                            type="content_block_start",
                            index=text_index,
                            content_block={
                                "type": "text",
                                "purpose": purpose,
                                "name": tool_name,
                                "displayText": running_display,
                                "stepIndex": step.index,
                                "stepTitle": step.title,
                                "skillName": step.skill_name,
                            },
                        )
                    )
                    # 检索 legacy：跳过大段 text_delta（与 normalizedResult 重复），在 stop 上挂结构化 payload 瘦身 SSE
                    if step.skill_name == "retrieval":
                        retrieval_summary_on_stop = True
                        safe_push(
                            RuntimeTaskEvent(
                                type="content_block_stop",
                                index=text_index,
                                payload={
                                    "tool": tool_name,
                                    "taskId": subtask_id,
                                    "skillName": step.skill_name,
                                    "stepIndex": step.index,
                                    "stepTitle": step.title,
                                    "displayText": done_display,
                                    "retryable": skill_result.retryable,
                                    "sourceState": skill_result.source_state,
                                    "errorDetail": skill_result.error_detail,
                                    "normalizedResult": skill_result.normalized_result,
                                },
                            )
                        )
                    else:
                        safe_push(
                            RuntimeTaskEvent(
                                type="content_block_delta",
                                index=text_index,
                                delta={"type": "text_delta", "text": synthetic_text},
                            )
                        )
                        if step.skill_name != "writing":
                            safe_push(
                                RuntimeTaskEvent(
                                    type="content_block_stop",
                                    index=text_index,
                                )
                            )

            step_html = render_assistant_html(step.skill_name, skill_result, requested_model or "")
            step_summary = skill_result.render_blocks[0].get("title") if skill_result.render_blocks else title_for_skill(step.skill_name)
            a2a_task_registry.append_message(subtask_id, "sub_agent", step_summary)
            a2a_task_registry.set_output(
                subtask_id,
                json.dumps(skill_result.normalized_result, ensure_ascii=False),
            )
            a2a_task_registry.set_status(subtask_id, TASK_STATUS_COMPLETED)
            tool_result_payload: dict[str, Any] = {
                "tool": tool_name,
                "taskId": subtask_id,
                "skillName": step.skill_name,
                "stepIndex": step.index,
                "stepTitle": step.title,
                "displayText": done_display,
                "normalizedResult": skill_result.normalized_result,
                "retryable": skill_result.retryable,
                "sourceState": skill_result.source_state,
                "errorDetail": skill_result.error_detail,
            }
            if text_only_stream:
                safe_push(
                    RuntimeTaskEvent(
                        type="content_block_stop",
                        index=text_index,
                        payload=tool_result_payload,
                    )
                )
            elif compact_stream:
                safe_push(
                    RuntimeTaskEvent(
                        type="content_block_stop",
                        index=tool_use_index,
                        payload=tool_result_payload,
                    )
                )
            elif retrieval_summary_on_stop:
                tool_result_payload.pop("normalizedResult", None)
                safe_push(
                    RuntimeTaskEvent(
                        type="tool_result",
                        payload=tool_result_payload,
                    )
                )
            else:
                safe_push(
                    RuntimeTaskEvent(
                        type="tool_result",
                        payload=tool_result_payload,
                    )
                )
            step_outcomes.append(
                {
                    "index": step.index,
                    "task_id": subtask_id,
                    "skill_name": step.skill_name,
                    "title": step.title,
                    "summary": step_summary,
                    "html": step_html,
                    "normalized_result": skill_result.normalized_result,
                    "annotations": skill_result.editor_annotations,
                    "retryable": skill_result.retryable,
                    "source_state": skill_result.source_state,
                    "error_detail": skill_result.error_detail,
                    "reasoning_content": skill_result.reasoning_content,
                }
            )
            pending_artifacts.extend(skill_result.artifact_refs)
            next_cin = build_handoff_content(
                cin,
                step.skill_name,
                skill_result.normalized_result,
            )
            if step.skill_name == "writing" and skill_result.source_state == "model_error":
                return (
                    persist_run(
                        "waiting_user",
                        {
                            "resumeToken": f"{run.id}:{subtask_id}",
                            "taskId": subtask_id,
                            "parentTaskId": task_id,
                            "skillName": step.skill_name,
                            "stepIndex": step.index,
                            "title": step.title,
                            "promptMenu": {
                                "type": "clarification",
                                "title": "写作模型调用失败",
                                "description": skill_result.error_detail or "模型调用失败，请检查网关配置后重试或补充要求。",
                                "question": skill_result.error_detail,
                                "options": [{"key": "custom_input", "label": "补充说明并重试", "recommended": True}],
                                "resultPreview": skill_result.normalized_result,
                                "resumeMode": "rerun_current_step",
                            },
                            "resumeMode": "rerun_current_step",
                            "resumeCurrentStep": _step_payload(step),
                            "normalizedResult": skill_result.normalized_result,
                            "annotations": skill_result.editor_annotations,
                            "remainingSteps": [_step_payload(item) for item in plan.steps if item.index > step.index],
                            "plan": _plan_payload(plan),
                            "resumeInput": next_cin,
                            "sourceState": skill_result.source_state,
                            "errorDetail": skill_result.error_detail,
                        },
                    ),
                    skill_result,
                    subtask_id,
                    next_cin,
                )
            if step.skill_name in INTERACTIVE_SKILLS:
                prompt_menu = _build_prompt_menu(
                    step,
                    skill_result.normalized_result,
                    skill_result.editor_annotations,
                    skill_result,
                )
                if prompt_menu:
                    return (
                        persist_run(
                            "waiting_user",
                            {
                                "resumeToken": f"{run.id}:{subtask_id}",
                                "taskId": subtask_id,
                                "parentTaskId": task_id,
                                "skillName": step.skill_name,
                                "stepIndex": step.index,
                                "title": step.title,
                                "promptMenu": prompt_menu,
                                "resumeMode": prompt_menu.get("resumeMode") or "prompt_menu_choice",
                                "resumeCurrentStep": (
                                    _step_payload(step)
                                    if prompt_menu.get("resumeMode") == "rerun_current_step"
                                    else None
                                ),
                                "normalizedResult": skill_result.normalized_result,
                                "annotations": skill_result.editor_annotations,
                                "remainingSteps": [_step_payload(item) for item in plan.steps if item.index > step.index],
                                "plan": _plan_payload(plan),
                                "resumeInput": next_cin,
                                "sourceState": skill_result.source_state,
                                "errorDetail": skill_result.error_detail,
                            },
                        ),
                        skill_result,
                        subtask_id,
                        next_cin,
                    )
            return None, skill_result, subtask_id, next_cin

        waves = _execution_step_waves(plan.steps)
        for wave_idx, wave in enumerate(waves):
            if (
                leader_messages is not None
                and wave_idx > 0
                and settings.enable_model_planner
            ):
                try:
                    guarded = apply_leader_context_guard(
                        leader_messages,
                        max_context_tokens=settings.compaction_max_chars // 4,
                    )
                    reflect = main_agent_inst.leader_step(guarded, requested_model)
                    log_stage(
                        "leader.reflect",
                        {
                            "conversationId": conversation.id,
                            "modelName": reflect.get("model_name"),
                            "hasToolCalls": bool((reflect.get("message") or {}).get("tool_calls")),
                            "estimatedTokens": estimate_tokens(guarded),
                        },
                        enabled=settings.debug_runtime_logs,
                        max_chars=settings.debug_log_max_chars,
                        max_string_chars=settings.debug_log_max_string_chars,
                    )
                except Exception as exc:
                    log_stage(
                        "leader.reflect.error",
                        {"error": str(exc)},
                        enabled=settings.debug_runtime_logs,
                        max_chars=settings.debug_log_max_chars,
                        max_string_chars=settings.debug_log_max_string_chars,
                    )

            wave_steps = sorted(wave, key=lambda s: s.index)
            wave_inputs: list[str] = []
            wave_results: list[SkillExecutionResult] = []
            wave_ids: list[str] = []
            use_parallel = (
                len(wave_steps) > 1
                and not pending_direct_answer
            )
            if use_parallel:
                wave_input_base = current_input

                def _run_parallel(st: ExecutionStep) -> tuple[ExecutionStep, dict | None, SkillExecutionResult, str, str]:
                    return (st, *drive_step(st, wave_input_base))

                with ThreadPoolExecutor(max_workers=min(4, len(wave_steps))) as pool:
                    futs = [pool.submit(_run_parallel, st) for st in wave_steps]
                    ordered: list[tuple] = []
                    for fut in as_completed(futs):
                        ordered.append(fut.result())
                    ordered.sort(key=lambda row: row[0].index)
                    for st, early, sr, sid, nxt in ordered:
                        if early is not None:
                            return early
                        wave_results.append(sr)
                        wave_ids.append(sid)
                        wave_inputs.append(wave_input_base)
                    merged = wave_input_base
                    for st, _early, sr, _sid, _nxt in ordered:
                        merged = build_handoff_content(merged, st.skill_name, sr.normalized_result)
                    current_input = merged
            else:
                for step in wave_steps:
                    step_input_snapshot = current_input
                    early, sr, sid, next_cin = drive_step(step, current_input)
                    if early is not None:
                        return early
                    wave_results.append(sr)
                    wave_ids.append(sid)
                    wave_inputs.append(step_input_snapshot)
                    current_input = next_cin

            if leader_messages is not None and wave_steps:
                tool_calls, _call_ids = build_synthetic_dispatch_tool_calls(
                    wave_steps,
                    task_prompts=wave_inputs,
                )
                leader_messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": tool_calls,
                    }
                )
                for tc, st, sid, res in zip(tool_calls, wave_steps, wave_ids, wave_results):
                    leader_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": format_dispatch_tool_result_json(
                                step=st,
                                subtask_id=sid,
                                normalized_result=res.normalized_result,
                                source_state=res.source_state,
                                error_detail=res.error_detail,
                                retryable=res.retryable,
                            ),
                        }
                    )

        return persist_run("completed")
    except Exception as exc:
        return persist_failure(exc)


def execute_prepared_run(
    conversation_id: str,
    current_user,
    *,
    run_id: str,
    task_id: str,
    content: str,
    requested_skill: str | None,
    requested_model: str | None,
    attachments: list[dict],
    cookies: str | None,
    resume_from_waiting: bool = False,
    selected_option: str | None = None,
    prompt_menu_input: str | None = None,
) -> None:
    db = SessionLocal()
    try:
        conversation = db.execute(
            select(V4Conversation).where(
                V4Conversation.id == conversation_id,
                V4Conversation.user_id == current_user.user_id,
                V4Conversation.is_deleted.is_(False),
            )
        ).scalar_one()
        run_conversation(
            db,
            conversation,
            current_user,
            content,
            requested_skill,
            requested_model,
            attachments,
            cookies,
            resume_from_waiting,
            selected_option,
            prompt_menu_input,
            prepared_run_id=run_id,
            prepared_task_id=task_id,
        )
    finally:
        db.close()


def first_login_to_agent_app(db: Session, user_id: str) -> bool:
    count = db.execute(
        select(func.count()).select_from(V4Conversation).where(
            V4Conversation.user_id == user_id, V4Conversation.is_deleted.is_(False)
        )
    ).scalar_one()
    return count == 0



def read_profile_docs(current_user, profile: V4UserProfile) -> dict:
    identify_markdown = read_user_doc(current_user.user_id, profile.identify_md_path)
    memory_markdown = read_user_doc(current_user.user_id, profile.memory_md_path)
    session_summary_markdown = read_user_doc(
        current_user.user_id, profile.last_session_summary_md_path
    )
    return {
        "identify_markdown": identify_markdown,
        "memory_markdown": memory_markdown,
        "session_summary_markdown": session_summary_markdown,
    }


def build_prompt_profile_docs(current_user, profile: V4UserProfile) -> dict:
    raw_docs = read_profile_docs(current_user, profile)
    mem_expanded = _expand_memory_index_markdown(
        current_user.user_id,
        raw_docs["memory_markdown"],
        prefix="topics/",
        max_files=3,
        max_chars_per_file=900,
        section_title="已展开的关键主题内容",
    )
    sess_expanded = _expand_memory_index_markdown(
        current_user.user_id,
        raw_docs["session_summary_markdown"],
        prefix="sessions/",
        max_files=2,
        max_chars_per_file=1200,
        section_title="已展开的最近会话摘要",
    )
    return {
        "identify_markdown": summarize_memory_for_context(raw_docs["identify_markdown"] or "", max_chars=1200),
        "memory_markdown": summarize_memory_for_context(mem_expanded, max_chars=2000),
        "session_summary_markdown": summarize_memory_for_context(sess_expanded, max_chars=1600),
    }
