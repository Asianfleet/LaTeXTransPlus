# 论文级术语表最小闭环设计

## 背景

`docs/term-scan.md` 记录了当前术语一致性问题：同一篇论文中，`power sampling` 可能被译成“幂采样”“功率采样”“幂抽样”等不同说法。现有术语逻辑主要内嵌在 `TranslatorAgent`：

- 启动翻译时读取 `user_term`、arXiv category 词表或 `terms/default.csv`。
- `terms` 模式会把整个 `term_dict` 注入 prompt。
- `update_term` 的动态术语更新发生在翻译后，不能在首次翻译前锁定论文核心术语。
- 现有 validator 只检查 LaTeX 命令、placeholder 和括号结构，不检查术语一致性。

本设计按第一版最小闭环实现：翻译前生成论文级术语表，翻译后用户可修改术语表，然后通过显式命令全量重译。暂不加入术语 validator 和局部重译。

## 目标

- 在正式翻译前，为当前论文生成 `project_terms.csv`。
- `project_terms.csv` 使用两列 CSV，方便用户直接编辑。
- 首次翻译默认自动生成术语表并继续执行。
- 支持配置为“生成术语表后暂停”，让用户先审核再翻译。
- 用户修改 `project_terms.csv` 后，可通过显式 CLI 参数触发全量重译。
- 重译复用已有 parser map 和当前 `project_terms.csv`，重新生成 PDF。
- 保持现有 validator retry 流程，不在第一版引入 `term_mismatch`。

## 非目标

- 不实现术语一致性 validator。
- 不实现按术语影响范围的局部重译。
- 不保存复杂术语 metadata，例如 `locked`、`confidence`、`forbidden_targets`、来源位置。
- 不提供交互式 CSV 编辑器。
- 不改变 PDF 编译和 LaTeX 结构校验的主体语义。

## 配置

新增配置段：

```toml
[terminology]
enabled = true
review_before_translate = false
max_llm_candidates = 30
```

字段含义：

- `enabled`：是否在首次翻译前生成论文级术语表。
- `review_before_translate`：是否生成 `project_terms.csv` 后暂停 workflow，等待用户审核。
- `max_llm_candidates`：最多让 LLM 为多少个未知候选术语生成中文译名。

默认行为是 `enabled=true` 且 `review_before_translate=false`，即生成术语表后直接继续首次翻译。

## CLI 行为

新增显式重译参数：

```powershell
latextrans --project D:\paper --retranslate-with-terms
```

该参数语义：

- 根据 `--project`、`output_dir` 和 `target_language` 找到对应输出目录，例如 `outputs/ch_paper`。
- 要求输出目录中已存在 `sections_map.json`、`captions_map.json`、`envs_map.json` 和 `project_terms.csv`。
- 不重新解析原始 LaTeX 项目。
- 使用当前 `project_terms.csv` 全量重新翻译所有可翻译 part。
- 重新运行现有 validator retry。
- 重新生成 PDF。

若找不到必要文件，命令直接失败并给出清晰错误，不静默退回首次翻译流程。

## 术语表格式

第一版只生成 CSV：

```csv
English Term,Chinese Translation
power sampling,幂采样
power distribution,幂分布
distribution sharpening,分布锐化
```

读取规则：

- 第一行如果是 header，则跳过。
- 没有 header 的两列 CSV 也兼容。
- 空行跳过。
- 非两列行记录 warning 并跳过，不中断流程。
- 英文术语按 case-insensitive 去重。
- 高优先级来源已写入的术语不能被低优先级来源覆盖。

## 术语优先级

`TranslatorAgent.build_term_dict()` 调整为以下优先级：

```text
user_term > project_terms.csv > arXiv category 词表 > terms/default.csv > placeholder 自保护项
```

说明：

- `user_term` 仍是全局最高优先级。
- `project_terms.csv` 是论文级术语表，优先级高于 category 和 default。
- category 词表和 default 词表只补充缺失术语。
- placeholder 自保护项最后加入，确保 `<PLACEHOLDER_...>` 保持不变。

## TerminologyAgent

新增 `src/agents/tool_agents/terminology_agent.py`。

职责：

- 读取 parser 生成的 `sections_map.json`、`captions_map.json` 和 `envs_map.json`。
- 从标题、摘要、section heading、caption、section 开头段落和可翻译 environment 中收集英文文本。
- 匹配既有词表中的英文术语。
- 用轻量规则抽取 2-5 个词的英文短语候选。
- 对未命中既有词表的候选，最多选取 `max_llm_candidates` 个让 LLM 生成建议中文译名。
- 写出 `project_terms.csv`。

候选抽取第一版保持保守：

- 优先 multi-word term，不锁定单个多义词，例如不生成 `power -> 幂`。
- 优先包含领域词的短语，例如 `sampling`、`distribution`、`model`、`algorithm`、`likelihood`、`reward`、`verifier`。
- 过滤明显泛化短语，例如 `this paper`、`our method`、`the result`。
- 专名、模型名、数据集名和 benchmark 可保留英文作为译名。

LLM 失败时不阻塞首次翻译：已命中既有词表的术语仍写入；未知候选可跳过或保留英文译名。

## 首次翻译数据流

```text
prepare project
-> ParserAgent 生成 *_map.json
-> TerminologyAgent 生成 project_terms.csv
-> 如果 review_before_translate=true：停止并提示用户审核
-> TranslatorAgent 读取 project_terms.csv + 既有词表
-> ValidatorAgent 保持现有结构校验
-> GeneratorAgent 生成 PDF
```

`review_before_translate=true` 时，workflow 返回暂停状态，不进入 translator，也不生成 PDF。消息应提示用户编辑 `project_terms.csv` 后使用重译命令继续。

## 全量重译数据流

```text
resolve project + output/ch_project
-> 确认 parser map 和 project_terms.csv 存在
-> 清空或覆盖旧 trans_content
-> TranslatorAgent 全量重译
-> ValidatorAgent
-> GeneratorAgent 覆盖生成新 PDF
```

重译不删除输出目录，不删除用户编辑过的 `project_terms.csv`，只覆盖 map 中的 `trans_content` 和最终 PDF。

## 错误处理

- `project_terms.csv` 不存在：`--retranslate-with-terms` 失败，提示先运行首次翻译或补充术语表。
- parser map 不存在：失败，提示该输出目录不可复用。
- CSV 行格式错误：记录 warning，跳过该行。
- LLM 术语生成失败：保留既有词表命中的术语；未知候选跳过或译名保留英文。
- `review_before_translate=true`：workflow 返回暂停状态，不标记为普通翻译成功。
- 全量重译仍沿用现有 validator retry 与 PDF 生成策略。

## 测试计划

新增或调整 `unittest`：

1. `TerminologyAgent` 单测
   - 能从 section/caption/env 中抽取候选术语。
   - 能合并既有词表命中。
   - LLM 失败时不阻塞术语表生成。

2. CSV 读写单测
   - 支持 header 与无 header。
   - 空行跳过。
   - 非两列行 warning 后跳过。
   - case-insensitive 去重保持高优先级。

3. `TranslatorAgent.build_term_dict()` 单测
   - 验证 `user_term > project_terms.csv > category > default`。
   - 验证 placeholder 自保护项仍存在。

4. `CoordinatorAgent` 单测
   - 首次流程会在 parser 后调用 `TerminologyAgent`。
   - `review_before_translate=true` 时不进入 translator。
   - `terminology.enabled=false` 时保持旧流程。

5. Runtime/CLI 轻量测试
   - `--retranslate-with-terms` 进入复用输出目录的全量重译路径。
   - 缺少 `project_terms.csv` 或 parser map 时返回清晰失败。

6. 回归验证
   - `python -m unittest discover tests` 必须通过。

## 兼容性

- 旧配置缺少 `[terminology]` 时使用默认开启术语表生成的行为。
- 用户仍可用 `user_term` 覆盖论文级术语。
- 现有 `terms/*.csv` 文件格式不变。
- 现有 validator report 格式不变。
- 第一版不改变用户可配置的 `mode` 取值，但只要 `project_terms.csv` 存在，`TranslatorAgent` 就必须把它并入术语词表并在 prompt 中启用术语约束。这样可以避免生成了论文级术语表却没有实际影响翻译。

## 风险

- 默认生成术语表会增加首次翻译前的 LLM 调用，`max_llm_candidates` 用于控制成本。
- CSV 只有两列，无法表达 forbidden targets 和 confidence，后续如果引入术语 validator 需要扩展格式或增加 JSON sidecar。
- 全量重译成本高，但符合第一版边界；后续可基于术语命中范围做局部重译。
- 规则抽取可能产生噪声术语，因此第一版应保守过滤，并允许用户通过 CSV 修改。
