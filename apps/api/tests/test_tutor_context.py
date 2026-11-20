"""答疑上下文组合回归:跑真实循环,只替换模型与持久化边界。"""

import itertools
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agent import tutor


class TutorContextTests(unittest.TestCase):
    def test_optional_contexts_survive_all_combinations(self) -> None:
        question = "请帮我解释这两个机制的关系"
        checkpoint = {
            "question": "检查点问题",
            "pass_rule": "能说明各自职责",
            "answer": "我的复述",
            "verdict": "fail",
        }
        history = [
            {"role": "user", "content": "历史问题"},
            {"role": "assistant", "content": "历史回答"},
        ]
        for has_page, has_checkpoint, has_mastered, has_state in itertools.product(
            (False, True), repeat=4
        ):
            with self.subTest(
                page=has_page, checkpoint=has_checkpoint, mastered=has_mastered, state=has_state
            ):
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
                    patch.object(tutor, "load_messages", return_value=history),
                    patch.object(tutor, "append_turn") as append,
                ):
                    events = list(tutor.run_tutor(
                        question,
                        "模型底料",
                        "s2" if has_page else None,
                        session_id="test-session",
                        course_id="test-course",
                        checkpoint=checkpoint if has_checkpoint else None,
                        mastered_terms=["已学概念甲", "已学概念乙"] if has_mastered else None,
                        state_note="进度增量:刚通过检查点" if has_state else None,
                    ))
                messages = client.messages.stream.call_args.kwargs["messages"]
                current = messages[-1]["content"]
                self.assertEqual(messages[:-1], history)
                self.assertEqual(current.count(question), 1)
                self.assertTrue(current.endswith(question))
                self.assertEqual("第「s2」页" in current, has_page)
                self.assertEqual("已学概念甲/已学概念乙" in current, has_mastered)
                self.assertEqual("进度增量:刚通过检查点" in current, has_state)
                self.assertEqual("不要直接给完整标准答案" in current, has_checkpoint)
                for value in checkpoint.values():
                    self.assertEqual(value in current, has_checkpoint)
                if not any((has_page, has_checkpoint, has_mastered, has_state)):
                    self.assertEqual(current, question)
                self.assertEqual(events[-1]["answer"], "离线回答")
                # 存储的用户原话不掺入内部上下文,历史消息也不会被回改。
                self.assertEqual(append.call_args_list[0].args[3], question)


if __name__ == "__main__":
    unittest.main()
