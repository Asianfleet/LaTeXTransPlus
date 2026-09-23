# Lite Protected Token Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Lite Markdown 的保护标记改为带类型的短标记，并在标记校验失败时重试单个翻译块。

**Architecture:** `lite_markdown` 负责生成块内唯一的 `[[LTP_<TYPE>_<N>]]` 标记，并以专用异常报告缺失或重复。`MarkdownTranslatorAgent` 只捕获该异常，在重新提交原始 protected Markdown 后重试当前块；网络重试与 Heavy 校验流程保持不变。

**Tech Stack:** Python 3.10+、`unittest`、`asyncio`、TOML 配置。

## Global Constraints

- 仅使用 `latextrans` conda 环境运行项目测试。
- 不重试整个 Lite 工作流，不生成部分 `translated.md`，不改变 Heavy 行为。
- 所有新函数与类包含简短 docstring；配置通过 Lite runtime fields 和 TUI schema 生效。

---

### Task 1: Typed token and validation diagnostics

**Files:**
- Modify: `src/engines/lite_markdown.py`
- Test: `tests/test_lite_markdown.py`

**Interfaces:**
- Produces: `ProtectedTokenValidationError(ValueError)`，包含缺失与重复 token 信息。
- Produces: `protect_markdown()` 生成 `[[LTP_CODE_0]]`、`[[LTP_MATH_1]]` 等块内唯一标记。

- [x] **Step 1: Write failing tests**

验证代码、公式和 URL 各自产生可读类型标记；验证源文已有完全相同的 `[[LTP_CODE_0]]` 时生成器避让；验证缺失和重复标记抛出专用异常。

- [x] **Step 2: Run focused Markdown tests and verify failure**

Run: `conda run -n latextrans python -m unittest tests.test_lite_markdown`

Expected: FAIL，因为当前标记带 UUID 且不存在专用异常。

- [x] **Step 3: Implement deterministic typed tokens**

移除 UUID 命名空间；根据被保护内容的类型生成候选标记，碰撞时递增块内序号。恢复函数收集缺失与重复 token 后抛出 `ProtectedTokenValidationError`。

- [x] **Step 4: Run focused Markdown tests and verify pass**

Run: `conda run -n latextrans python -m unittest tests.test_lite_markdown`

Expected: PASS。

### Task 2: Per-block protected-token retries

**Files:**
- Modify: `src/agents/tool_agents/markdown_translator_agent.py`
- Test: `tests/test_markdown_translator_agent.py`

**Interfaces:**
- Consumes: `ProtectedTokenValidationError` 与 `lite.protected_token_retry_attempts`。
- Produces: 对缺失或重复 token 的每个块最多执行初次请求加 N 次重试；重试使用原始 protected Markdown。

- [x] **Step 1: Write failing async tests**

用注入请求回调模拟“首轮遗漏、次轮正确”和“耗尽重试预算”，断言请求次数、输出原子性和日志等级。

- [x] **Step 2: Run focused translator tests and verify failure**

Run: `conda run -n latextrans python -m unittest tests.test_markdown_translator_agent`

Expected: FAIL，因为当前第一次 `restore_markdown()` 失败会终止任务。

- [x] **Step 3: Implement validation-only retry loop**

在 `_translate_block()` 中围绕请求和恢复建立有限循环；只捕获 `ProtectedTokenValidationError`，在等待后重发原始内容。传输异常继续由现有 provider loop 处理，耗尽后保留严格错误。

- [x] **Step 4: Run focused translator tests and verify pass**

Run: `conda run -n latextrans python -m unittest tests.test_markdown_translator_agent`

Expected: PASS。

### Task 3: Runtime configuration and regression verification

**Files:**
- Modify: `src/engines/base.py`
- Modify: `config/default.toml`
- Modify: `config/template.toml`
- Modify: `src/tui/config.py`
- Modify: `src/tui/config_schema.py`
- Test: `tests/test_engine_config.py`
- Test: `tests/test_tui_config.py`

**Interfaces:**
- Produces: `[lite].protected_token_retry_attempts`，默认 `2`，代表首次请求后的额外重试次数。

- [x] **Step 1: Write failing configuration tests**

验证该配置仅传入 Lite effective runtime config，并验证 UI 配置迁移为已有 Lite section 补充默认值。

- [x] **Step 2: Run focused configuration tests and verify failure**

Run: `conda run -n latextrans python -m unittest tests.test_engine_config tests.test_tui_config`

Expected: FAIL，因为该字段当前未转发且迁移不补默认值。

- [x] **Step 3: Implement configuration forwarding and TUI field**

将字段加入 Lite runtime fields、默认与模板 TOML、UI migration defaults，以及 Lite 设置 schema；读取时校验非负整数。

- [ ] **Step 4: Run focused and full regression tests**

Run: `conda run -n latextrans python -m unittest tests.test_lite_markdown tests.test_markdown_translator_agent tests.test_engine_config tests.test_tui_config tests.test_lite_engine`

Run: `conda run -n latextrans python -m unittest discover tests`

Expected: PASS。

## Implementation Notes

- [x] 使用 `[[LTP_<TYPE>_<N>]]` 标记替换 UUID 标记；按类型独立编号并避让源文本中的完全相同标记。
- [x] `restore_markdown()` 汇总缺失与重复标记后抛出 `ProtectedTokenValidationError`，翻译器仅对该异常重试当前块。
- [x] 增加 `lite.protected_token_retry_attempts`，默认额外重试 2 次，并接入 Lite runtime、默认/模板配置与 TUI 设置页。
- [x] 组合回归验证通过：78 个相关测试，且默认/模板 TOML 可解析。
- [ ] `python -m unittest discover tests` 已启动两次；两轮运行的最终摘要均未被终端采样保留，未将其视为已验证通过。
