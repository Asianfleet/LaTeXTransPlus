"""验证 TUI 左侧项目列表的排序策略。"""

import unittest
from types import SimpleNamespace

from src.tui.project_list import (
    PROJECT_SORT_BY_CREATED_AT,
    PROJECT_SORT_BY_INITIAL,
    PROJECT_SORT_BY_TITLE,
    PROJECT_SORT_OPTIONS,
    _stat_creation_timestamp,
    sort_project_states,
)
from src.tui.state import ProjectViewState, TaskViewState


class ProjectListSortingTests(unittest.TestCase):
    """验证项目列表的三种稳定排序方式。"""

    def test_sort_options_expose_the_three_requested_modes(self):
        """三个控件选项分别对应首字符、标题和创建时间排序。"""
        self.assertEqual(
            [label for label, _ in PROJECT_SORT_OPTIONS],
            ["按首字符排序", "按标题排序", "按创建时间排序"],
        )

    def test_sort_by_initial_title_and_created_at(self):
        """三种模式分别按项目名首字符、标题和创建时间排序。"""
        older = TaskViewState(
            input_type="arxiv",
            inputs=["older"],
            task_id="20261001T120000.000",
        )
        older.projects.extend(
            [
                ProjectViewState(project_name="zeta", title="Alpha"),
                ProjectViewState(project_name="beta", title="Zulu"),
            ]
        )
        newer = TaskViewState(
            input_type="arxiv",
            inputs=["newer"],
            task_id="20261003T120000.000",
        )
        newer.projects.append(ProjectViewState(project_name="alpha", title="Middle"))
        rows = [(older, project) for project in older.projects]
        rows.append((newer, newer.projects[0]))

        self.assertEqual(
            [project.project_name for _, project in sort_project_states(rows, PROJECT_SORT_BY_INITIAL)],
            ["alpha", "beta", "zeta"],
        )
        self.assertEqual(
            [project.project_name for _, project in sort_project_states(rows, PROJECT_SORT_BY_TITLE)],
            ["zeta", "alpha", "beta"],
        )
        self.assertEqual(
            [project.project_name for _, project in sort_project_states(rows, PROJECT_SORT_BY_CREATED_AT, descending=True)],
            ["alpha", "zeta", "beta"],
        )

    def test_sort_directions_keep_equal_keys_stable_and_leave_input_unchanged(self):
        """方向切换反转排序键，同时保留相同创建时间项目的相对顺序。"""
        older = TaskViewState(input_type="arxiv", inputs=[], task_id="20261001T120000.000")
        newer = TaskViewState(input_type="arxiv", inputs=[], task_id="20261003T120000.000")
        rows = [
            (older, ProjectViewState(project_name="zeta", title="Alpha")),
            (older, ProjectViewState(project_name="beta", title="Zulu")),
            (newer, ProjectViewState(project_name="alpha", title="Middle")),
        ]
        original = list(rows)
        for mode, descending, expected in (
            (PROJECT_SORT_BY_CREATED_AT, False, ["zeta", "beta", "alpha"]),
            (PROJECT_SORT_BY_CREATED_AT, True, ["alpha", "zeta", "beta"]),
            (PROJECT_SORT_BY_INITIAL, True, ["zeta", "beta", "alpha"]),
            (PROJECT_SORT_BY_TITLE, True, ["beta", "alpha", "zeta"]),
        ):
            with self.subTest(mode=mode, descending=descending):
                ordered = sort_project_states(rows, mode, descending=descending)
                self.assertEqual([project.project_name for _, project in ordered], expected)
                self.assertEqual(rows, original)

    def test_equal_sort_keys_preserve_input_order(self):
        """相同首字符或标题时保持项目原有顺序。"""
        task = TaskViewState(input_type="arxiv", inputs=["task"], task_id="task")
        task.projects.extend(
            [
                ProjectViewState(project_name="zeta", title="Same"),
                ProjectViewState(project_name="zebra", title="Same"),
            ]
        )
        rows = [(task, project) for project in task.projects]

        for mode in (PROJECT_SORT_BY_INITIAL, PROJECT_SORT_BY_TITLE):
            with self.subTest(mode=mode):
                self.assertEqual(sort_project_states(rows, mode), rows)

    def test_creation_time_stat_fallback_is_platform_aware(self):
        """优先使用 birth time，且仅在 Windows 将 st_ctime 作为创建时间。"""
        creation_stat = SimpleNamespace(st_ctime=200.0, st_birthtime=100.0)
        legacy_stat = SimpleNamespace(st_ctime=200.0)

        self.assertEqual(_stat_creation_timestamp(creation_stat, "posix"), 100.0)
        self.assertEqual(_stat_creation_timestamp(legacy_stat, "nt"), 200.0)
        self.assertEqual(_stat_creation_timestamp(legacy_stat, "posix"), float("-inf"))

    def test_missing_title_and_unparseable_time_keep_sorting_safe_and_stable(self):
        """缺失标题或时间戳时仍可排序，无法解析的时间保持原顺序。"""
        first = TaskViewState(input_type="arxiv", inputs=["first"], task_id="legacy-a")
        second = TaskViewState(input_type="arxiv", inputs=["second"], task_id="legacy-b")
        rows = [
            (first, ProjectViewState(project_name="same", title="")),
            (second, ProjectViewState(project_name="same", title="")),
        ]

        self.assertIs(
            sort_project_states(rows, PROJECT_SORT_BY_CREATED_AT)[0][0],
            first,
        )
        self.assertEqual(
            [project.title for _, project in sort_project_states(rows, PROJECT_SORT_BY_TITLE)],
            ["", ""],
        )


if __name__ == "__main__":
    unittest.main()
