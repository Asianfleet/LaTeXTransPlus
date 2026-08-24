# LLM 自定义 JSON 请求参数设计

## 背景

当前项目的 LLM 请求分散在 `ParserAgent`、`TranslatorAgent` 和 `TerminologyAgent` 中。三者都直接组装请求体，字段名相近但不完全一致，后续如果要给不同供应商加额外请求参数，很容易出现漏配或行为不一致。

用户希望新增一个配置开关，用来注入“思考模式”相关参数，但不想把它绑定成单一布尔值或固定 provider 选项。更合适的方式是允许在配置中写一段自定义 JSON，让用户按目标接口自行传入原始请求字段，例如：

```toml
[llm_config]
custom_json = '{"reasoning_effort": "high"}'
```

或者：

```toml
[llm_config]
custom_json = '{"enable_thinking": true}'
```

## 目标

- 新增 `llm_config.custom_json` 配置项。
- 允许用户以 JSON object 的形式追加任意合法请求字段。
- 对 Parser、Translator、Terminology 三类 LLM 请求全部生效。
- 保留程序内部生成的核心字段，不允许被配置覆盖。
- 对 JSON 语法错误、类型错误和字段冲突给出明确报错。
- 同步更新默认配置、TUI 配置页和 README。

## 非目标

- 不新增 provider 下拉选项。
- 不做供应商自动识别。
- 不把 `custom_json` 解释成固定的 `thinking_mode` 布尔值。
- 不允许配置覆盖 `model`、`messages`、`temperature`、`max_tokens`、`max_new_tokens` 等内部字段。
- 不改动现有请求的重试逻辑、日志逻辑或业务流程。

## 推荐方案

在 `llm_config` 下新增一个字符串配置项 `custom_json`。该值必须是 JSON object 字符串，加载配置时解析为 Python `dict`，然后在每次 LLM 请求构造完成后，合并到请求体顶层。

合并规则：

- 先构造程序内部请求体。
- 再把 `custom_json` 解析结果逐键合并进去。
- 若自定义 JSON 中包含已存在的内部字段，直接报错。
- 若 `custom_json` 为空字符串或仅含空白，则视为未配置。

示例：

```toml
[llm_config]
custom_json = '{"enable_thinking": true}'
```

最终请求体会变成：

```json
{
  "model": "...",
  "messages": [...],
  "temperature": 0.7,
  "enable_thinking": true
}
```

这个方案比 provider 专用开关更通用，也比把配置拆成多个布尔字段更容易扩展。

## 设计细节

### 配置语义

`custom_json` 的定位是“额外请求字段”，不是“完整请求体”。

允许的输入：

- 空字符串
- 任何合法 JSON object 字符串

拒绝的输入：

- JSON array
- 字符串、数字、布尔值、`null`
- 非法 JSON

### 冲突规则

以下字段视为内部保留字段，不能被 `custom_json` 覆盖：

- `model`
- `messages`
- `temperature`
- `max_tokens`
- `max_new_tokens`

如果用户的 JSON 中出现这些键，配置加载应直接失败，并指出冲突字段名。

### 作用范围

`custom_json` 对以下三类请求全部生效：

- `ParserAgent`
- `TranslatorAgent`
- `TerminologyAgent`

TranslatorAgent 中所有向 LLM 发出的请求都必须统一应用，包括：

- 正式翻译
- 重翻译
- 术语提取
- 摘要/辅助请求

### 配置入口

需要同步更新：

- `config/default.toml`
- `config/template.toml`
- `src/tui/config_schema.py`
- `README.md`
- `README_ZH.md`

TUI 中建议使用多行文本输入，方便粘贴 JSON。

## 架构设计

### 统一解析与合并 helper

建议在共享配置模块中新增 helper，负责：

- 读取 `llm_config.custom_json`
- 解析 JSON
- 校验必须是 object
- 校验保留字段冲突
- 返回可合并的 `dict`

这个 helper 应被 `runtime.load_runtime_config()` 和三类 agent 共享使用，避免 `main.py`、`runtime.py` 和各个 agent 各自处理时再次分叉。

### 请求构造 helper

建议再抽一个小的请求体合并函数，负责把基础 payload 和自定义 payload 合并成最终 JSON。

行为应当固定为：

- 基础 payload 优先
- `custom_json` 只追加新字段
- 冲突即报错

这样三类 agent 只需要专注各自的业务 payload，不必重复写合并逻辑。

## 错误处理

- `custom_json` 不是合法 JSON 时，配置加载失败。
- `custom_json` 解析后不是 object 时，配置加载失败。
- `custom_json` 与保留字段冲突时，配置加载失败。
- 若配置文件中未写 `custom_json` 或写空字符串，则视为不启用。

错误信息应明确指出问题字段和配置位置，便于用户直接修改 TOML。

## 测试设计

新增测试应覆盖：

- `custom_json` 为空时不改变请求体。
- `custom_json` 解析为 object 后会追加到请求体。
- 冲突字段会报错。
- 非 object JSON 会报错。
- 非法 JSON 会报错。
- Parser、Translator、Terminology 三类 agent 都能读取并应用同一份配置。

建议补充：

- `tests/test_runtime_config.py`
- `tests/test_tui_app.py`
- `tests/test_terminology_agent.py`
- `tests/test_translator_retry_prompt.py`
- `tests/test_cli_language_args.py` 或相关 CLI 配置测试

## 兼容性

- 不配置 `custom_json` 时，现有行为保持不变。
- 现有 `model`、`api_key_env`、`base_url` 语义不变。
- 不改变 API key 解析方式。
- 不改变现有请求重试和失败回退策略。

## 决策总结

本次采用“`llm_config.custom_json` 追加式 JSON 配置”的方式实现思考模式和其他扩展请求参数：

- 语义是额外字段，不是完整请求体。
- 三类 LLM 请求统一生效。
- 发生保留字段冲突时直接报错。
- 配置和 TUI 仅提供原始 JSON 编辑入口，不做 provider 绑定。

这个设计能覆盖 OpenAI 兼容接口、硅基流动以及未来其他兼容 provider 的扩展字段，同时保持当前请求结构清晰可控。
