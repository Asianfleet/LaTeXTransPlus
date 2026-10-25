"""验证翻译模式对内置术语来源和回退行为的约束。"""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

from src.agents.tool_agents.translator_agent import TranslatorAgent


class TranslatorBuiltinTermsTests(unittest.TestCase):
    """覆盖分类加载、默认词表回退及其他术语来源的保留。"""

    def _make_agent(self, category=None, mode="plain", **config):
        """创建无需真实 LLM 配置的术语加载测试实例。"""
        return TranslatorAgent(
            config={
                "source_language": "en",
                "target_language": "ch",
                "llm_config": {},
                "category": category,
                **config,
            },
            trans_mode=mode,
            project_dir="paper",
        )

    def test_plain_without_current_project_categories_loads_no_builtin_terms(self):
        """空分类及仅其他项目的分类均不能触发默认词表加载。"""
        for category in (None, {}, {"paper": []}, {"other": ["cs.AI"]}):
            with self.subTest(category=category):
                agent = self._make_agent(category)
                with patch.object(agent, "_load_default_terms_file", return_value={"Default": "默认"}), patch(
                    "src.agents.tool_agents.translator_agent.pd.read_csv"
                ) as read_csv:
                    agent.build_term_dict()
                self.assertEqual(agent.term_dict, {})
                read_csv.assert_not_called()

    def test_plain_loads_only_listed_category_files(self):
        """多分类仅合并指定文件，缺失分类文件不影响其他分类。"""
        agent = self._make_agent({"paper": ["cs.AI", "missing", "cs.LG"]})
        with patch(
            "src.agents.tool_agents.translator_agent.pd.read_csv",
            side_effect=[
                {"Source Term": ["Graph"], "Target Translation": ["图"]},
                FileNotFoundError(),
                {"Source Term": ["Token"], "Target Translation": ["词元"]},
            ],
        ) as read_csv, patch.object(agent, "_load_default_terms_file") as fallback:
            agent.build_term_dict()
        self.assertEqual(agent.term_dict, {"Graph": "图", "Token": "词元"})
        self.assertEqual(read_csv.call_args_list, [
            call(os.path.join("terms", name + ".csv"), header=None, names=["Source Term", "Target Translation"])
            for name in ("cs.AI", "missing", "cs.LG")
        ])
        fallback.assert_not_called()

    def test_plain_missing_category_file_does_not_fall_back(self):
        """指定分类全部缺失时，plain 仍不加载默认词表。"""
        agent = self._make_agent({"paper": ["missing"]})
        with patch(
            "src.agents.tool_agents.translator_agent.pd.read_csv", side_effect=FileNotFoundError
        ), patch.object(agent, "_load_default_terms_file", return_value={"Default": "默认"}):
            agent.build_term_dict()
        self.assertEqual(agent.term_dict, {})

    def test_terms_mode_preserves_default_fallback(self):
        """terms 模式继续在空分类或分类文件全部缺失时回退。"""
        for category in ({}, {"paper": ["missing"]}):
            with self.subTest(category=category):
                agent = self._make_agent(category, mode="terms")
                with patch(
                    "src.agents.tool_agents.translator_agent.pd.read_csv", side_effect=FileNotFoundError
                ), patch.object(agent, "_load_default_terms_file", return_value={"Default": "默认"}):
                    agent.build_term_dict()
                self.assertEqual(agent.term_dict, {"Default": "默认"})

    def test_plain_empty_categories_preserve_user_project_and_placeholder_terms(self):
        """禁用内置词表时仍保留用户、项目和占位符，并维持覆盖优先级。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            user_file = root / "user.csv"
            user_file.write_text("Graph,用户图\n", encoding="utf-8")
            (root / "project_terms.csv").write_text("Graph,项目图\nToken,词元\n", encoding="utf-8")
            agent = self._make_agent({}, user_term=str(user_file))
            agent.output_dir = str(root)
            agent.term_dict = {"<PLACEHOLDER_ENV_1>": "<PLACEHOLDER_ENV_1>"}
            with patch.object(agent, "_load_default_terms_file", return_value={"Default": "默认"}):
                agent.build_term_dict()
        self.assertEqual(agent.term_dict, {
            "<PLACEHOLDER_ENV_1>": "<PLACEHOLDER_ENV_1>", "Graph": "用户图", "Token": "词元",
        })
        self.assertTrue(agent._should_use_terms_prompt())

    def test_other_language_pairs_do_not_load_english_chinese_categories(self):
        """指定分类也不能把英中内置词表引入其他语言对。"""
        agent = self._make_agent({"paper": ["cs.AI"]}, source_language="de", target_language="jp")
        with patch("src.agents.tool_agents.translator_agent.pd.read_csv") as read_csv:
            agent.build_term_dict()
        self.assertEqual(agent.term_dict, {})
        read_csv.assert_not_called()


class RuntimeCategoryTests(unittest.TestCase):
    """验证 arXiv 准备阶段遵守 plain 模式的显式分类配置。"""

    def test_plain_arxiv_preserves_configured_categories(self):
        """空分类和手工分类均不能在 plain 模式下被自动分类覆盖。"""
        from src.runtime import prepare_projects

        for mode in (None, "plain"):
            for category in (None, {}, {"2507.02199": ["cs.LG"]}):
                for callback in (None, unittest.mock.Mock()):
                    with self.subTest(mode=mode, category=category, callback=callback is not None):
                        with tempfile.TemporaryDirectory() as tmp_dir:
                            config = {
                                "paper_list": ["2507.02199"],
                                "tex_sources_dir": str(Path(tmp_dir) / "sources"),
                                "output_dir": str(Path(tmp_dir) / "output"),
                            }
                            if mode is not None:
                                config["mode"] = mode
                            if category is not None:
                                config["category"] = category
                            with patch("src.runtime.batch_download_arxiv_tex", return_value=["paper"]), patch(
                                "src.runtime.extract_compressed_files"
                            ), patch("src.runtime.get_arxiv_category", return_value={"2507.02199": ["cs.AI"]}) as fetch:
                                _, effective_config, _, _ = prepare_projects(config, prepare_log_callback=callback)
                            self.assertEqual(effective_config.get("category", {}), category or {})
                            fetch.assert_not_called()

    def test_terms_arxiv_preserves_automatic_category_discovery(self):
        """terms 模式继续自动获取 arXiv 分类，并支持准备日志回调。"""
        from src.runtime import prepare_projects

        for callback in (None, unittest.mock.Mock()):
            with self.subTest(callback=callback is not None):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    config = {
                        "mode": "terms",
                        "paper_list": ["2507.02199"],
                        "tex_sources_dir": str(Path(tmp_dir) / "sources"),
                        "output_dir": str(Path(tmp_dir) / "output"),
                    }
                    categories = {"2507.02199": ["cs.AI"]}
                    with patch("src.runtime.batch_download_arxiv_tex", return_value=["paper"]), patch(
                        "src.runtime.extract_compressed_files"
                    ), patch("src.runtime.get_arxiv_category", return_value=categories) as fetch:
                        _, effective_config, _, _ = prepare_projects(config, prepare_log_callback=callback)
                    self.assertEqual(effective_config["category"], categories)
                    fetch.assert_called_once()
