"""T4 答疑提示阶梯回归:档位计数(自上次 pass 的连续非 pass)→ 档位化引导注入,全离线。

替身边界沿 test_gaps 惯例:临时目录 SQLite/课件,traces 目录隔离,
模型入口 MagicMock(生成器在 context 事件后即弃,不会真调模型)。
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from app.agent import tutor
from app.core import learning_store
from app.core.config import settings


class HintLadderTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        stack.enter_context(tmp)
        for key in ("data_dir", "courses_dir", "traces_dir"):
            directory = Path(tmp.name) / key
            directory.mkdir()
            p = patch.object(settings, key, directory)
            p.start()
            stack.callback(p.stop)
        # learning_store 的库路径即 settings.data_dir/classroom.db(_conn 内现算),
        # 指到临时目录即可,无需再 patch 模块属性。

    # ---- 档位计数:自上次 pass 的连续非 pass ----

    def _grade(self, page: str, verdict: str, answer: str) -> None:
        learning_store.record_result("course", page, answer, {"verdict": verdict})

    def test_count_zero_without_grades(self) -> None:
        self.assertEqual(learning_store.consecutive_non_pass("course", "q1"), 0)

    def test_count_consecutive_fails(self) -> None:
        self._grade("q1", "fail", "一")
        self._grade("q1", "fail", "二")
        self.assertEqual(learning_store.consecutive_non_pass("course", "q1"), 2)

    def test_count_stops_at_newest_pass(self) -> None:
        self._grade("q1", "fail", "旧错")
        self._grade("q1", "pass", "后来过了")
        self.assertEqual(learning_store.consecutive_non_pass("course", "q1"), 0)

    def test_count_since_last_pass(self) -> None:
        self._grade("q1", "pass", "早前过")
        self._grade("q1", "fail", "错一")
        self._grade("q1", "fail", "错二")
        self.assertEqual(learning_store.consecutive_non_pass("course", "q1"), 2)

    def test_count_is_per_checkpoint(self) -> None:
        self._grade("q1", "fail", "q1 错")
        self._grade("q2", "fail", "q2 错")
        self.assertEqual(learning_store.consecutive_non_pass("course", "q1"), 1)
        self.assertEqual(learning_store.consecutive_non_pass("course", "q2"), 1)

    # ---- 档位化引导注入 ----

    def _first_user(self, hint_level: int, checkpoint: dict[str, Any] | None) -> str:
        stream = MagicMock()
        stream.__iter__.return_value = iter([
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="离线回答"),
            )
        ])
        stream.get_final_message.return_value = SimpleNamespace(
            stop_reason="end_turn", usage=SimpleNamespace()
        )
        client = MagicMock()
        client.messages.stream.return_value.__enter__.return_value = stream
        with (
            patch.object(tutor, "get_llm_client", return_value=client),
            patch.object(tutor, "build_system", return_value=[]),
            patch.object(tutor, "load_messages", return_value=[]),
            patch.object(tutor, "append_turn"),
        ):
            list(tutor.run_tutor(
                "帮我搞懂薄弱点", "模型底料", "s1",
                session_id="test-session", course_id="course",
                checkpoint=checkpoint, hint_level=hint_level,
            ))
        return str(client.messages.stream.call_args.kwargs["messages"][-1]["content"])

    _CHECKPOINT = {
        "question": "检查点问题", "pass_rule": "标准",
        "answer": "复述", "verdict": "fail",
    }

    def test_level1_keeps_guided_instruction(self) -> None:
        current = self._first_user(1, dict(self._CHECKPOINT))
        self.assertIn("引导式解答", current)
        self.assertIn("不要直接给完整标准答案", current)
        self.assertNotIn("半示范", current)
        self.assertNotIn("直接把概念讲透", current)

    def test_level2_half_demonstration(self) -> None:
        current = self._first_user(2, dict(self._CHECKPOINT))
        self.assertIn("半示范", current)
        self.assertIn("把它套回原问题", current)
        self.assertNotIn("引导式解答:先点破薄弱点", current)

    def test_level3_direct_explain_with_angle_switch(self) -> None:
        current = self._first_user(3, dict(self._CHECKPOINT))
        self.assertIn("直接把概念讲透", current)
        self.assertIn("换一个角度", current)
        self.assertIn("当场应用一次", current)

    def test_level_zero_clamps_to_l1(self) -> None:
        current = self._first_user(0, dict(self._CHECKPOINT))
        self.assertIn("引导式解答", current)

    def test_all_levels_share_escape_and_no_meta(self) -> None:
        for level in (1, 2, 3):
            with self.subTest(level=level):
                current = self._first_user(level, dict(self._CHECKPOINT))
                self.assertIn("「直接告诉我", current)  # 逃生门(措辞约定,零 UI)
                self.assertIn("自行加深", current)  # 会话内升级授权
                self.assertIn("不向学员提及提示档位", current)  # 防元话语

    def test_no_checkpoint_no_guidance_even_with_level(self) -> None:
        current = self._first_user(3, None)
        self.assertNotIn("检查点问题", current)
        self.assertNotIn("讲透", current)


if __name__ == "__main__":
    unittest.main()
