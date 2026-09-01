# Task 4 实现报告

## 状态

已完成项目管理表多选列、顶部操作按钮和按钮状态规则。

## 实现

- 新增 `ProjectManagementTable`，单击行切换选中状态。
- App 使用 `(task_id, project_name)` 维护 `selected_project_keys`。
- 项目表列顺序调整为“选中 / 项目 / 状态 / 任务 id”。
- 刷新表格时保留仍存在项目的选择，清除失效身份。
- 终止、删除、重新翻译按钮按全选项目状态动态启用；空选择或混合运行状态时禁用。
- 按钮事件已预留给后续终止、删除和重译实现。

## 验证

`conda run -n latextrans python -m unittest tests.test_tui_app.TuiProjectManagerTests -v`

结果：3 个测试通过。

## 顾虑

按钮具体操作由 Task 5 接入；当前仅负责控件、选择身份和可用性计算。
