"""文本后处理：寒暄前缀剥离、Markdown → 纯文本、公文正文抽取。

模型输出规范由 prompt 约束，但真实运行中仍会出现偏差：
- "好的，我可以帮您…"、"以下是范文：" 等寒暄/引导语；
- 公文正文被 **加粗**、``## 标题``、``---`` 等 Markdown 包裹；
- 结尾补一句"如需调整请告诉我"。

本模块提供与 LLM 约定互补的"代码侧兜底"，保证前端真正收到的是：
1. 公文场景 → 纯文本正文（保留换行），无 Markdown、无寒暄。
2. 通用回复 → 去掉寒暄与末尾客套，格式保持自然。
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 寒暄前缀 / 末尾客套
# ---------------------------------------------------------------------------

_GREETING_PATTERNS = [
    re.compile(r"^(?:好的|好嘞|没问题|没问题的|当然可以|当然了|当然)[，,。！!：:]\s*"),
    re.compile(
        r"^(?:我(?:可以|来|这就|马上)?(?:帮|为)(?:您|你)(?:生成|起草|撰写|写出|写|拟)[^。！!\n]*[，,。！!])\s*"
    ),
    re.compile(r"^(?:以下(?:是|为)[^。！!\n]*[：:])\s*"),
    re.compile(r"^(?:下面(?:是|为)[^。！!\n]*[：:])\s*"),
    re.compile(r"^(?:这(?:是|就是)[^。！!\n]*[：:])\s*"),
    re.compile(r"^(?:根据(?:您|你)的(?:要求|需求|指示)[，,。！!])\s*"),
    re.compile(r"^(?:收到[，,。！!])\s*"),
    re.compile(r"^(?:明白了?[，,。！!])\s*"),
    re.compile(r"^(?:已(?:为您|给您)?(?:生成|起草|撰写|整理)[^。！!\n]*[，,。！!])\s*"),
    re.compile(r"^(?:OK|Ok|ok)[，,。！!：:]?\s*"),
]

_TRAILING_OFFER_PATTERNS = [
    re.compile(
        r"\n+[^\n]*?(?:如(?:您|你)?(?:需要|有)(?:其他|进一步|更多)[^\n]*?(?:[。！!].*)?)$",
        re.DOTALL,
    ),
    re.compile(
        r"\n+[^\n]*?(?:如需(?:要)?[^\n]*?(?:调整|修改|补充|完善)[^\n]*?(?:[。！!].*)?)$",
        re.DOTALL,
    ),
    re.compile(r"\n+[^\n]*?请(?:随时)?告(?:诉|知)我[^\n]*(?:[。！!].*)?$", re.DOTALL),
    re.compile(r"\n+[^\n]*?希望(?:对您)?(?:有所|能)帮助[^\n]*(?:[。！!].*)?$", re.DOTALL),
]


def strip_conversational_prefix(text: str) -> str:
    """剥离中文寒暄开头。最多迭代 4 次以覆盖叠加前缀。"""
    if not text:
        return ""
    cleaned = text.lstrip()
    for _ in range(4):
        new_val = cleaned
        for pattern in _GREETING_PATTERNS:
            new_val2 = pattern.sub("", new_val, count=1)
            if new_val2 != new_val:
                new_val = new_val2.lstrip()
                break
        if new_val == cleaned:
            break
        cleaned = new_val
    return cleaned


def strip_trailing_offers(text: str) -> str:
    """剥离结尾"如需调整请告诉我 / 希望对您有帮助"等客套。"""
    if not text:
        return ""
    cleaned = text
    for pattern in _TRAILING_OFFER_PATTERNS:
        new_val = pattern.sub("", cleaned)
        if new_val != cleaned:
            cleaned = new_val
    return cleaned.rstrip()


# ---------------------------------------------------------------------------
# Markdown -> 纯文本
# ---------------------------------------------------------------------------

_FENCED_CODE_RE = re.compile(r"```[A-Za-z0-9_-]*\n?([\s\S]*?)\n?```", re.MULTILINE)
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", re.MULTILINE)
_H_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BOLD_STAR_RE = re.compile(r"\*\*([^\n*]+?)\*\*")
_BOLD_UNDER_RE = re.compile(r"__([^\n_]+?)__")
_ITALIC_STAR_RE = re.compile(r"(?<![*\w])\*([^\n*]+?)\*(?!\*)")
_ITALIC_UNDER_RE = re.compile(r"(?<![_\w])_([^\n_]+?)_(?!_)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+?)`")
_LIST_BULLET_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def strip_markdown_to_plain(text: str) -> str:
    """将含 Markdown 符号的文本降为纯文本，保留段落换行。

    保留的内容：
    - 中文编号（一、二、/1./2.）不会被误伤；
    - 段落结构通过换行保留；
    - 段落内合并后的 3 个以上换行会压缩到 2 个。
    """
    if not text:
        return ""
    out = text.replace("\r\n", "\n")
    out = _FENCED_CODE_RE.sub(lambda m: m.group(1), out)
    out = _IMG_RE.sub(r"\1", out)
    out = _LINK_RE.sub(r"\1", out)
    out = _HR_RE.sub("", out)
    out = _H_RE.sub("", out)
    out = _BLOCKQUOTE_RE.sub("", out)
    out = _BOLD_STAR_RE.sub(r"\1", out)
    out = _BOLD_UNDER_RE.sub(r"\1", out)
    out = _ITALIC_STAR_RE.sub(r"\1", out)
    out = _ITALIC_UNDER_RE.sub(r"\1", out)
    out = _INLINE_CODE_RE.sub(r"\1", out)
    out = _LIST_BULLET_RE.sub("", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


# ---------------------------------------------------------------------------
# 公文正文抽取
# ---------------------------------------------------------------------------

_BODY_XML_RE = re.compile(
    r"<\s*正文\s*>\s*([\s\S]*?)\s*<\s*/\s*正文\s*>", re.IGNORECASE
)
_BODY_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:##\s*)?正文\s*[:：]?\s*\n([\s\S]+)$", re.IGNORECASE
)
_FRONT_MATTER_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:##\s*)?(?:写作思路|思路说明|说明)\s*\n[\s\S]*?"
    r"(?=\n\s*(?:##\s*)?正文\s*[:：]?\s*\n|$)",
    re.IGNORECASE,
)
_PLACEHOLDER_HINT_RE = re.compile(r"(?:待补充|待填写|自行填写|请补充|另行填写)")


def extract_document_body(raw: str) -> str:
    """从写作 agent 返回中抽取"正文"部分。

    识别顺序：
    1. ``<正文>...</正文>`` 显式标签（prompt 推荐契约）
    2. ``## 正文`` / ``正文`` 标题分段（兼容旧 prompt 返回）
    3. 无标签：剥离可能存在的"写作思路"前言后返回剩余
    """
    if not raw:
        return ""
    text = raw.strip()
    m = _BODY_XML_RE.search(text)
    if m:
        return m.group(1).strip()
    m2 = _BODY_HEADING_RE.search(text)
    if m2:
        return m2.group(1).strip()
    stripped = _FRONT_MATTER_HEADING_RE.sub("", text, count=1)
    return stripped.strip()


def clean_document_text(raw: str) -> str:
    """公文写作输出的完整后处理：抽取正文 → 剥离 Markdown → 去除寒暄/末尾客套。"""
    body = extract_document_body(raw or "")
    body = strip_conversational_prefix(body)
    body = strip_markdown_to_plain(body)
    body = strip_trailing_offers(body)
    # 统一未知信息占位符，避免出现多种"待补充/自行填写"写法。
    body = _PLACEHOLDER_HINT_RE.sub("xxx", body)
    return body.strip()


def clean_general_text(raw: str) -> str:
    """通用回复的轻量后处理：去除寒暄开头与末尾客套。"""
    out = strip_conversational_prefix(raw or "")
    out = strip_trailing_offers(out)
    return out.strip()
