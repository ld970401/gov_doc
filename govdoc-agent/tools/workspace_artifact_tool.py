from __future__ import annotations

from typing import Any


class WorkspaceArtifactTool:
    """工作区产物提交工具（stub）。

    说明：
    - 本阶段仅提供工具契约与空实现，不执行真实写盘；
    - 后续可接入 runtime 中现有 workspace/artifact 持久化链路。
    """

    tool_name = "commit_workspace_artifact"

    def get_tool_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.tool_name,
                "description": "将最终写作产物提交到工作空间（当前为 stub，占位不落盘）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "产物标题"},
                        "artifact_type": {
                            "type": "string",
                            "enum": ["document", "report"],
                            "description": "产物类型",
                        },
                        "content_text": {"type": "string", "description": "正文纯文本"},
                        "content_html": {"type": "string", "description": "正文 HTML（可选）"},
                        "summary": {"type": "string", "description": "摘要（可选）"},
                    },
                    "required": ["title", "artifact_type", "content_text"],
                    "additionalProperties": False,
                },
            },
        }

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        # stub: 当前仅返回占位状态，不进行真实写入。
        return {
            "tool": self.tool_name,
            "committed": False,
            "status": "stub_not_implemented",
            "title": payload.get("title"),
            "artifactType": payload.get("artifact_type"),
        }

