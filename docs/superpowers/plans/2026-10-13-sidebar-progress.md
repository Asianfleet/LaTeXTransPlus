# 左侧项目实时进度实现计划

**目标：** 运行中的项目在标题下显示 `⌊ 进度文本`，终态恢复为单行。

**设计：** 沿用 `project_log`，集中识别阶段日志；状态模型保存临时进度，独立条目组件渲染两行。按任务 ID 和项目名局部更新，保持列表选择和滚动位置。

**约束：** 使用 latextrans conda 环境；测试隔离真实 UI 配置；不保存临时进度到历史；不新增依赖。

- [x] 增加回归测试并确认缺少进度接口及第二行组件。
  实施记录：状态测试验证提取和结束清理，UI 测试验证项目身份和布局。
- [x] 实现阶段提取、状态生命周期和两行条目组件。
  实施记录：集中识别八类日志，终态清除进度并忽略迟到日志，组件隐藏空进度。
- [x] 接入日志事件的局部更新，并调整条目高度样式。
  实施记录：按任务 ID 和项目名定位；条目自适应一至两行，未变化的进度不触发控件刷新。
- [x] 运行新增测试，检查 UTF-8、UI 配置哈希和最终 diff。
  实施记录：4 个新增测试通过，覆盖八类阶段、四类终态、迟到日志、同名任务隔离及窄侧栏实际渲染；UI 配置哈希保持一致，diff 检查通过。

验证命令：`conda run -n latextrans python -m unittest tests.test_tui_state.TuiStateTests.test_extract_progress_text_normalizes_known_progress_logs tests.test_tui_state.TuiStateTests.test_project_progress_is_updated_and_cleared_on_terminal_event tests.test_tui_project_progress`
