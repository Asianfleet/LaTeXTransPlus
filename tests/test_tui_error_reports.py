import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.tui import error_reports
from src.tui.state import ProjectViewState


class TuiErrorReportsTests(unittest.TestCase):
    """验证错误报告数据处理从 App 迁移后保持既有语义。"""

    def test_merge_retains_final_and_resolved_initial_rows(self) -> None:
        """最终报告优先，同位置初始记录不重复。"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = [
                {"part": "sec", "num_or_ph": "1", "error": "old"},
                {"part": "cap", "num_or_ph": "2", "error": "fixed"},
            ]
            final = [{"part": "sec", "num_or_ph": "1", "error": "current"}]
            path = root / "errors_report.json"
            path.write_text(json.dumps(final), encoding="utf-8")
            (root / "initial_errors_report.json").write_text(
                json.dumps(initial),
                encoding="utf-8",
            )
            project = ProjectViewState(project_name="paper", output_dir=str(root))

            resolved_path = error_reports.project_errors_report_path(project)

            self.assertEqual(resolved_path, path)
            self.assertIsNone(project.errors_report_path)
            self.assertEqual(
                error_reports.error_reports_with_status(project, resolved_path),
                [(final[0], "unresolved"), (initial[1], "resolved")],
            )

    def test_project_report_path_prefers_existing_explicit_path(self) -> None:
        """显式报告存在时优先使用，失效时再从输出目录发现。"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            explicit = root / "explicit.json"
            fallback = root / "output" / "errors_report.json"
            fallback.parent.mkdir()
            explicit.write_text("[]", encoding="utf-8")
            fallback.write_text("[]", encoding="utf-8")
            project = ProjectViewState(
                project_name="paper",
                errors_report_path=str(explicit),
                output_dir=str(fallback.parent),
            )

            self.assertEqual(error_reports.project_errors_report_path(project), explicit)
            explicit.unlink()
            self.assertEqual(error_reports.project_errors_report_path(project), fallback)
            self.assertEqual(project.errors_report_path, str(explicit))

    def test_empty_reports_fall_back_to_project_failures(self) -> None:
        """无有效报告时依次展示项目错误、PDF 警告或空结果。"""
        project_error = ProjectViewState(project_name="paper", error="compile failed", pdf_error="pdf failed")
        pdf_error = ProjectViewState(project_name="paper", pdf_error="pdf failed")
        clean = ProjectViewState(project_name="paper")

        self.assertEqual(
            error_reports.error_reports_with_status(project_error, None),
            [({"part": "project", "num_or_ph": "-", "error": "compile failed"}, "unresolved")],
        )
        self.assertEqual(
            error_reports.error_reports_with_status(pdf_error, None),
            [({"part": "project", "num_or_ph": "-", "error": "pdf failed"}, "warning")],
        )
        self.assertEqual(error_reports.error_reports_with_status(clean, None), [])

    def test_read_error_report_tolerates_invalid_inputs(self) -> None:
        """报告读取忽略缺失、空白、损坏、非列表和非对象元素。"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "report.json"
            self.assertEqual(error_reports.read_error_report(None), [])
            self.assertEqual(error_reports.read_error_report(str(path)), [])

            for invalid_content in ("", "{broken", '{"part": "sec"}'):
                path.write_text(invalid_content, encoding="utf-8")
                self.assertEqual(error_reports.read_error_report(str(path)), [])

            record = {"part": "sec", "num_or_ph": "1"}
            path.write_text(json.dumps([record, "bad", 3, None]), encoding="utf-8")
            self.assertEqual(error_reports.read_error_report(str(path)), [record])

    def test_report_path_key_and_position_helpers_preserve_display_text(self) -> None:
        """初始报告路径、稳定键和位置文字保持既有格式。"""
        self.assertIsNone(error_reports.initial_error_report_path(None))
        self.assertEqual(
            error_reports.initial_error_report_path(r"D:\out\errors_report.json"),
            Path(r"D:\out\errors_report.json").parent / "initial_errors_report.json",
        )
        self.assertEqual(error_reports.error_report_key({"part": "sec", "num_or_ph": 2}), ("sec", "2"))
        self.assertEqual(error_reports.error_report_position({"part": "sec", "num_or_ph": "1"}), "章节 1")
        self.assertEqual(error_reports.error_report_position({"part": "cap", "num_or_ph": "2"}), "图题 2")
        self.assertEqual(error_reports.error_report_position({"part": "env"}), "环境 -")
        self.assertEqual(error_reports.error_report_position({}), "项目 -")

    def test_issue_and_legacy_fields_preserve_type_and_problem_order(self) -> None:
        """新旧 issue 字段按原顺序去重类型并拼接问题说明。"""
        report = {
            "issues": [
                {"type": "command_mismatch", "message": "new command"},
                {"type": "custom", "message": "custom problem"},
                "bad",
            ],
            "command_error": "old command",
            "ph_error": "old placeholder",
            "bracket_error": "old bracket",
            "error": "general",
        }

        self.assertEqual(error_reports.error_report_type(report), "命令、custom、占位符、括号")
        self.assertEqual(
            error_reports.error_report_problem(report),
            "new command\ncustom problem\nold command\nold placeholder\nold bracket\ngeneral",
        )
        self.assertEqual(error_reports.error_report_type({}), "项目")
        self.assertEqual(error_reports.error_report_problem({}), "")

    def test_error_report_content_reads_all_three_map_types(self) -> None:
        """章节、图题和环境错误都能反查对应原文与译文。"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            map_data = {
                "sections_map.json": [{"section": "1", "content": "section source", "trans_content": "章节译文"}],
                "captions_map.json": [{"placeholder": "CAP1", "content": "caption source", "trans_content": "图题译文"}],
                "envs_map.json": [{"placeholder": "ENV1", "content": "env source", "trans_content": "环境译文"}],
            }
            for filename, records in map_data.items():
                (root / filename).write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            project = ProjectViewState(project_name="paper", output_dir=str(root))

            self.assertEqual(
                error_reports.error_report_content({"part": "sec", "num_or_ph": "1"}, project),
                ("section source", "章节译文"),
            )
            self.assertEqual(
                error_reports.error_report_content({"part": "cap", "num_or_ph": "CAP1"}, project),
                ("caption source", "图题译文"),
            )
            self.assertEqual(
                error_reports.error_report_content({"part": "env", "num_or_ph": "ENV1"}, project),
                ("env source", "环境译文"),
            )
            self.assertEqual(error_reports.error_report_content({"part": "project"}, project), ("", ""))

    def test_content_root_and_map_reader_tolerate_invalid_data(self) -> None:
        """内容目录选择稳定，map 读取忽略异常格式和非对象元素。"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "reports" / "errors_report.json"
            project = ProjectViewState(
                project_name="paper",
                errors_report_path=str(report_path),
                output_dir=str(root / "output"),
            )
            self.assertEqual(error_reports.error_content_root(project), report_path.parent)
            self.assertIsNone(error_reports.error_content_root(ProjectViewState(project_name="empty")))

            map_path = root / "sections_map.json"
            self.assertEqual(error_reports.read_json_list(map_path), [])
            for invalid_content in ("", "[broken", '{"section": "1"}'):
                map_path.write_text(invalid_content, encoding="utf-8")
                self.assertEqual(error_reports.read_json_list(map_path), [])

            record = {"section": "1", "content": "source"}
            map_path.write_text(json.dumps([record, "bad", None]), encoding="utf-8")
            self.assertEqual(error_reports.read_json_list(map_path), [record])
            self.assertEqual(error_reports.find_error_part_record(root, "sec", "1"), record)
            self.assertIsNone(error_reports.find_error_part_record(root, "sec", "2"))
            self.assertIsNone(error_reports.find_error_part_record(root, "unknown", "1"))


if __name__ == "__main__":
    unittest.main()
