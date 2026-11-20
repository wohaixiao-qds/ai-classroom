"""跨领域大纲不强套 Agent 规则,知识库测试只写临时目录。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.agent import research
from app.core.config import settings
from app.services import vault_sync


class OutlineDomainTests(unittest.TestCase):
    def test_domain_prompt_keeps_general_goals_and_conditional_model_analysis(self) -> None:
        for topic in ("条件概率", "中国近代史", "Agent Harness"):
            prompt = research._FRAMEWORK_PROMPT.format(topic=topic)
            self.assertIn(f"主题:{topic}", prompt)
            self.assertIn("理解障碍", prompt)
            self.assertIn("仅当主题本身属于 LLM/Agent 工程", prompt)
            self.assertNotIn("归约不进去的课,不值得单独存在", prompt)
            self.assertIn("goal", prompt)
            self.assertIn("prereqs", prompt)

    def test_search_does_not_silently_filter_classic_sources_to_one_year(self) -> None:
        with patch("app.agent.tools.web_search_multi", return_value="资料") as search:
            research._execute("web_search", {"query": "条件概率 教材"})
            self.assertEqual(search.call_args.args, ("条件概率 教材", None))
            research._execute("web_search", {"query": "最新规范", "recency": "week"})
            self.assertEqual(search.call_args.args, ("最新规范", "week"))

    def test_new_domain_uses_own_directory_and_legacy_bindings_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(settings, "kb_dir", Path(tmp)):
            agent = Path(tmp) / "Agent"
            agent.mkdir()
            old = agent / "03-RAG"
            old.mkdir()
            math: dict[str, Any] = {"domain": "数学", "topic": "条件概率", "courses": []}
            self.assertEqual(vault_sync._domain_base(math), Path(tmp) / "数学")
            self.assertEqual(vault_sync._domain_base({"domain": "RAG 工程", "theme_dir": "03-RAG"}),
                             agent)
            self.assertEqual(vault_sync._domain_base({
                "topic": "RAG 检索增强", "domain": "RAG 工程",
            }), agent)
            theme = vault_sync._create_theme_dir(math, "条件概率")
            assert theme is not None
            math["courses"] = [{"id": "c1", "title": "条件概率", "goal": "计算条件概率",
                                "why": "区分条件方向", "part": "基础"}]
            with patch.object(vault_sync, "_course_published", return_value=False):
                vault_sync._write_outline_doc(math, theme)
                vault_sync._outline_stub(math, theme)
            text = (theme / "大纲.md").read_text()
            self.assertIn("学习动机:区分条件方向", text)
            self.assertNotIn("弱点归因", text)
            stub = (theme / "00-条件概率导览.md").read_text()
            self.assertIn("[[00-数学导览]]", stub)
            self.assertNotIn("[[00-Agent导览]]", stub)


if __name__ == "__main__":
    unittest.main()
