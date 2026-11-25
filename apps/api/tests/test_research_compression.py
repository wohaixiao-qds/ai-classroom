"""T2.5 历史压缩 + T2.6 本地快照回读的隔离回归(临时目录,不碰真实数据)。

覆盖:压缩触发(输入体积优先+轮数辅助)、压缩形状(首条 prompt 与最后一轮
完整交互原样保留)、摘要保留清单(约束原文/门禁反馈/候选要点+quote+快照定位、
「引文命中」与「语义审查」分开标记)、read_snapshot 回读(绝不联网)。
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from app.agent import research
from app.agent.tools import read_snapshot, set_snapshot_checkpoint
from app.core.config import settings


class ResearchCompressionTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        self.data_dir.mkdir()
        traces_dir = Path(tmp.name) / "traces"
        traces_dir.mkdir()
        for name, value in (("data_dir", self.data_dir), ("traces_dir", traces_dir)):
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        set_snapshot_checkpoint(None)
        self.addCleanup(set_snapshot_checkpoint, None)

    # ---------- T2.5 压缩形状 ----------

    def test_compress_messages_keeps_head_and_last_round(self) -> None:
        head = {"role": "user", "content": "prompt with goal"}
        messages: list[dict[str, Any]] = [
            head,
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1"}]},
            {"role": "user",
             "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "a"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t2"}]},
            {"role": "user",
             "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "b"}]},
        ]
        compressed = research._compress_messages(
            messages, research_context=None, successful_fetches={},
            tool_calls=[], phase="material:x",
        )
        assert compressed is not None
        self.assertEqual(len(compressed), 4)
        self.assertEqual(compressed[0], head)  # 首条 prompt 原样
        self.assertTrue(compressed[1]["content"].startswith(research._DIGEST_MARKER))
        self.assertEqual(compressed[2], messages[-2])  # 最后一轮完整交互原样
        self.assertEqual(compressed[3], messages[-1])
        # tool_result 引用的 tool_use 同历史存活(单留一半会被 API 拒)
        self.assertEqual(compressed[2]["content"][0]["id"], "t2")
        self.assertEqual(compressed[3]["content"][0]["tool_use_id"], "t2")
        # 历史太短(没有可压缩的中间历史)不压缩
        self.assertIsNone(research._compress_messages(
            messages[:3], research_context=None, successful_fetches={},
            tool_calls=[], phase="material:x",
        ))
        self.assertIsNone(research._compress_messages(
            messages[:1], research_context=None, successful_fetches={},
            tool_calls=[], phase="material:x",
        ))

    # ---------- T2.5 摘要保留清单 ----------

    def test_digest_preserves_candidates_and_separate_status_markers(self) -> None:
        url = "https://docs.example.org/guide"
        sentence = "Authoritative sentence about harness boundaries. "
        body = f"[Guide | {url}]\n" + sentence * 10
        quote = sentence.strip()
        draft_text = json.dumps({
            "topic": "t", "subtopic": "s",
            "sources": [{"id": 1, "title": "Guide", "url": url}],
            "groups": [{"heading": "facts", "points": [
                {"text": "matched point", "source_id": 1, "quote": quote},
                {"text": "broken point", "source_id": 1,
                 "quote": "This quote never appears in the fetched body."},
            ]}],
        })
        middle = [
            {"role": "assistant", "content": draft_text},
            {"role": "user", "content":
                "交付物不合格,逐条修完重新输出完整 JSON:\n"
                "- 要点 g1p2 的 quote 不在来源[1]实际抓取正文中,不得翻译或改写摘录"},
        ]
        digest = research._build_history_digest(
            middle,
            research_context={"learning_goal": "能画出边界图",
                              "scope": {"讲": "边界", "不讲": "模型训练"}},
            successful_fetches={url: {"result": body, "call_index": 0}},
            tool_calls=[], phase="material:s",
        )
        self.assertIn("能画出边界图", digest)  # 课程 goal 原文
        self.assertIn("不讲", digest)  # scope 排除项原文
        self.assertIn("要点 g1p2 的 quote 不在来源[1]", digest)  # 门禁反馈原文
        self.assertIn("matched point", digest)
        self.assertIn(quote, digest)  # 逐字 quote 保留
        self.assertIn('"quote_status": "matched"', digest)
        self.assertIn('"quote_status": "unmatched"', digest)
        self.assertIn('"quote_start"', digest)  # 快照定位保留
        self.assertIn('"snapshot_sha256"', digest)
        self.assertIn('"semantic_review": "unreviewed"', digest)
        self.assertNotIn("已确认", digest)  # 引文命中与语义审查不得合并标记
        self.assertIn("read_snapshot", digest)
        self.assertIn("sha256", digest)
        self.assertIn(url, digest)

    def test_digest_for_framework_drafts(self) -> None:
        url = "https://lab.example.net/harness"
        sentence = "A harness wraps the model with tools and termination rules. "
        body = f"[Lab | {url}]\n" + sentence * 8
        quote = sentence.strip()
        draft_text = json.dumps({"topic": "t", "courses": [
            {"id": "c1", "title": "认识 harness", "goal": "能画出边界图",
             "scope": "讲边界不讲训练", "why": "把模型与系统混淆", "part": "起步",
             "prereqs": [],
             "source_quotes": [{"url": url, "quote": quote}]},
        ]})
        digest = research._build_history_digest(
            [{"role": "assistant", "content": draft_text}],
            research_context=None,
            successful_fetches={url: {"result": body, "call_index": 0}},
            tool_calls=[], phase="framework",
        )
        self.assertIn("认识 harness", digest)
        self.assertIn("能画出边界图", digest)
        self.assertIn(quote, digest)
        self.assertIn('"quote_status": "matched"', digest)
        self.assertIn("与语义审查相互独立", digest)  # 状态说明:引文命中≠语义审查

    def test_second_compression_ignores_prior_digest_as_feedback(self) -> None:
        middle = [
            {"role": "user", "content": research._DIGEST_MARKER + "旧的摘要"},
            {"role": "assistant", "content": "text"},
            {"role": "user", "content": "交付物不合格,逐条修完重新输出完整 JSON"},
        ]
        self.assertEqual(research._last_user_feedback(middle),
                         "交付物不合格,逐条修完重新输出完整 JSON")

    # ---------- T2.5 循环内端到端(压缩触发) ----------

    def test_loop_compresses_history_when_input_over_limit(self) -> None:
        url = "https://docs.example.org/guide"
        sentence = "Authoritative sentence about harness boundaries. "
        body = f"[Guide | {url}]\n" + sentence * 40
        quote = sentence.strip()
        delivery = json.dumps({
            "topic": "t", "subtopic": "s",
            "sources": [{"id": 1, "title": "Guide", "url": url}],
            "groups": [{"heading": "facts", "points": [
                {"text": f"point {i}", "source_id": 1, "quote": quote}
                for i in range(30)
            ]}],
        })

        def tool_resp(i: int) -> SimpleNamespace:
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", name="fetch_page",
                                         id=f"call-{i}", input={"url": url})],
                stop_reason="tool_use",
                usage=SimpleNamespace(input_tokens=10, output_tokens=2))

        responses: list[SimpleNamespace] = [
            tool_resp(0),
            SimpleNamespace(
                content=[SimpleNamespace(type="text", text="让我再抓一次确认细节。")],
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=10, output_tokens=2)),
            tool_resp(1),
            tool_resp(2),
            SimpleNamespace(
                content=[SimpleNamespace(type="text", text=delivery)],
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=10, output_tokens=2)),
        ]
        client = SimpleNamespace()
        client.with_options = lambda **_: client
        # _loop 复用同一个 messages 列表对象并原地 append;Mock 的 call_args 只存
        # 引用,必须逐次深拷贝快照才能断言「第 N 次调用时的历史」。
        seen: list[list[dict[str, Any]]] = []
        seen_tools: list[Any] = []

        def create(**kwargs: Any) -> SimpleNamespace:
            seen.append(copy.deepcopy(kwargs["messages"]))
            seen_tools.append(kwargs.get("tools"))
            return responses[len(seen) - 1]

        client.messages = SimpleNamespace(create=create)
        fetch = Mock(return_value=body)
        prompt = "MATERIAL PROMPT with course goal"
        with (patch.object(research, "get_llm_client", return_value=client),
              patch.object(research, "_COMPRESS_TOKENS_LIMIT", 500),
              patch.object(research, "_execute",
                           side_effect=lambda _name, args: fetch(args["url"])),
              patch.object(research, "trace_research"),
              patch.object(research, "_review_material")):
            result = research._loop(
                prompt, lambda _d, _f: [], "topic", "material:snap",
                material_filename="t.compress.material.json",
            )
        self.assertIn("groups", result)
        self.assertEqual(len(seen), 5)
        # 原料阶段装配 read_snapshot(框架阶段不装配)
        self.assertIs(seen_tools[0], research.MATERIAL_TOOLS)
        # 第 4 次模型调用(轮数≥4 且估算超限)拿到压缩后的历史
        compressed = seen[3]
        self.assertEqual(len(compressed), 4)
        self.assertEqual(compressed[0]["content"], prompt)
        summary = compressed[1]["content"]
        self.assertTrue(summary.startswith(research._DIGEST_MARKER))
        self.assertIn("未返回完整 JSON", summary)  # 门禁反馈原文进摘要
        self.assertIn("read_snapshot", summary)
        self.assertIn(url, summary)  # 已抓来源清单保留(含 sha)
        # 最后一轮完整交互保留且 tool_use/tool_result 配对完整
        self.assertEqual(compressed[2]["content"][0]["id"], "call-1")
        self.assertEqual(compressed[3]["content"][0]["tool_use_id"], "call-1")
        # 历史再次超限可重复压缩,数据源是循环级记录,配对仍完整
        again = seen[4]
        self.assertEqual(len(again), 4)
        self.assertEqual(again[2]["content"][0]["id"], "call-2")
        # 已抓正文持久化在检查点(历史剔除后仍可恢复/回读)
        cp = research._load_fetch_checkpoint("t.compress.material.json")
        assert cp is not None
        self.assertIn(url, cp["pages"])

    # ---------- T2.6 本地快照回读 ----------

    def test_read_snapshot_roundtrip_without_network(self) -> None:
        filename = "t.snap.material.json"
        url = "https://example.org/a"
        body = "正文A" * 200 + "\n" + "正文B" * 200
        research._save_fetch_checkpoint(filename, url, body, [], None)
        path = research._checkpoint_path(filename)
        set_snapshot_checkpoint(path)
        with patch.object(urllib.request, "urlopen",
                          side_effect=AssertionError("read_snapshot 绝不联网")):
            out = read_snapshot(url)
            self.assertTrue(out.startswith(f"[快照 {url} | 字符 0–"))
            self.assertIn("正文A", out)
            self.assertIn("正文B", out)
            # offset 翻页:标头带定位与总长
            total = len(body)
            mid = read_snapshot(url, offset=total - 10, length=4000)
            self.assertIn(f"字符 {total - 10}–{total} / 共 {total}", mid)
            self.assertNotIn("正文A", mid)
            # 越界 offset 给可读错误,不抛异常
            self.assertIn("超出", read_snapshot(url, offset=total + 5))
            # 未知 URL:列出已保存来源,不触网
            missing = read_snapshot("https://example.org/missing")
            self.assertIn("快照中没有该 URL", missing)
            self.assertIn(url, missing)
        # 损坏检查点:可读错误
        path.write_text("{ broken", encoding="utf-8")
        self.assertIn("读取失败", read_snapshot(url))
        # 未注入/清空:不可用
        set_snapshot_checkpoint(None)
        self.assertIn("快照不可用", read_snapshot(url))

    def test_read_snapshot_dispatch_and_catalog(self) -> None:
        self.assertNotIn("read_snapshot", [t["name"] for t in research.RESEARCH_TOOLS])
        self.assertEqual(
            [t["name"] for t in research.MATERIAL_TOOLS],
            [t["name"] for t in research.RESEARCH_TOOLS] + ["read_snapshot"],
        )
        desc = next(t for t in research.MATERIAL_TOOLS
                    if t["name"] == "read_snapshot")["description"]
        self.assertIn("正文已退出对话历史", desc)
        # dispatch 走注入的检查点,返回带 offset 标头的正文段落
        research._save_fetch_checkpoint(
            "t.dispatch.material.json", "https://example.org/x",
            "[T | https://example.org/x]\n" + "字 " * 500, [], None,
        )
        set_snapshot_checkpoint(research._checkpoint_path("t.dispatch.material.json"))
        out = research._execute(
            "read_snapshot", {"url": "https://example.org/x", "offset": 4})
        self.assertTrue(out.startswith("[快照 https://example.org/x | 字符 4–"))
        self.assertIn("字", out)
        # 框架阶段(未注入检查点)该工具不可用
        set_snapshot_checkpoint(None)
        self.assertIn("快照不可用", research._execute(
            "read_snapshot", {"url": "https://example.org/x"}))


if __name__ == "__main__":
    unittest.main()
