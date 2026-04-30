from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    display_name: str
    description: str
    system_prompt_path: str
    tools: list[str]
    when_to_use: str
    when_not_to_use: str
    can_be_chained: bool = True
    background: bool = False
    metadata: dict = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    examples: list[str] = field(default_factory=list)
    prompt_key: str | None = None
    selectable: bool = True
    default_objective: str = ""

    @property
    def title(self) -> str:
        return self.display_name

    @property
    def scope(self) -> str:
        return str(self.metadata.get("scope") or self.when_to_use)

    @property
    def default_subtask_role(self) -> str:
        return str(self.metadata.get("subtask_role") or ("skill_worker" if self.selectable else "main_agent"))

    @property
    def summary(self) -> str:
        return self.description

    @property
    def prompt_path(self) -> Path:
        relative = self.system_prompt_path.lstrip("/").replace("\\", "/")
        return PROJECT_ROOT / relative


MAIN_AGENT = AgentDefinition(
    name="general",
    display_name="主 Agent 对话",
    description="用户直接与主 Agent 对话；主 Agent 负责理解意图，决定直接回答还是调度 sub agent。",
    system_prompt_path="prompts/sub/general.md",
    tools=["dispatch_sub_agent"],
    when_to_use="闲聊、能力咨询、流程说明、策略建议，或无需调用专门 sub agent 的简单问答。",
    when_not_to_use="用户明确选择了某个 sub agent，或确需检索、写作、审核、查重、排版等专业能力时。",
    can_be_chained=False,
    metadata={
        "scope": "处理通用问答、能力说明和主 Agent 直接回复场景。",
        "subtask_role": "main_agent",
    },
    aliases=("main", "lead", "leader"),
    examples=["你好，你是谁", "你现在能帮我做什么", "我应该先用哪个 agent"],
    prompt_key="general",
    selectable=False,
    default_objective="主 Agent 直接回应用户问题，必要时说明下一步建议调用的 sub agent。",
)


class AgentRegistry:
    _agents: dict[str, AgentDefinition] = {}
    _aliases: dict[str, str] = {}
    _registered: bool = False

    @classmethod
    def register(cls, agent_def: AgentDefinition) -> None:
        cls._agents[agent_def.name] = agent_def
        cls._aliases[agent_def.name] = agent_def.name
        for alias in agent_def.aliases:
            cls._aliases[alias.lower()] = agent_def.name

    @classmethod
    def normalize_name(cls, name: str | None) -> str | None:
        normalized = (name or "").strip().lower()
        if not normalized:
            return None
        if normalized == "general":
            return "general"
        return cls._aliases.get(normalized)

    @classmethod
    def get(cls, name: str | None) -> AgentDefinition | None:
        canonical = cls.normalize_name(name)
        if canonical == "general":
            return MAIN_AGENT
        if not canonical:
            return None
        return cls._agents.get(canonical)

    @classmethod
    def list_all(cls) -> list[AgentDefinition]:
        return list(cls._agents.values())

    @classmethod
    def list_selectable(cls) -> list[AgentDefinition]:
        return [item for item in cls.list_all() if item.selectable]

    @classmethod
    def to_prompt_context(cls) -> str:
        lines = ["## 可用 Sub Agent 清单", ""]
        for agent in cls.list_selectable():
            lines.append(f"### {agent.name}（{agent.display_name}）")
            lines.append(f"- 功能：{agent.description}")
            lines.append(f"- 可用工具：{', '.join(agent.tools) or '无'}")
            lines.append(f"- 适用场景：{agent.when_to_use}")
            lines.append(f"- 不适用场景：{agent.when_not_to_use}")
            lines.append(f"- 可串联：{'是' if agent.can_be_chained else '否'}")
            lines.append("")
        return "\n".join(lines).strip()


def _load_prompt(prompt_path: Path) -> str:
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "你是智慧公文系统的 agent。请基于当前任务边界完成工作。"


def canonical_agent_name(name: str | None) -> str | None:
    canonical = AgentRegistry.normalize_name(name)
    return canonical or ("general" if (name or "").strip().lower() == "general" else None)


def get_agent_spec(name: str) -> AgentDefinition:
    agent = AgentRegistry.get(name)
    if agent is None:
        raise ValueError(f"未知 agent: {name}")
    return agent


def title_for_agent(name: str) -> str:
    return get_agent_spec(name).title


def scope_for_agent(name: str) -> str:
    return get_agent_spec(name).scope


def prompt_key_for_agent(name: str) -> str | None:
    return get_agent_spec(name).prompt_key


def system_prompt_for_agent(name: str | None) -> str:
    return _load_prompt(get_agent_spec(name or "general").prompt_path)


def selectable_sub_agents() -> list[AgentDefinition]:
    return AgentRegistry.list_selectable()


def exposed_agent_descriptors() -> list[dict]:
    order = ["retrieval", "writing", "review", "dedup", "layout"]
    order_index = {k: i for i, k in enumerate(order)}
    ordered = sorted(
        selectable_sub_agents(),
        key=lambda item: (order_index.get(item.name, 999), item.name),
    )
    return [
        {
            "key": agent.name,
            "title": agent.display_name,
            "summary": agent.description,
            "examples": agent.examples,
            "aliases": list(agent.aliases),
            "tools": agent.tools,
            "whenToUse": agent.when_to_use,
            "whenNotToUse": agent.when_not_to_use,
        }
        for agent in ordered
    ]
