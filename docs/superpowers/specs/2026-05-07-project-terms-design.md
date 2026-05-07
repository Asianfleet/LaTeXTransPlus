# 论文级术语表最小闭环设计

## 背景

`docs/term-scan.md` 记录了当前术语一致性问题：同一篇论文中，源语术语可能在目标语里被翻译成多种说法。例如在 `source_language=en`、`target_language=ch` 时，`power sampling` 可能被译成“幂采样”“功率采样”“幂抽样”。现有术语逻辑主要内嵌在 `TranslatorAgent`：

- 启动翻译时读取 `user_term`、arXiv category 词表或 `terms/default.csv`。
- `terms` 模式会把整个 `term_dict` 注入 prompt。
- `update_term` 的动态术语更新发生在翻译后，不能在首次翻译前锁定论文核心术语。
- 现有 validator 只检查 LaTeX 命令、placeholder 和括号结构，不检查术语一致性。

本设计按第一版最小闭环实现：翻译前根据当前 `source_language` 和 `target_language` 生成论文级术语表，翻译后用户可修改术语表，然后通过显式命令全量重译。暂不加入术语 validator 和局部重译。

## 目标

- 在正式翻译前，为当前论文生成 `project_terms.csv`。
- `project_terms.csv` 使用两列 CSV，方便用户直接编辑。
- 为需要 LLM 生成或选择译名的术语生成 `project_terms_decisions.json`，记录候选译法、最终采用译法和原因。
- 首次翻译默认自动生成术语表并继续执行。
- 支持配置为“生成术语表后暂停”，让用户先审核再翻译。
- 用户修改 `project_terms.csv` 后，可通过显式 CLI 参数触发全量重译。
- 重译复用已有 parser map 和当前 `project_terms.csv`，重新生成 PDF。
- 保持现有 validator retry 流程，不在第一版引入 `term_mismatch`。

## 非目标

- 不实现术语一致性 validator。
- 不实现按术语影响范围的局部重译。
- 不把复杂术语 metadata 写入用户编辑用的 `project_terms.csv`。诊断和决策信息写入独立 JSON 日志。
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
- `max_llm_candidates`：最多让 LLM 为多少个未知候选术语生成目标语译名。

默认行为是 `enabled=true` 且 `review_before_translate=false`，即生成术语表后直接继续首次翻译。

## CLI 行为

新增显式重译参数：

```powershell
latextrans --project D:\paper --retranslate-with-terms
```

该参数语义：

- 根据 `--project`、`output_dir` 和 `target_language` 找到对应输出目录，例如 `outputs/<target_language>_paper`。
- 要求输出目录中已存在 `sections_map.json`、`captions_map.json`、`envs_map.json` 和 `project_terms.csv`。
- 如果存在 `project_terms_decisions.json`，保留它作为术语生成审计日志；全量重译不会覆盖它，除非用户显式重新生成术语表。
- 不重新解析原始 LaTeX 项目。
- 使用当前 `project_terms.csv` 全量重新翻译所有可翻译 part。
- 重新运行现有 validator retry。
- 重新生成 PDF。

若找不到必要文件，命令直接失败并给出清晰错误，不静默退回首次翻译流程。

## 术语表格式

第一版的用户编辑用术语表主文件是 CSV：

以下示例只展示 `source_language=en`、`target_language=ch` 的内容形态；其他语言对仍使用同样的两列表头和“源语术语 -> 目标语译名”语义。

```csv
Source Term,Target Translation
power sampling,幂采样
power distribution,幂分布
distribution sharpening,分布锐化
```

读取规则：

- 第一行如果是 header，则跳过。
- 没有 header 的两列 CSV 也兼容。
- 空行跳过。
- 非两列行记录 warning 并跳过，不中断流程。
- 源语术语去重必须基于语言安全的归一化：有大小写的语言可以做 case-insensitive 去重；没有大小写或大小写折叠可能改变语义的语言保持精确文本去重。
- 高优先级来源已写入的术语不能被低优先级来源覆盖。
- CSV 两列语义固定为 `source_language` 术语和 `target_language` 译名，不得在代码里写死 English/Chinese。

## 术语决策日志

`TerminologyAgent` 需要额外写出 `project_terms_decisions.json`。该文件是审计日志，不是用户主要编辑入口；用户仍主要修改 `project_terms.csv`。

日志记录对象：

- 需要 LLM 生成或选择目标语译名的候选术语。
- 可选记录来自既有词表的术语命中，但必须标记 `decision_source="existing_glossary"`，不能混同为 LLM 生成结果。

建议结构：

```json
{
  "source_language": "en",
  "target_language": "ch",
  "paper_context": {
    "project_name": "2510.14901",
    "title": "Reasoning by Sampling...",
    "abstract": "We propose power sampling...",
    "keywords": [],
    "category": ["cs.AI"]
  },
  "decisions": [
    {
      "source_term": "power sampling",
      "candidate_translations": ["幂采样", "功率采样", "幂抽样"],
      "selected_translation": "幂采样",
      "reason": "The paper defines power sampling through a power distribution, so the target term should preserve the mathematical power sense rather than physical power.",
      "decision_source": "llm",
      "contexts": [
        "We propose power sampling as a training-free inference-time algorithm...",
        "Power sampling matches or exceeds RL post-training..."
      ]
    }
  ]
}
```

日志规则：

- `paper_context` 必须来自当前论文和当前语言配置，不得写死语言对。
- `title`、`abstract`、`keywords` 尽量从 parser 输出中提取；如果缺失，则使用空字符串或空数组。
- `category` 可以来自 arXiv category 配置；本地项目没有 category 时使用空数组。
- `candidate_translations`、`selected_translation` 和 `reason` 必须来自 LLM 结构化输出或明确的 fallback 规则。
- 如果 LLM 失败且候选被跳过，不写入 `project_terms.csv`，但可以在 JSON 中记录 `decision_source="llm_failed"` 和失败原因。
- `--retranslate-with-terms` 默认只读取用户修改后的 `project_terms.csv`，不根据 JSON 反推术语。

## 术语优先级

`TranslatorAgent.build_term_dict()` 调整为以下优先级：

```text
user_term > project_terms.csv > arXiv category 词表 > terms/default.csv > placeholder 自保护项
```

说明：

- `user_term` 仍是全局最高优先级。
- `project_terms.csv` 是论文级术语表，优先级高于 category 和 default。
- category 词表和 default 词表只补充缺失术语。
- 现有 `terms/*.csv` 和 `terms/default.csv` 是历史 English-to-Chinese 资源，只能在 `source_language=en` 且 `target_language=ch` 时默认加载。其他语言对不能默认加载这些词表，除非后续显式增加带语言对标识的词表机制。
- placeholder 自保护项最后加入，确保 `<PLACEHOLDER_...>` 保持不变。

## TerminologyAgent

新增 `src/agents/tool_agents/terminology_agent.py`。

职责：

- 读取 parser 生成的 `sections_map.json`、`captions_map.json` 和 `envs_map.json`。
- 从标题、摘要、section heading、caption、section 开头段落和可翻译 environment 中收集源语文本。
- 提取论文上下文：标题、摘要、关键词、项目名、可用 category，以及候选术语出现的局部上下文。
- 匹配适用于当前语言对的既有词表中的源语术语。
- 按当前 `source_language` 选择候选抽取策略。
- 对未命中既有词表的候选，最多选取 `max_llm_candidates` 个让 LLM 生成建议目标语译名。请求中必须包含论文元信息、摘要和该术语的若干局部上下文，以提高译名准确度。
- 写出 `project_terms.csv`。
- 写出 `project_terms_decisions.json`，记录 LLM 候选译法、最终采用译法和原因。

候选抽取第一版保持保守：

- 对 `source_language=en`，可以使用英文 2-5 词短语规则，优先 multi-word term，不锁定单个多义词，例如不生成 `power -> 幂`。
- 英文源语下可优先包含领域词的短语，例如 `sampling`、`distribution`、`model`、`algorithm`、`likelihood`、`reward`、`verifier`。
- 英文源语下过滤明显泛化短语，例如 `this paper`、`our method`、`the result`。
- 对非英文源语，不套用英文 noun phrase 或空格分词规则；第一版使用适用词表匹配和 LLM 基于上下文提名候选术语。
- 专名、模型名、数据集名和 benchmark 可保留源语原文作为目标语译名。

LLM 失败时不阻塞首次翻译：已命中既有词表的术语仍写入；未知候选可跳过或保留源语原文作为译名。

LLM 术语译名生成的输入应至少包含：

- `source_language` 和 `target_language` 的可读语言名。
- 论文标题、摘要、关键词和可用 category。
- 候选术语列表。
- 每个候选术语的 1-3 条局部上下文。
- 已确定的相邻术语表，帮助 LLM 保持译名体系一致。

LLM 输出必须是结构化 JSON 或可严格解析为 JSON 的内容；解析失败时按 LLM 失败处理，不从自由文本里猜测译名。

## 首次翻译数据流

```text
prepare project
-> ParserAgent 生成 *_map.json
-> TerminologyAgent 生成 project_terms.csv 和 project_terms_decisions.json
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
- LLM 术语生成失败：保留既有词表命中的术语；未知候选跳过或译名保留源语原文，并在 `project_terms_decisions.json` 记录失败状态。
- `project_terms_decisions.json` 写入失败：不阻塞翻译，但记录 warning；`project_terms.csv` 仍是翻译使用的权威术语表。
- `review_before_translate=true`：workflow 返回暂停状态，不标记为普通翻译成功。
- 全量重译仍沿用现有 validator retry 与 PDF 生成策略。

## 测试计划

新增或调整 `unittest`：

1. `TerminologyAgent` 单测
   - 能从 section/caption/env 中抽取候选术语。
   - 能合并既有词表命中。
   - LLM 失败时不阻塞术语表生成。
   - 非英文源语不会走英文短语抽取规则。
   - LLM 译名生成请求包含论文标题、摘要、关键词、category 和候选术语局部上下文。
   - 能写出 `project_terms_decisions.json`，包含候选译法、最终采用译法和原因。
   - LLM 失败时 JSON 日志记录失败状态，CSV 不写入不可确认的译名。

2. CSV 读写单测
   - 支持 header 与无 header。
   - 空行跳过。
   - 非两列行 warning 后跳过。
   - 有大小写语言的 case-insensitive 去重保持高优先级。
   - CSV header 和内部字段使用 `Source Term` / `Target Translation`，不写死 English/Chinese。

3. `TranslatorAgent.build_term_dict()` 单测
   - 验证 `user_term > project_terms.csv > category > default`。
   - 验证 placeholder 自保护项仍存在。
   - 验证 `terms/default.csv` 和 category 词表只在 English-to-Chinese 语言对默认加载。
   - 验证非 English-to-Chinese 语言对仍可加载 `user_term` 与 `project_terms.csv`。

4. `CoordinatorAgent` 单测
   - 首次流程会在 parser 后调用 `TerminologyAgent`。
   - `review_before_translate=true` 时不进入 translator。
   - `terminology.enabled=false` 时保持旧流程。

5. Runtime/CLI 轻量测试
   - `--retranslate-with-terms` 进入复用输出目录的全量重译路径。
   - 缺少 `project_terms.csv` 或 parser map 时返回清晰失败。
   - `--retranslate-with-terms` 不依赖 `project_terms_decisions.json`，用户修改后的 CSV 是重译权威输入。

6. 回归验证
   - `python -m unittest discover tests` 必须通过。

## 兼容性

- 旧配置缺少 `[terminology]` 时使用默认开启术语表生成的行为。
- 用户仍可用 `user_term` 覆盖论文级术语。
- 现有 `terms/*.csv` 文件格式不变，但它们被视为 English-to-Chinese 默认词表，不对其他语言对自动生效。
- 现有 validator report 格式不变。
- 第一版不改变用户可配置的 `mode` 取值，但只要 `project_terms.csv` 存在，`TranslatorAgent` 就必须把它并入术语词表并在 prompt 中启用术语约束。这样可以避免生成了论文级术语表却没有实际影响翻译。
- 新增 `project_terms_decisions.json` 是辅助审计文件，不改变 `project_terms.csv` 的用户编辑入口，也不作为重译时的权威术语来源。

## 风险

- 默认生成术语表会增加首次翻译前的 LLM 调用，`max_llm_candidates` 用于控制成本。
- CSV 只有两列，无法表达 forbidden targets 和 confidence；第一版用 `project_terms_decisions.json` 保存决策说明，但后续如果引入术语 validator，仍可能需要扩展 schema。
- 全量重译成本高，但符合第一版边界；后续可基于术语命中范围做局部重译。
- 规则抽取可能产生噪声术语，因此第一版应保守过滤，并允许用户通过 CSV 修改。
- 多语言术语抽取质量取决于语言对。第一版明确避免把英文规则套到所有源语；非英文源语主要依赖适用词表和 LLM 候选提名。
- 论文元信息和摘要提取可能不完整；实现时必须允许缺失字段，不应因为缺少摘要而阻塞术语表生成。
