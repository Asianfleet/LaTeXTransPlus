import unittest

from src.tui import app, widgets


class TuiWidgetsTests(unittest.TestCase):
    """验证控件迁移后的导出身份与响应式标题。"""

    def test_app_reexports_original_objects(self) -> None:
        """调用方应获得同一类和函数而不是复制实现。"""
        names = (
            "APP_TITLE_PLAIN",
            "APP_TITLE_ART",
            "APP_TITLE_ART_COMPACT",
            "APP_TITLE_LINE_STYLES",
            "APP_TITLE_LITE_LINE_STYLES",
            "app_title_art_width",
            "build_art_title",
            "build_app_title",
            "build_app_title_for_width",
            "ResponsiveAppTitle",
            "ErrorReportsTable",
            "ProjectManagementTable",
            "ZoteroResultsTable",
            "EntryBatchTextArea",
            "ZoteroSearchInput",
            "ConfigTabbedContent",
            "DetailTabbedContent",
        )
        for name in names:
            self.assertIs(getattr(app, name), getattr(widgets, name))

    def test_narrow_title_falls_back_in_both_engines(self) -> None:
        """窄终端保留相同文字并使用各引擎的标题色板。"""
        for engine in ("heavy", "lite"):
            title = widgets.build_app_title_for_width(1, engine)
            self.assertEqual(title.plain, widgets.APP_TITLE_PLAIN)

    def test_title_boundaries_preserve_art_and_engine_palettes(self) -> None:
        """宽版与紧凑版边界应保留艺术字和当前引擎色板。"""
        wide_width = widgets.app_title_art_width(widgets.APP_TITLE_ART)
        compact_width = widgets.app_title_art_width(widgets.APP_TITLE_ART_COMPACT)
        for engine, palette in (
            ("heavy", widgets.APP_TITLE_LINE_STYLES),
            ("lite", widgets.APP_TITLE_LITE_LINE_STYLES),
        ):
            wide_title = widgets.build_app_title_for_width(wide_width, engine)
            compact_title = widgets.build_app_title_for_width(compact_width, engine)
            self.assertEqual(wide_title.plain, widgets.APP_TITLE_ART)
            self.assertEqual(compact_title.plain, widgets.APP_TITLE_ART_COMPACT)
            self.assertEqual([span.style for span in wide_title.spans], list(palette))
            self.assertEqual([span.style for span in compact_title.spans], list(palette))
