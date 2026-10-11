# TUI 应用脚本拆分实施计划

状态：已实施并完成定向验收。计划提交为 `f8aae37`；实现代码尚未提交。

> 执行者要求：使用 `superpowers:executing-plans` 在当前工作区逐项实施。步骤使用复选框追踪；每项完成后补充实现说明和实际验证结果。本文件只制定计划，不授权立即执行代码修改或自动提交实现代码。

**目标：** 按已通过的 spec 拆分 `src/tui/app.py`，形成可独立理解的控件、配置页、详情页、错误报告和 Zotero 模块，保持用户行为。

**架构：** 第一阶段抽取样式、控件和错误报告数据处理；第二阶段依次迁移配置页、Zotero 面板和详情页。App 保留导航、任务生命周期和项目身份；页面局部状态由所属组件持有，通过明确方法和 Textual 消息交互。

**技术栈：** Python 3.10+、unittest、Textual、Rich、TOML、setuptools。编写计划时，本地 `latextrans` 环境为 Textual `8.2.8`、setuptools `83.0.0`、wheel `0.47.0`；项目依赖仍为 `textual>=0.86.0`。

**设计依据：** [已通过的 spec](../specs/2026-10-10-tui-app-split-design.md)。用户于本轮通过设计；spec 原文已按用户要求提交为 `11dfa9e`。

## 全局约束

- 所有后续操作只在 `D:\projects\tools\worktrees\LaTeXTransPlus\total-cabin\LaTeXTransPlus`，不得回到旧项目目录编辑。共享 Git 元数据位于主仓库是 worktree 的正常机制，不意味着改写旧目录源码。
- 不创建新 worktree；执行前检查 Git 状态，有非本轮产生的未提交变化时按 AGENTS.md 询问。实施计划本身的待提交状态也应在开始代码实施前明确处理。
- 新文档、注释和 docstring 使用中文，文件使用 UTF-8，小块 `apply_patch` 编辑；每个新增类、函数和消息构造函数包含用途 docstring。
- 不改变布局、主题、快捷键、用户文案、配置结构、翻译流程、事件协议、项目元数据格式或 Zotero 业务语义；不增加依赖、不升级 Textual。
- 项目身份始终使用 `(task_id, project_name)`，项目管理、runtime 事件、取消与 worker 留在 App。
- 新模块不得导入 App，不使用 mixin、全局事件总线或动态导入回避依赖边界。
- 只用 `latextrans` conda 环境运行项目和测试。默认只运行新增 TUI 测试；调整既有测试的导入、mock 和断言，但未经用户要求不执行既有完整 TUI 套件。
- TUI 测试必须从临时 cwd 运行，并在整个 `run_test()` 生命周期拦截配置保存；不得读取或输出真实凭据，不访问真实翻译 API 或 Zotero。
- 保留 `src.tui.app:run`、App、页面常量和 spec 约定的重新导出；私有方法和依赖 patch 路径按实际所属模块迁移。
- 不以 App 行数作为机械门槛；完成要求是移除页面业务和重复状态，而不是把业务藏入委托链。
- 每个任务只在实际验证通过后勾选；记录未执行验证和原因。英文提交消息在任务末尾建议，除用户另行授权外不自动提交实现代码。

## 文件责任与执行顺序

| 任务 | 新增文件 | 修改文件 | 可独立验证的结果 |
| --- | --- | --- | --- |
| 1 | `src/tui/app.tcss`、`tests/test_tui_style_resources.py` | `src/tui/app.py`、`setup.py`、`tests/test_tui_app.py` | 样式从资源加载，保留安装包资源 |
| 2 | `src/tui/widgets.py`、`tests/test_tui_widgets.py` | `src/tui/app.py` | 控件迁移且重新导出同一对象 |
| 3 | `src/tui/error_reports.py`、`tests/test_tui_error_reports.py` | `src/tui/app.py`、`tests/test_tui_app.py` | 数据读取不依赖 UI，错误表保持原样 |
| 4 | `src/tui/config_page.py`、`tests/test_tui_config_page.py` | `src/tui/app.py`、`tests/test_tui_app.py`、`tests/test_tui_metadata_ui.py` | 配置只有一个所有者，生命周期不误保存 |
| 5 | `src/tui/zotero_panel.py`、`tests/test_tui_zotero_panel.py` | `src/tui/app.py`、`src/tui/widgets.py`、`tests/test_tui_app.py` | 面板独立完成搜索、选择、导入 |
| 6 | `src/tui/project_detail.py`、`tests/test_tui_project_detail.py`、`tests/test_tui_app_split.py` | `src/tui/app.py`、`src/tui/widgets.py`、`tests/test_tui_app.py` | 详情独立展示，App 只协调 |
| 7 | 无 | 本计划；必要时修正以上任务文件 | 验收覆盖、安装包资源和 diff 核验 |

以下迁移以方法名为准。当前 worktree 的代码基线早于旧目录，不把旧目录的标题提取或引擎颜色提交夹带进来。完整原有函数体从本 worktree 迁移，下面列出的代码用于新增接口与接线，不要求重新实现原有业务。

## 任务 1：迁出样式并补齐包资源

**文件：** 新增 `src/tui/app.tcss`、`tests/test_tui_style_resources.py`；修改 `src/tui/app.py`、`setup.py` 和 `tests/test_tui_app.py` 的 DEFAULT_CSS 断言。

**接口：** `LaTeXTransTuiApp.CSS_PATH = "app.tcss"`；安装包资源路径为 `src/tui/app.tcss`，不依赖 cwd。

- [x] 添加资源回归测试，完整示例放入新测试模块；期望重构前失败于 CSS_PATH 尚未指定资源，而不是依赖缺失。

```python
import unittest
from pathlib import Path
from src.tui import app as app_module


class TuiStyleResourcesTests(unittest.TestCase):
    """验证样式从应用模块旁的资源加载。"""

    def test_stylesheet_is_located_beside_app(self) -> None:
        """保证资源定位与调用方的工作目录无关。"""
        self.assertEqual(app_module.LaTeXTransTuiApp.CSS_PATH, "app.tcss")
        path = Path(app_module.__file__).with_name("app.tcss")
        css = path.read_text(encoding="utf-8")
        self.assertIn("#entry-form", css)
        self.assertIn("#zotero-results", css)
```

- [x] 执行 `conda run --no-capture-output -n latextrans python -X utf8 -m unittest tests.test_tui_style_resources -v`，记录预期失败。
- [x] 将 App 的 `DEFAULT_CSS` 三引号内文本原样迁入 `.tcss`，移除内联定义；App 设置 `CSS_PATH = "app.tcss"`。保持当前 worktree 的 CSS 值和规则顺序。
- [x] 在 `setup()` 增加 `package_data={"src.tui": ["app.tcss"]}`；不改入口、版本或依赖。既有样式字符串断言改读 `Path(tui_app.__file__).with_name("app.tcss").read_text(encoding="utf-8")`，不在 App 保留 CSS 副本。
- [x] 重跑资源测试，期望通过。安装包的真实资源与临时 cwd 启动验证在任务 7 执行。
- [x] 检查 diff 并记录实施说明。建议提交消息：`refactor(tui): extract stylesheet and package resources`。

### 任务 1 实施说明

已将 `DEFAULT_CSS` 的 4844 个字符逐字符迁入 `src/tui/app.tcss`，App 改用模块相对的 `CSS_PATH`，并在 `setup.py` 声明包资源。原样 CSS 不含计划示例中的 `#detail-tabs`，经确认将资源测试改为断言既有的 `#zotero-results`。资源测试先按 TDD 记录 `CSS_PATH` 为 `None` 的 1 条预期失败，再用计划命令重跑通过 1 条；三个既有样式断言从临时 cwd 定向运行，通过 3 条。安装 wheel 与临时安装启动按计划留到任务 7。

## 任务 2：迁出通用控件并保留导出

**文件：** 新增 `src/tui/widgets.py`、`tests/test_tui_widgets.py`；修改 `src/tui/app.py`。

**接口：** `widgets.py` 保留以下名称和现有函数签名：`APP_TITLE_PLAIN`、两版艺术字、两套标题色板、`app_title_art_width`、`build_art_title`、`build_app_title`、`build_app_title_for_width`、`ResponsiveAppTitle`、`ErrorReportsTable`、`ProjectManagementTable`、`ZoteroResultsTable`、`EntryBatchTextArea`、`ZoteroSearchInput`、`ConfigTabbedContent`、`DetailTabbedContent`。

- [x] 新增导出身份和标题边界测试；下面完整示例期望先因新模块不存在而失败。

```python
import unittest
from src.tui import app, widgets


class TuiWidgetsTests(unittest.TestCase):
    """验证控件迁移后的导出身份与响应式标题。"""

    def test_app_reexports_original_objects(self) -> None:
        """调用方应获得同一类和函数而不是复制实现。"""
        names = ("ResponsiveAppTitle", "ProjectManagementTable",
                 "ZoteroResultsTable", "build_app_title_for_width")
        for name in names:
            self.assertIs(getattr(app, name), getattr(widgets, name))

    def test_narrow_title_falls_back_in_both_engines(self) -> None:
        """窄终端保留相同文字并使用各引擎的标题色板。"""
        for engine in ("heavy", "lite"):
            title = widgets.build_app_title_for_width(1, engine)
            self.assertEqual(title.plain, widgets.APP_TITLE_PLAIN)
```

- [x] 执行 `conda run --no-capture-output -n latextrans python -X utf8 -m unittest tests.test_tui_widgets -v` 并记录失败。
- [x] 将上述常量、标题函数及类的完整现有定义迁到 `widgets.py`；私有 `_title_line_styles` 一并迁移，按真实使用迁入 Rich/Textual 和 `normalize_engine` 导入。App 显式导入需兼容的符号。
- [x] 保持控件当前 App 回调、Enter 绑定、鼠标抑制标记、游标和 resize 行为。`compact_progress_log_for_display` 和 `_merge_project_log_text` 此时仍在 App，任务 6 再迁移。
- [x] 重跑上述测试，期望通过；检查 `widgets.py` 没有导入 `src.tui.app`。
- [x] 检查 diff 并记录实施说明。建议提交消息：`refactor(tui): extract reusable widgets`。

### 任务 2 实施说明

已将两版艺术字、两套标题色板、标题构建函数和 8 个通用 Textual 控件原样迁入 `src/tui/widgets.py`，App 通过显式导入继续导出同一对象。表格回调、Enter 绑定、鼠标事件抑制、游标与 resize 行为保持不变，日志合并和压缩函数仍由 App 持有。新增测试先记录模块不存在导致的 1 条预期导入失败；迁移后扩展为覆盖全部兼容符号身份、窄屏回退、宽版/紧凑版边界及 Heavy/Lite 色板，任务命令通过 3 条。`widgets.py` 无 App 反向导入，三个既有标题用例的附加定向运行因当前 worktree 不存在 `config/ui.toml` 而在公共测试基类初始化阶段报错，未修改或生成真实 UI 配置；旧 TUI 全套测试按约束未运行。

## 任务 3：抽取错误报告数据处理

**文件：** 新增 `src/tui/error_reports.py`、`tests/test_tui_error_reports.py`；修改 `src/tui/app.py` 和 `tests/test_tui_app.py` 中直接使用迁移私有方法的用例。

**输入：** 现有 `ProjectViewState` 和报告/map 路径。**输出接口：**

| 原 App 方法 | 新模块函数签名 |
| --- | --- |
| `_project_errors_report_path` | `project_errors_report_path(project: ProjectViewState) -> Path | None`，只解析，不回填 |
| `_error_reports_with_status` | `error_reports_with_status(project: ProjectViewState, report_path: Path | None) -> list[tuple[dict[str, object], str]]` |
| `_read_error_report` | `read_error_report(report_path: str | None) -> list[dict[str, object]]` |
| `_initial_error_report_path` | `initial_error_report_path(report_path: str | None) -> Path | None` |
| `_error_report_key` | `error_report_key(report: dict[str, object]) -> tuple[str, str]` |
| `_error_report_position` | `error_report_position(report: dict[str, object]) -> str` |
| `_error_report_type` | `error_report_type(report: dict[str, object]) -> str` |
| `_error_report_problem` | `error_report_problem(report: dict[str, object]) -> str` |
| `_error_report_content` | `error_report_content(report: dict[str, object], project: ProjectViewState) -> tuple[str, str]` |
| `_error_content_root` | `error_content_root(project: ProjectViewState) -> Path | None` |
| `_find_error_part_record` | `find_error_part_record(content_root: Path, part: str, identifier: str) -> dict[str, object] | None` |
| `_read_json_list` | `read_json_list(path: Path) -> list[dict[str, object]]` |

- [x] 添加完整数据回归测试示例，并补充空文件、损坏 JSON、非列表、非对象元素、新旧 issue 字段及三个 map 类型的用例。

```python
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from src.tui.error_reports import error_reports_with_status, project_errors_report_path
from src.tui.state import ProjectViewState


class TuiErrorReportsTests(unittest.TestCase):
    """验证报告迁移后保留合并顺序且不修改项目状态。"""

    def test_merge_retains_final_and_resolved_initial_rows(self) -> None:
        """最终报告优先，同位置初始记录不重复。"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = [{"part": "sec", "num_or_ph": "1", "error": "old"},
                       {"part": "cap", "num_or_ph": "2", "error": "fixed"}]
            final = [{"part": "sec", "num_or_ph": "1", "error": "current"}]
            path = root / "errors_report.json"
            path.write_text(json.dumps(final), encoding="utf-8")
            (root / "initial_errors_report.json").write_text(
                json.dumps(initial), encoding="utf-8")
            project = ProjectViewState(project_name="paper", output_dir=str(root))
            resolved_path = project_errors_report_path(project)
            self.assertEqual(resolved_path, path)
            self.assertIsNone(project.errors_report_path)
            self.assertEqual(error_reports_with_status(project, resolved_path),
                             [(final[0], "unresolved"), (initial[1], "resolved")])
```

- [x] 执行 `conda run --no-capture-output -n latextrans python -X utf8 -m unittest tests.test_tui_error_reports -v`，期望因新模块不存在失败。
- [x] 按表迁移原有完整函数体，去掉 `self` 并将内部调用替换为模块函数。合并函数使用传入的 `report_path`，移除函数内原有路径发现调用；保留 `OSError`、`JSONDecodeError`、空结果及项目错误/PDF 警告回退语义。
- [x] App 的错误表仍负责 Rich 文本、列宽与截断。用以下完整委托保留必要路径回填；`error_reports` 为从 `src.tui` 导入的模块。

```python
def _project_errors_report_path(self, project: ProjectViewState) -> Path | None:
    """解析报告路径并保留既有的产物路径回填。"""
    path = error_reports.project_errors_report_path(project)
    if path is not None:
        project.errors_report_path = str(path)
    return path


def _error_reports_with_status(self, project: ProjectViewState) -> list[tuple[dict[str, object], str]]:
    """将已解析路径交给独立的错误报告数据模块。"""
    path = self._project_errors_report_path(project)
    return error_reports.error_reports_with_status(project, path)
```

- [x] 表格内容和字段文字转换直接调用模块函数；移除其余迁移方法的重复业务实现。相关既有测试改测模块函数，UI 展示断言保持。
- [x] 重跑新增数据测试，期望通过；检查新模块没有 Textual/Rich/App 依赖。建议提交消息：`refactor(tui): isolate error report data handling`。

### 任务 3 实施说明

已将错误报告路径解析、最终/初始报告合并、字段转换和三类 map 内容反查迁入 `src/tui/error_reports.py`；纯函数不回填项目状态，App 仅在薄委托中保留既有路径回填，并继续负责 Rich 状态文本、列宽和截断。新增测试先因模块不存在产生预期导入错误；实现后 8 条数据测试全部通过，覆盖空文件、损坏 JSON、非列表、非对象元素、项目错误/PDF 警告回退、新旧 issue 字段和 sections/captions/envs 三类 map。模块依赖检查未发现 Textual、Rich 或 App 反向依赖，App 与新模块导入检查通过；按项目约束未扩大运行旧 TUI 测试。

## 任务 4：迁入 ConfigPage 并隔离保存生命周期

**文件：** 新增 `src/tui/config_page.py`、`tests/test_tui_config_page.py`；修改 App 和两个既有 UI 测试文件的实际依赖 patch 路径。

**组件：** `ConfigPage(Vertical)`，构造参数 `engine: str`、`id: str = "config"`。在 App 初始化中创建 `self.config_page = ConfigPage(self.effective_engine)`，替换原 `Vertical(id=PAGE_CONFIG)` 整段为 `yield self.config_page`，不增加包装层。

**确定接口：**

- `load_config() -> None`：读取配置，受保护地填充并更新预览。
- `get_config() -> dict[str, object]`：返回深拷贝；快照为空时按需调用 `load_ui_config(Path.cwd())` 并缓存，不触发保存或表单事件。
- `set_config(config: dict[str, object]) -> None`：深拷贝到组件的 `current_config`，不自动保存。
- `set_engine(engine: str, rebuild: bool = True) -> None`：归一化引擎，按需调用本组件的异步 worker `_rebuild_config_fields()`。
- `persist_form() -> None`：保留原表单校验、保存、预览及错误提示。
- `save_default_engine(engine: str) -> None`：基于 `get_config()` 保存默认值，更新唯一快照并发送配置变化消息。
- `ConfigPage.ConfigChanged(config: dict[str, object])`：继承 `Message`，消息中的配置是深拷贝，不与快照共享可变字典。

- [x] 新模块添加生命周期测试，使用以下完整 setup 和清理注册。`tests/test_tui_config_page.py` 的 `TuiConfigPageTests` 继承 `unittest.IsolatedAsyncioTestCase`；模块导入 `unittest`、`os`、`TemporaryDirectory`、`Path`、`Mock`、`patch`、`Select` 和 `LaTeXTransTuiApp`。其他新组件测试各自保留简单的同等隔离 setup，不从既有大测试模块继承。

```python
async def asyncSetUp(self) -> None:
    """将整个 UI 生命周期放入临时目录并拦截配置访问。"""
    self.original_cwd = Path.cwd()
    self.temporary = TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.addCleanup(os.chdir, self.original_cwd)
    os.chdir(self.temporary.name)
    self.save = Mock()
    targets = {
        "src.tui.app.load_ui_config": Mock(return_value={}),
        "src.tui.config_page.load_ui_config": Mock(return_value={}),
        "src.tui.config_page.save_ui_config": self.save,
        "src.tui.config.save_ui_config": self.save,
        "src.tui.config_page.list_llm_profiles": Mock(return_value=[]),
        "src.tui.config_page.list_available_font_families": Mock(return_value=[]),
    }
    for target, replacement in targets.items():
        patcher = patch(target, replacement)
        patcher.start()
        self.addCleanup(patcher.stop)


async def test_mount_rebuild_and_delayed_edit_save_only_user_change(self) -> None:
    """组件挂载和重建不保存，用户编辑只保存一次。"""
    app = LaTeXTransTuiApp(load_history_on_mount=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_engine("lite")
        await app.workers.wait_for_complete()
        await pilot.pause()
        self.save.assert_not_called()
        page = app.config_page
        config = {"target_language": "ja", "engine": "heavy"}
        with patch.object(page, "_config_from_form", return_value=config):
            app.query_one("#config-target_language", Select).value = "ja"
            await pilot.pause()
        self.save.assert_called_once()
        self.assertEqual(page.get_config()["target_language"], "ja")
        self.assertEqual(app.effective_engine, "lite")
```

- [x] 执行 `conda run --no-capture-output -n latextrans python -X utf8 -m unittest tests.test_tui_config_page -v`，确认缺少组件导致失败，不使用 `create=True`。
- [x] 从 App 迁移 `_config_form_widgets` 至 `_update_config_preview` 的完整方法体，连同 `_is_config_widget`、`_config_from_form`、异步重建和保护标记。局部字段使用组件的 `effective_engine`；保留字段名、提示、归一化和未知元数据合并。
- [x] 配置页 `compose()` 迁入原配置 tab 子树。`on_mount()` 保持加载保护并在布局稳定后解除；`load_config()` 和重建都在填充及排空延迟事件后解除保护，异常路径恢复标记。使用组件自己的 `prevent(...)`，不借用 App 的事件上下文。
- [x] 配置页接收 Input/Select/Switch/TextArea 的 Changed，确认来源为配置编辑字段后 `event.stop()` 并调用 `persist_form()`；预览 TextArea 不触发保存。配置预览 tab 的激活由组件接收并保持原行为。移除 App 对这些配置事件的重复处理，保留入口引擎 Switch。
- [x] 使用以下完整状态转发和消息接线；App 初始化移除独立配置字典、加载保护和字体缓存。原加载/保存公开方法只委托 `config_page.load_config()`/`persist_form()`，引擎持久化路径调用 `save_default_engine()`。

```python
@property
def current_config(self) -> dict[str, object]:
    """提供当前配置快照的兼容读取入口。"""
    return self.config_page.get_config()


@current_config.setter
def current_config(self, config: dict[str, object]) -> None:
    """把兼容赋值转交配置页的唯一状态。"""
    self.config_page.set_config(config)
```

- [x] Zotero 尚在 App 时，`on_config_page_config_changed` 不缓存第二份配置，继续通过转发属性读取；任务 5 接入面板后，该 handler 将 `message.config` 中的 Zotero 段传给面板。
- [x] 新增配置深拷贝、空快照回退、默认引擎不切会话、非法整数不保存、两种引擎 profile/字体、隐藏字段和未知元数据保留测试；表单值测试使用完整假配置，按现有 config_schema 默认值构造，不加载真实 provider 文件。
- [x] 既有测试把字体/profile/表单加载依赖 patch 改为 `src.tui.config_page.*`，生命周期保存 patch 覆盖该模块；启动参数测试保留 `src.tui.app.load_ui_config`。真实 UI 配置哈希保护继续保留，不能通过删除检查绕过问题。
- [x] 重跑新增配置测试，期望通过，填写实施说明。建议提交消息：`refactor(tui): encapsulate configuration page`。

### 任务 4 实施说明

已将配置页布局、字段构建、profile/字体提示、表单填充与校验、TOML 预览和保存迁入 `ConfigPage`，App 仅保留兼容委托、深拷贝状态转发及会话引擎入口。配置保存生命周期使用代次和活动计数隔离挂载、连续重建、嵌套加载及 worker 取消，旧 refresh 回调不能提前放行保存；正常结束、异常和取消均等待延迟 Changed 排空后才解除保护。显式空快照会恢复按需加载，而一次真实加载得到的空配置仍只缓存一次。新增测试先因模块不存在产生预期导入错误，实现后覆盖深拷贝、空快照、默认引擎、整数校验、两种引擎字段、未知元数据、预挂载切换和交叠生命周期；`conda run --no-capture-output -n latextrans python -X utf8 -m unittest tests.test_tui_config_page -v` 最终通过 12 条测试。既有 UI 测试已改用临时 cwd 和 `src.tui.config_page.*` patch，并保留真实 `config/ui.toml` 的存在状态与摘要保护；受影响的 32 条既有定向测试初跑 29 条通过，3 条旧等待/文案断言修正后已定向重跑通过。编译检查和 `git diff --check` 通过，工作树中未生成 `config/ui.toml`；按项目约束未运行旧 TUI 全套。

## 任务 5：封装 ZoteroPanel 与局部控件消息

**文件：** 新增 `src/tui/zotero_panel.py`、`tests/test_tui_zotero_panel.py`；修改 App、`widgets.py` 和既有 Zotero UI 用例。

**组件：** `ZoteroPanel(TabPane)`，标题为现有 `"Zotero"`，ID 为 `"zotero-tab"`。直接替换现有 Zotero TabPane，不把新容器套进 TabPane。`adapter_factory` 的类型为 `Callable[[str, str], ZoteroAdapter]`，默认工厂仍采用现有创建逻辑。

**确定接口：**

- `set_context(*, project: ProjectViewState | None, task_id: str | None, input_type: str, arxiv_id: str, engine: str, config: dict[str, object], reset_selection: bool = False) -> None`：接收 Zotero 段配置的副本，身份变化或显式 reset 时清空结果，普通刷新不清空。
- `update_config(config: dict[str, object]) -> None`：只更新 Zotero 配置副本，不清空结果和选择。
- 保留 `load_zotero_libraries() -> None`、`search_zotero_items() -> None`、`auto_match_zotero_items() -> None`、`clear_zotero_results() -> None`、`toggle_zotero_row_selection(row_index: int) -> None`、两个导入操作的现有签名，以及 `populate_zotero_results(results: list[dict[str, object]]) -> None`。
- `ZoteroPanel.StatusChanged(message: str)`：向 App 的统一通知入口传递提示；面板自行更新当前项目的 `zotero_status`。

- [x] 新测试类 `TuiZoteroPanelTests` 使用临时 cwd 和整个交互生命周期的配置 patch。新增以下完整测试方法；模块导入 `Mock`、`patch`、`Input`、`Select`、`LaTeXTransTuiApp`。假 adapter 的调用期望不包含任何真实服务数据。

```python
async def test_enter_search_reaches_adapter_once(self) -> None:
    """输入框提交由所属面板处理且不被 App 再次执行。"""
    app = LaTeXTransTuiApp(load_history_on_mount=False)
    adapter = Mock()
    adapter.search_items.return_value = []
    async with app.run_test() as pilot:
        panel = app.zotero_panel
        panel.adapter_factory = Mock(return_value=adapter)
        panel.zotero_libraries = [
            {"library_type": "user", "library_id": "7", "name": "Test"}]
        select = panel.query_one("#zotero-library-select", Select)
        select.set_options([("Test", "user:7")])
        select.value = "user:7"
        search = panel.query_one("#zotero-search-input", Input)
        search.value = "paper"
        app.switch_page("detail")
        app.query_one("#detail-tabs").active = "zotero-tab"
        with patch.object(panel, "load_zotero_libraries"):
            await pilot.pause()
            search.focus()
            await pilot.press("enter")
            await pilot.pause()
        adapter.search_items.assert_called_once_with("paper", "7", "user")
```

- [x] 执行 `conda run --no-capture-output -n latextrans python -X utf8 -m unittest tests.test_tui_zotero_panel -v`，记录缺少面板/接口的失败。
- [x] 完整迁移 App 中 `_initialize_zotero_results_table` 至 `_selected_zotero_library` 的 Zotero 业务方法与列宽常量；保留数据表私有尺寸更新调用，不顺带重写列宽策略。`_translated_markdown_path` 一并迁入，`_selected_task_input_type` 和 `_selected_arxiv_id` 留在 App 用于上下文准备。
- [x] 将业务代码中的 `_selected_project()`、配置回退、输入类型和 arXiv 推断改为面板明确接收的上下文。凭据解析仍只在导入分支，通过配置环境变量名查找；测试使用临时假变量值，不枚举环境，也不读真实值。保留 adapter 的 TypeError 兼容分支和逐项失败继续处理。
- [x] `ZoteroSearchInput` 定义 `SearchRequested(Message)`；`ZoteroResultsTable` 定义 `SelectionRequested(row_index: int)` 与 `ResizeRequested(Message)`。构造函数说明载荷用途。搜索 action 和单击方法只发消息，面板 handler 停止冒泡后调用业务方法；resize handler 按原有布局时机调整列宽。原有重复点击抑制和游标滚动逻辑保留。
- [x] 面板处理自身按钮、Input.Submitted、DataTable.RowSelected 和控件消息；保留 Enter 绑定的优先级，确保一种提交只走一条路径。App 删除对应 Zotero 事件分支，不删除项目管理表的处理。
- [x] App 暂时持有 `self.zotero_panel` 并在原详情 tab 位置 `yield` 该面板；初始化结果表改由面板 `on_mount` 完成。App 在选择、引擎变化、产物完成时提供上下文；显式选择同一项目也按原有语义传 `reset_selection=True`。
- [x] 若保留 App 的 Zotero 公开委托，调用前同步 App 的 `zotero_adapter_factory` 至面板，以兼容现有调用方注入；组件测试直接注入面板工厂。结果列表和选择集合从 App 移除，既有测试直接读取面板状态，不保留独立副本。
- [x] `on_config_page_config_changed` 取 Zotero 段：值为字典时调用 `panel.update_config(...)`，否则传空字典；`on_zotero_panel_status_changed` 仅执行 `event.stop()` 和 `self._notify(event.message)`，不再次写项目状态。
- [x] 新增完整身份切换清空、同身份刷新保留、单击切换一次、窄宽 resize、空库/搜索错误、自动匹配、缺失文件与凭据名提示、PDF 与 Markdown 部分导入失败继续处理的回归测试。
- [x] 重跑新增面板测试，期望通过；核验无真实网络、App 反向依赖或重复状态。建议提交消息：`refactor(tui): encapsulate Zotero panel interactions`。

### 任务 5 实施说明

已将 Zotero 搜索、自动匹配、选择、导入、状态与列宽处理迁入 `ZoteroPanel`，App 只保留上下文准备、父详情 tab 激活和兼容公开委托。控件通过局部消息与面板交互；实测鼠标点击产生的 `RowSelected` 会消费抑制标记，随后键盘 Enter 仍可再次切换。新增 13 条隔离测试先记录缺少模块的预期失败，最终覆盖明确上下文、相同身份保留、显式重置、运行时 adapter 注入、空库与失败提示、窄宽往返、PDF/Markdown 逐项失败继续处理；指定测试命令通过。编译及依赖扫描确认面板不反向导入 App，结果、选择和库列表只由面板持有，测试未访问真实 Zotero 或翻译服务。

## 任务 6：迁入 ProjectDetail，完成 App 协调边界

**文件：** 新增 `src/tui/project_detail.py`、`tests/test_tui_project_detail.py`、`tests/test_tui_app_split.py`；修改 App、`widgets.py` 和既有详情/日志测试的调用位置。

**组件：** `ProjectDetail(Vertical)`，构造参数 `engine: str`、`adapter_factory: Callable[[str, str], ZoteroAdapter]`、`id: str = "detail"`。内部创建并持有任务 5 的 `ZoteroPanel`；直接替换 App 原详情根容器。

**确定接口：**

- `set_engine(engine: str) -> None`：执行原有 tab 显隐与首选 tab 回退，未挂载时只记录值。
- `show_project(project: ProjectViewState | None, *, task_id: str | None, task_log_lines: list[str], input_type: str, arxiv_id: str, zotero_config: dict[str, object], reset_zotero: bool = False) -> None`：记录展示上下文、刷新产物并调用面板的 `set_context()`。项目为 None 时不读取文件，按现有行为管理空上下文。
- `refresh_log(task_log_lines: list[str]) -> None`：更新任务日志快照并只刷新日志，用于 task_log 事件。
- `refresh_log_and_terms(task_log_lines: list[str]) -> None`：调用 `refresh_log()` 后刷新术语，用于 project_log 事件；不重读 TeX、Markdown 或错误报告。
- `refresh_selected_errors_table() -> None`：依据当前项目和当前可视宽度重画错误表。
- `zotero_panel: ZoteroPanel`：供 App 转发上下文、配置和兼容操作。
- 迁入 `_merge_project_log_text(file_text: str, memory_lines: list[str]) -> str`、`compact_progress_log_for_display(log_text: str) -> str` 和对应正则；App 显式重新导出这两个函数。

- [x] 新增 `TuiAppSplitTests`，使用临时 cwd 和任务 4 同等配置隔离。下面完整测试先验证两个任务的同名项目日志不会混入；模块导入 `patch`、App、`ProjectViewState` 和 `TaskViewState`。

```python
async def test_same_name_project_log_routes_by_task_identity(self) -> None:
    """同名项目的日志只刷新当前选中的任务。"""
    app = LaTeXTransTuiApp(load_history_on_mount=False)
    first = TaskViewState(input_type="arxiv", inputs=["same"], task_id="first")
    second = TaskViewState(input_type="arxiv", inputs=["same"], task_id="second")
    first.projects = [ProjectViewState(project_name="same")]
    second.projects = [ProjectViewState(project_name="same")]
    app.tasks = [first, second]
    async with app.run_test() as pilot:
        app.select_project("same", task_id="first")
        await pilot.pause()
        with patch.object(app.project_detail, "refresh_log_and_terms") as refresh:
            app.handle_runtime_event(
                {"type": "project_log", "project_name": "same", "line": "other"},
                second)
            refresh.assert_not_called()
            app.handle_runtime_event(
                {"type": "project_log", "project_name": "same", "line": "selected"},
                first)
            refresh.assert_called_once_with(first.task_log_lines)
```

- [x] 执行 `conda run --no-capture-output -n latextrans python -X utf8 -m unittest tests.test_tui_project_detail tests.test_tui_app_split -v`，记录缺失组件/接线的失败。
- [x] 将原详情 tab 子树、`_refresh_detail_tabs`、`_refresh_tex_preview` 至 `_project_terms_path` 中属于展示的方法迁入。任务 3 的报告读取函数继续只在数据模块实现；迁入错误列宽常量、Rich 状态色、文本截断与必要的路径回填。
- [x] 将 `_refresh_project_log` 的 `self.tasks` 等应用状态依赖替换为显式任务日志快照，文件/内存日志合并及连续进度压缩保持原算法。语法高亮、TeX 发现、Markdown 路径、术语 CSV 和读取提示完整迁移，不引入缓存或新渲染方式。
- [x] `ErrorReportsTable` 定义无载荷的 `ResizeRequested(Message)`，resize 时发送消息；详情组件处理后 `event.stop()` 并按原时机 `call_after_refresh(self.refresh_selected_errors_table)`。错误 tab 激活也由详情组件接收；Zotero tab 激活委托面板加载库，配置 tab 激活仍由配置页处理。
- [x] App 初始化 `self.project_detail`，在 compose 中 `yield self.project_detail`；App 的 `zotero_panel` 改为读取 `self.project_detail.zotero_panel` 的属性，不再创建第二个面板。原 public 详情刷新和 Zotero 操作保留必要薄委托。
- [x] App 的详情刷新先按完整身份取得关联 task/project，再传入 task 日志、输入类型、按原优先级提取的 arXiv ID 和 Zotero 配置。`select_project` 传 `reset_zotero=True`；普通产物刷新不清空用户的 Zotero 选择。
- [x] 用以下完整方法替换日志协调；日志事件仍在 `handle_runtime_event` 中 apply 后刷新并直接返回，取消与 worker 代码不迁移。

```python
def _refresh_selected_project_log(
    self, event: dict[str, object], task: TaskViewState | None = None
) -> None:
    """仅将当前任务项目的日志事件交给详情组件。"""
    event_type = event.get("type")
    if event_type not in {"project_log", "task_log"}:
        return
    project = self._selected_project()
    target_task = task or self.current_task
    if project is None or target_task is None:
        return
    if target_task.task_id != self.selected_task_id:
        return
    if event_type == "project_log" and project.project_name != str(event.get("project_name") or ""):
        return
    if event_type == "task_log":
        self.project_detail.refresh_log(target_task.task_log_lines)
    else:
        self.project_detail.refresh_log_and_terms(target_task.task_log_lines)
```

- [x] 新增纯日志合并/进度压缩测试，Heavy/Lite 文件展示与缺失提示测试，错误 tab 激活及 resize 测试，Zotero 项目切换上下文测试。三个表格的 resize 测试使用 `await pilot.resize_terminal(140, 40)` 和再次缩窄，比较列宽并确认选择和游标仍有效。
- [x] 新增 App 集成测试覆盖入口 Enter 提交一次、单击项目/Zotero 行切换一次、完成事件刷新当前产物、切引擎不改任务引擎、取消后迟到完成不覆盖状态，以及日志事件不重建项目列表/不写元数据。全部任务运行使用假 runner/进程，不启动翻译。
- [x] 更新既有详情测试的实际依赖位置，删除 App 内重复业务实现、已迁入组件的事件分支、无用导入和临时委托；保留 `_notify`、任务生命周期、元数据保存和 runner 替换检测。
- [x] 重跑上述新增测试，期望通过，填写实施说明。建议提交消息：`refactor(tui): encapsulate project detail views`。

### 任务 6 实施说明

已新增 `ProjectDetail` 并将详情标签树、Heavy/Lite 产物、错误表、日志与术语展示迁入组件；App 直接挂载该组件，只保留完整任务/项目身份解析、任务生命周期和必要兼容委托。Zotero 面板现在由详情组件唯一持有，显式选项目重置结果，普通完成刷新保留选择；arXiv ID 按项目名和关联任务输入提取，不再误用其他当前任务。错误表 resize 与错误/Zotero tab 激活由详情内部消费，日志事件在应用状态后严格按 task id 和项目名局部刷新并直接返回。

TDD 首次运行按计划因 `src.tui.project_detail` 不存在而失败；实现后新增两模块共 18 条测试通过（176.301 秒），覆盖日志纯函数、空上下文不读文件、日志快照复制、三张表缩放、Enter/单击单次触发、完成/切引擎/取消迟到/runner 替换分支和同名项目身份路由。随后补强测试隔离，App 默认 Zotero adapter 统一替换为空库 fake，自动激活 Zotero tab 的定向交互测试通过；最终七模块综合验证由任务 7 执行。

## 任务 7：安装包、集成与最终验收

**文件：** 在 `tests/test_tui_style_resources.py` 增加安装包验证；检查所有本次文件，更新本计划实际完成项。此步骤包含验证所需的新增测试代码，不修改运行功能。

- [x] 将以下完整方法加入任务 1 的 `TuiStyleResourcesTests`；模块补充 `shutil`、`subprocess`、`sys`、`zipfile` 和 `TemporaryDirectory` 导入。只复制明确列出的源码与打包文件，不复制配置、provider、输出或 Git 元数据。

```python
def test_wheel_has_stylesheet_and_runs_from_temporary_cwd(self) -> None:
    """验证分发包资源及安装后的样式定位。"""
    repository = Path(__file__).resolve().parents[1]
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        stage = root / "source"
        stage.mkdir()
        shutil.copytree(repository / "src", stage / "src")
        for name in ("setup.py", "main.py", "requirements.txt"):
            shutil.copy2(repository / name, stage / name)
        wheels = root / "wheels"
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-deps",
             "--no-build-isolation", "--no-index", "--wheel-dir", str(wheels),
             str(stage)], cwd=stage, check=True, capture_output=True, text=True)
        wheel = next(wheels.glob("*.whl"))
        installed = root / "installed"
        with zipfile.ZipFile(wheel) as archive:
            self.assertIn("src/tui/app.tcss", archive.namelist())
            archive.extractall(installed)
        foreign_cwd = root / "foreign"
        foreign_cwd.mkdir()
        smoke = f'''
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, {str(installed)!r})
from src.tui import app as app_module

async def verify():
    """从临时安装目录挂载应用，隔离配置访问。"""
    save = Mock()
    adapter = Mock()
    adapter.list_libraries.return_value = []
    with patch("src.tui.app.load_ui_config", return_value={{}}), \\
         patch("src.tui.app.ZoteroAdapter", return_value=adapter), \\
         patch("src.tui.config_page.load_ui_config", return_value={{}}), \\
         patch("src.tui.config_page.save_ui_config", save), \\
         patch("src.tui.config.save_ui_config", save), \\
         patch("src.tui.config_page.list_llm_profiles", return_value=[]), \\
         patch("src.tui.config_page.list_available_font_families", return_value=[]):
        for engine in ("heavy", "lite"):
            app = app_module.LaTeXTransTuiApp(
                load_history_on_mount=False, initial_engine=engine)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                assert app.query_one("#entry-form").size.width > 0
                await pilot.resize_terminal(40, 30)
                await pilot.pause()
                assert app.query_one("#app-title").size.width > 0
    save.assert_not_called()
    assert Path(app_module.__file__).resolve().is_relative_to(
        Path({str(installed)!r}).resolve())

asyncio.run(verify())
'''
        subprocess.run([sys.executable, "-c", smoke], cwd=foreign_cwd,
                       check=True, capture_output=True, text=True)
```

- [x] 执行前记录：构建通常产生 build/egg-info，但本测试只在临时源码副本产生；不会修改当前环境的 editable 安装。先检查 `pip`、setuptools、wheel 可用，缺失且无简单方案时按项目规则报告，不替代为伪造 wheel。
- [x] 定向运行下面七个新增模块，全部应通过；资源模块包含首次安装包验证。若资源测试失败，按 systematic-debugging 查明资源缺失、安装路径或生命周期问题，不跳过断言；修正后只定向复跑受影响用例，不重复无关构建。

```powershell
conda run --no-capture-output -n latextrans python -X utf8 -m unittest tests.test_tui_style_resources tests.test_tui_widgets tests.test_tui_error_reports tests.test_tui_config_page tests.test_tui_zotero_panel tests.test_tui_project_detail tests.test_tui_app_split -v
git diff --check
git diff --stat
git status --short
```

- [x] 检查真实 `config/ui.toml` 的 diff 和测试前后哈希，仅比较摘要，不输出内容；文件不存在时核验执行后仍未生成。确认 worker mock、配置 mock 和 adapter mock 在整个交互生命周期生效。
- [x] 核对新模块无 App 反向导入，App 无表单生成、错误报告读取、Zotero 搜索/导入业务和局部状态副本；所有公开兼容委托只指向唯一实现。审阅既有测试的 mock 路径修改，不默认执行旧 TUI 全套测试。
- [x] 确认最终 diff 无用户配置、构建产物、旧目录修改或无关修复；确认临时目录已正常清理。对本轮实际产生的无关文件先核实路径再清理，不处理用户原有变化。
- [x] 根据下表逐项核对 spec，更新任务复选框与实际实现/验证说明。最终汇报变更、测试结果、未运行项目与原因，建议英文提交消息：`refactor(tui): split app into focused components`。

### 任务 7 实施说明

新增真实 wheel 验证，只在临时源码副本构建并解压到临时安装目录；从另一临时 cwd 挂载 Heavy/Lite 并缩放终端，确认资源位于 wheel 中且 App 确实从该安装目录导入。构建使用 `--no-deps --no-build-isolation --no-index`，不安装到真实环境。配置保存与自动 Zotero tab 激活的 adapter 均在整个测试生命周期替换为 fake。

最终按上述七模块命令运行 56 项，55 项通过，唯一错误是任务 5 的测试仍调用已经迁走的 App tab handler；将调用位置更新为 `app.project_detail.on_tabbed_content_tab_activated` 后，该用例定向 1/1 通过，并复跑 `tests.test_tui_zotero_panel -v` 得到 13/13 通过（138.059 秒）。其余 43 项均在最终生产代码上通过；本次只改测试入口，未重复无关构建或套件。56 个新增用例均已验证通过，其中资源模块包含真实 wheel 验证。按项目约束，未运行既有完整 TUI 套件及全项目测试，也未调用真实翻译流程或 PDF 编译。

UTF-8/AST/docstring、模块依赖方向、样式与原 `DEFAULT_CSS` 逐字符一致检查通过；`git diff --check` 无错误，仅有计划文件 LF/CRLF 提示。测试前后真实 `config/ui.toml` 均不存在，未生成配置、build、dist 或 egg-info 变更。`app.py` 最终为 1,172 行。任务 1 至 6 的分项审查及最终 `medium` 审查通过，无未处理代码问题。所有实现修改留在当前 worktree，未提交、未合并。

## Spec 覆盖与交付检查

| Spec 要求 | 实施任务 | 交付证据 |
| --- | --- | --- |
| 两阶段迁移、明确依赖 | 1 至 3；4 至 6 | 每个阶段可启动，新增模块无 App 导入 |
| 样式不变、包资源及任意 cwd | 1、7 | 资源测试、真实 wheel 及临时安装启动 |
| 控件、标题及导出兼容 | 2、5、6 | 导出身份、窄屏、Enter、点击与快捷键测试 |
| 唯一配置状态及默认/会话引擎区分 | 4 | 深拷贝、回退、表单及生命周期测试 |
| 无 UI 依赖的错误报告处理 | 3、6 | 纯数据报告测试与错误表展示/resize |
| 详情文件、日志及项目身份 | 6 | 两引擎产物、日志压缩、同名任务事件路由 |
| Zotero 上下文、状态提示、部分失败 | 5、6 | 假 adapter、选择清空、导入统计测试 |
| 三个表格 resize 不退化 | 5、6 | 实际终端 resize，列宽/选择/游标断言 |
| 任务提交、取消、迟到事件与 runner 兼容 | 6、7 | 假进程集成测试、App 保留原 worker 分支 |
| 配置/凭据隔离、定向测试、diff 卫生 | 全部，最终 7 | 生命周期 mock、配置摘要、最终状态与 diff |

## 实施记录规则

每个任务结束后在对应任务末尾新增一段“任务 N 实施说明”，记录迁入方法与必要的接口调整、实际命令、测试通过数量及未执行项。尚未执行的任务维持 `[ ]`；本轮编写计划不代表任何实施步骤已经完成。

如执行时发现接口需要调整，先说明依据并同步修改所有调用方、测试与本计划，保持同一接口名称和类型。遇到超出 spec 的业务变化、缺失必需依赖或多种语义解决的冲突时停止相关操作并报告。

## 文档核验与下一步

本计划覆盖已通过 spec 的全部模块及验收边界。代码片段使用现有字段 ID（例如 `config-target_language`）和 unittest 约定；方法迁移依据当前 worktree，不依据旧目录行号。

实施已在当前 worktree 完成，任务清单与实际验证结果已同步。按用户最新要求，后续审查子代理使用 `medium` 思考强度。当前分支保留为 `feat/code-structure`；实现提交消息建议见任务 7。
