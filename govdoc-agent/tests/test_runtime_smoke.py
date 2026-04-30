"""
Runtime 端到端冒烟测试（无网络、无 DB）。

覆盖：
- `app.event_payload`：内容块 index 分段、displayText / purpose 映射、slim 白名单。
- `app.a2a_runtime.build_handoff_content`：retrieval summary_text 整段下传、items 列点路径。
- `app.runtime._extract_synthetic_text`：legacy 成功但无流式时能提取可展示文本。
- `agents.main_agent.MainAgent._normalize_document_steps` 与 `_looks_like_writing_request`：
  扩充的触发词（拟/生成/倡议书/方案等）能正确追加 writing 步骤。

运行：
  PYTHONPATH=. python3 -m unittest tests.test_runtime_smoke -v
"""

from __future__ import annotations

import unittest

from app.a2a_runtime import ExecutionStep, build_handoff_content
from app.agent_capability_adapter import SkillExecutionResult
from app.event_payload import (
    PLANNING_SUMMARY_TEXT_INDEX,
    PLANNING_THINKING_INDEX,
    display_text_for_step,
    done_label_for_skill,
    purpose_for_skill,
    slim_content_block,
    slim_delta,
    slim_payload,
    text_index_for_step,
    tool_use_index_for_step,
)
from app.runtime import _extract_synthetic_text
from agents.main_agent import MainAgent


def _make_step(index: int, skill: str, title: str) -> ExecutionStep:
    return ExecutionStep(
        index=index,
        skill_name=skill,
        title=title,
        objective=f"{title} 的目标",
        scope=f"{title} 的范围",
    )


class TestEventPayloadIndexing(unittest.TestCase):
    def test_index_segments_do_not_collide(self) -> None:
        self.assertEqual(PLANNING_THINKING_INDEX, 0)
        self.assertEqual(PLANNING_SUMMARY_TEXT_INDEX, 1)
        self.assertEqual(tool_use_index_for_step(1), 110)
        self.assertEqual(text_index_for_step(1), 111)
        self.assertEqual(tool_use_index_for_step(2), 120)
        self.assertEqual(text_index_for_step(2), 121)
        # 不与规划区间冲突
        self.assertGreater(tool_use_index_for_step(0), PLANNING_SUMMARY_TEXT_INDEX)

    def test_display_text_for_step_running_and_done(self) -> None:
        step = _make_step(1, "retrieval", "政策依据检索")
        self.assertIn("检索", display_text_for_step(step, phase="running"))
        self.assertIn("政策依据检索", display_text_for_step(step, phase="running"))
        done = display_text_for_step(step, phase="done")
        self.assertIn(done_label_for_skill("retrieval"), done)

    def test_purpose_mapping(self) -> None:
        self.assertEqual(purpose_for_skill("writing"), "article_draft")
        self.assertEqual(purpose_for_skill("retrieval"), "retrieval_summary")
        self.assertEqual(purpose_for_skill("unknown_skill"), "assistant_reply")


class TestEventPayloadSlimming(unittest.TestCase):
    def test_tool_result_slim_drops_task_packet(self) -> None:
        full_payload = {
            "tool": "retrieval",
            "taskId": "t1",
            "skillName": "retrieval",
            "stepIndex": 1,
            "stepTitle": "检索",
            "displayText": "检索完成",
            "taskPacket": {"task_id": "t1", "huge": "x" * 5000},
            "normalizedResult": {
                "items": [
                    {"title": f"item-{i}", "summary": "y" * 500} for i in range(20)
                ],
                "source": "legacy_success",
            },
            "retryable": False,
            "sourceState": "legacy_success",
            "errorDetail": None,
        }
        slim = slim_payload("tool_result", full_payload)
        self.assertNotIn("taskPacket", slim)
        self.assertEqual(slim["skillName"], "retrieval")
        self.assertEqual(slim["normalizedResult"]["itemsTotal"], 20)
        self.assertLessEqual(len(slim["normalizedResult"]["items"]), 5)

    def test_content_block_stop_payload_slims_like_tool_result(self) -> None:
        full_payload = {
            "tool": "retrieval",
            "taskId": "t1",
            "skillName": "retrieval",
            "stepIndex": 1,
            "stepTitle": "资料检索",
            "displayText": "检索完成",
            "normalizedResult": {
                "items": [{"title": f"item-{i}", "description": "y" * 500} for i in range(20)],
                "source": "legacy_success",
            },
            "retryable": False,
            "sourceState": "legacy_success",
            "errorDetail": None,
        }
        slim = slim_payload("content_block_stop", full_payload)
        self.assertEqual(slim["skillName"], "retrieval")
        self.assertEqual(slim["normalizedResult"]["itemsTotal"], 20)
        self.assertLessEqual(len(slim["normalizedResult"]["items"]), 5)

    def test_message_start_slim_picks_task_id_from_packet(self) -> None:
        payload = {"taskPacket": {"task_id": "abc", "skill_name": "writing"}}
        slim = slim_payload("message_start", payload)
        self.assertEqual(slim.get("taskId"), "abc")
        self.assertEqual(slim.get("requestedSkill"), "writing")
        self.assertNotIn("taskPacket", slim)

    def test_content_block_slim_keeps_metadata(self) -> None:
        block = {
            "type": "tool_use",
            "name": "writing",
            "skillName": "writing",
            "stepIndex": 2,
            "stepTitle": "公文写作",
            "displayText": "正在起草 公文写作",
            "extra": "drop_me",
        }
        slim = slim_content_block("content_block_start", block)
        self.assertIn("displayText", slim)
        self.assertIn("stepIndex", slim)
        self.assertNotIn("extra", slim)

    def test_delta_slim_trims_partial_json(self) -> None:
        delta = {"type": "input_json_delta", "partial_json": "a" * 6000, "extra": "drop"}
        slim = slim_delta("content_block_delta", delta)
        self.assertNotIn("extra", slim)
        self.assertLessEqual(len(slim["partial_json"]), 4100)
        self.assertTrue(slim["partial_json"].endswith("…"))

    def test_message_delta_keeps_only_stop_reason(self) -> None:
        slim = slim_payload("message_delta", {"delta": {"stop_reason": "end_turn", "extra": "drop"}})
        self.assertEqual(slim["delta"], {"stop_reason": "end_turn"})

    def test_error_payload_keeps_traceback_when_provided(self) -> None:
        slim = slim_payload(
            "error",
            {"errorDetail": "boom", "assistantMessageId": "m", "traceback": "tb", "extra": "drop"},
        )
        self.assertEqual(slim.get("traceback"), "tb")
        self.assertNotIn("extra", slim)


class TestHandoffContent(unittest.TestCase):
    def test_retrieval_summary_text_passed_as_full_background(self) -> None:
        result = {
            "items": [{"title": "t1", "summary": "s1"}],
            "summary_text": "## 关键结论\n- 结论1：xxx\n- 结论2：yyy\n",
            "source": "model_success",
        }
        out = build_handoff_content("原始请求", "retrieval", result)
        self.assertIn("整段背景资料", out)
        self.assertIn("关键结论", out)
        self.assertIn("结论1", out)

    def test_retrieval_items_fallback_when_no_summary_text(self) -> None:
        result = {
            "items": [
                {"title": "政策A", "summary": "要点A"},
                {"title": "政策B", "summary": "要点B"},
            ],
            "source": "legacy_success",
        }
        out = build_handoff_content("原始请求", "retrieval", result)
        self.assertIn("参考资料要点", out)
        self.assertIn("政策A", out)
        self.assertIn("不要再额外检索", out)

    def test_retrieval_clarification_preserved(self) -> None:
        result = {"user_clarification": "重点关注基层治理", "question": "希望侧重哪方面？"}
        out = build_handoff_content("原始请求", "retrieval", result)
        self.assertIn("用户补充信息", out)
        self.assertIn("重点关注基层治理", out)

    def test_writing_passes_document(self) -> None:
        result = {"document": "这是公文正文"}
        out = build_handoff_content("旧", "writing", result)
        self.assertEqual(out, "这是公文正文")


class TestSyntheticText(unittest.TestCase):
    def _skill_result(self, **kwargs) -> SkillExecutionResult:
        defaults = {
            "normalized_result": {},
            "render_blocks": [],
            "artifact_refs": [],
            "editor_annotations": [],
            "retryable": False,
        }
        defaults.update(kwargs)
        return SkillExecutionResult(**defaults)

    def test_writing_legacy_uses_document(self) -> None:
        sr = self._skill_result(normalized_result={"document": "公文草稿"})
        self.assertEqual(_extract_synthetic_text("writing", sr), "公文草稿")

    def test_retrieval_legacy_joins_items(self) -> None:
        sr = self._skill_result(
            normalized_result={
                "items": [
                    {"title": "政策A", "summary": "要点A"},
                    {"title": "政策B"},
                ]
            }
        )
        text = _extract_synthetic_text("retrieval", sr)
        self.assertIn("政策A", text)
        self.assertIn("要点A", text)
        self.assertIn("政策B", text)

    def test_fallback_to_render_block_html(self) -> None:
        sr = self._skill_result(
            render_blocks=[{"type": "review", "title": "t", "html": "<p>审核结论</p>"}],
            normalized_result={"issues": []},
        )
        self.assertIn("审核结论", _extract_synthetic_text("review", sr))

    def test_empty_when_nothing_available(self) -> None:
        sr = self._skill_result()
        self.assertEqual(_extract_synthetic_text("review", sr), "")


class TestWritingDetectionAndNormalization(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = MainAgent()

    def test_new_triggers_expand(self) -> None:
        samples = [
            "拟一份关于基层治理的调研报告",
            "帮我生成一篇工作汇报",
            "起草倡议书",
            "写个实施方案",
            "帮我准备一篇关于题目工作报告的正式文稿",
            "我准备一份工作总结，数据和案例要写实",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertTrue(self.agent._looks_like_writing_request(text))

    def test_pure_search_not_detected_as_writing(self) -> None:
        self.assertFalse(self.agent._looks_like_writing_request("帮我查一下端午节放假安排"))

    def test_normalize_appends_writing_after_retrieval(self) -> None:
        retrieval_step = _make_step(1, "retrieval", "资料检索")
        normalized, meta = self.agent._normalize_document_steps(
            "帮我拟一份端午节放假通知",
            [retrieval_step],
        )
        self.assertEqual([s.skill_name for s in normalized], ["retrieval", "writing"])
        self.assertEqual(normalized[-1].depends_on, ["step_01_retrieval"])
        self.assertIsNotNone(meta)

    def test_normalize_appends_writing_when_user_says_prepare_not_write(self) -> None:
        """模型只下发 retrieval 时，用户用「准备一篇…报告/正式文稿」也应触发补全 writing。"""
        retrieval_step = _make_step(1, "retrieval", "资料检索")
        normalized, meta = self.agent._normalize_document_steps(
            "帮我准备一篇关于大数据局工作报告的正式文稿",
            [retrieval_step],
        )
        self.assertEqual([s.skill_name for s in normalized], ["retrieval", "writing"])
        self.assertIsNotNone(meta)

    def test_normalize_noop_when_writing_already_present(self) -> None:
        steps = [_make_step(1, "retrieval", "r"), _make_step(2, "writing", "w")]
        normalized, meta = self.agent._normalize_document_steps("帮我拟通知", steps)
        self.assertEqual(len(normalized), 2)
        self.assertIsNone(meta)

    def test_normalize_noop_when_pure_search_request(self) -> None:
        steps = [_make_step(1, "retrieval", "r")]
        normalized, meta = self.agent._normalize_document_steps("查一下端午放假安排", steps)
        self.assertEqual(len(normalized), 1)
        self.assertIsNone(meta)


if __name__ == "__main__":
    unittest.main()
