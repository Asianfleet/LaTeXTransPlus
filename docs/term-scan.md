## USER

outputs\ch_2510.14901 看一下这篇论文的翻译情况

## LLM

整体看，`outputs\ch_2510.14901` 这次翻译是成功完成的。

生成状态：
- 最终 PDF 已生成：[ch_2510.14901.pdf](D:/Workspace/tools/LaTeXTrans/outputs/ch_2510.14901/ch_2510.14901.pdf)
- 日志显示 17 个 section 全部翻译完成，首次校验剩 4 个问题，重译后剩余错误为 0。
- [errors_report.json](D:/Workspace/tools/LaTeXTrans/outputs/ch_2510.14901/errors_report.json) 是空数组 `[]`。
- PDF 共 21 页，能抽取到中文正文，标题、摘要、引言、图注、主要章节都已中文化。

需要注意的翻译质量问题：
- 术语不统一：`power sampling` 被译成了“幂采样”“功率采样”“幂抽样”，建议统一成“幂采样”。
- 附录里的部分示例题目和模型回答仍是英文，例如 [main.tex](D:/Workspace/tools/LaTeXTrans/outputs/ch_2510.14901/2510.14901/main.tex:610) 附近。这可能是原文实验样例保留英文，也可能是漏译，取决于你希望附录样例是否也全部中文化。
- 编译日志没有 fatal error，但有一些普通排版 warning，包括 `Underfull hbox/vbox`、float 位置调整，以及一处 `Float too large for page by 36.9151pt`：[main.log](D:/Workspace/tools/LaTeXTrans/outputs/ch_2510.14901/2510.14901/build_pdflatex/main.log:1328)。PDF 已成功生成，这类主要是版面质量问题。
- PDF 文本抽取里 `Website/Code` 图标显示成奇怪字符，这是 FontAwesome 图标的文本抽取问题，不一定代表视觉渲染坏了。

结论：这篇论文的翻译流程和编译都成功，主体翻译完整度较高；主要需要人工修的是术语一致性，以及决定附录英文实验样例是否要翻译。

## USER

如何彻底解决“幂采样/功率采样/幂抽样”这种一致性问题？

## LLM

要彻底解决，不能只靠“翻译时提醒模型保持术语一致”。这类问题需要做成一条确定性的术语链路：

**推荐方案：翻译前锁定术语 + 翻译中强约束 + 翻译后校验重试**

1. **翻译前生成项目级术语表**
   在正式翻译 section 前，先扫描全文的标题、摘要、章节标题、图表 caption、关键词密集段落，抽取候选术语，生成 `project_terms.csv` 或 `term_dict.json`。

   对这篇论文应至少锁定：

   ```csv
   power sampling,幂采样
   power sampler,幂采样器
   power distribution,幂分布
   sharpened distribution,锐化分布
   distribution sharpening,分布锐化
   resampling,重采样
   sampling,采样
   ```

   注意不要把单独的 `power` 固定成“幂”，否则可能误伤普通语境；应优先锁定 multi-word term，比如 `power sampling`、`power distribution`。

2. **明确术语优先级**
   当前项目里已有 `terms/*.csv`、`user_term`、动态抽取术语。应规定优先级：

   ```text
   用户术语表 > 项目级术语表 > arXiv category 术语表 > default.csv > 动态抽取候选
   ```

   动态抽取的术语只能“补充候选”，不能覆盖已锁定术语。否则第一处译成“功率采样”，后面就可能被错误扩散。

3. **翻译时只注入相关术语，不塞整个大词表**
   现在 `TranslatorAgent` 会把整个 `term_dict` 放进 prompt。更稳的方式是：对当前 section/caption/env 做 source-term 匹配，只把命中的术语注入 prompt，并按长度降序排列。

   例如当前段落含有 `power sampling` 和 `sampling` 时，prompt 里应先给：

   ```text
   power sampling -> 幂采样
   sampling -> 采样
   ```

   这样可以避免模型先把 `sampling` 泛化掉，再把 `power sampling` 拆错。

4. **增加术语一致性 validator**
   这是彻底性的关键。生成 `trans_content` 后，validator 应检查：

   ```text
   如果 source 中出现 locked term，则 target 中必须出现对应 canonical translation。
   ```

   例如 source 有 `power sampling`，target 里必须有“幂采样”。如果出现“功率采样”或“幂抽样”，生成 `term_mismatch`：

   ```json
   {
     "part": "sec",
     "num_or_ph": "4_1",
     "issue": "term_mismatch",
     "source_term": "power sampling",
     "expected": "幂采样",
     "found": ["功率采样", "幂抽样"]
   }
   ```

   然后走现有 validator retry 路径，让 LLM 只修这一类问题。

5. **译后可选做安全替换，但不能粗暴全文 replace**
   对“功率采样 -> 幂采样”这种确定错误，可以做后处理修复，但必须只作用于自然语言文本，不要碰 LaTeX command、label、citation、URL、代码块、数学公式。

   所以更推荐：validator 报错后重译相关块，而不是直接对 `main.tex` 全局替换。

**为什么当前逻辑不够**

你刚才指出的 `update_term` bug 只是一个入口问题。即使它打开了，也还有结构性问题：

- 翻译是并发的，动态术语抽取顺序不稳定。
- 动态术语只新增不覆盖，早期错误术语可能保留下来。
- 没有术语一致性 validator，模型偶尔不遵守 glossary 也不会被抓出来。
- `power sampling` 这类短语术语如果不预先锁定，模型很容易拆成 `power=功率`、`sampling=采样`。

**落地顺序**

我建议按这个顺序做：

1. 先支持项目级 locked glossary，并给 `power sampling -> 幂采样` 这类术语加测试。
2. 再改 translator，只注入当前块命中的术语，最长短语优先。
3. 最后加 `term_mismatch` validator 和 retry，这样术语不一致会像 placeholder/command mismatch 一样被自动修复。

这样才能从“提示模型尽量一致”变成“系统能检测并纠正不一致”。

## USER

你提到 翻译前生成项目级术语表，那具体如何扫描呢

## LLM

可以把“扫描”放在现有流程的 `ParserAgent` 之后、`TranslatorAgent` 之前。此时已经有结构化文件：

- `sections_map.json`
- `captions_map.json`
- `envs_map.json`
- `inputs_map.json`
- `newcommands_map.json`

具体扫描分三层。

**1. 先从结构化 LaTeX 中抽纯文本**

不要直接扫最终 PDF，也不要直接用正则扫整篇 `.tex`。应该复用现有 `_extract_text_from_tex()` 思路：

```text
LaTeX source block
-> 替换 figure/table/env/caption placeholder
-> 去掉 citation、label、ref、math command 等非自然语言
-> LatexNodes2Text 转纯文本
-> 按 section/caption/env 保留来源位置
```

每条文本保留 metadata：

```json
{
  "part": "section",
  "id": "4_1",
  "role": "abstract|title|heading|body|caption|table",
  "text": "We propose power sampling for power distributions..."
}
```

标题、摘要、章节标题、图注权重应更高，因为核心术语通常先出现在这些地方。

**2. 候选术语发现**

推荐组合三种扫描方式。

第一种：匹配已有词表。  
把 `terms/default.csv`、`terms/cs.*.csv`、用户词表读进来，对 source text 做最长短语优先匹配。比如先匹配 `power sampling`，再考虑 `sampling`。这一步用于发现已知术语。

第二种：抽取英文 noun phrase。  
从文本中抽 2 到 5 个词的名词短语，优先保留：

```text
power sampling
power distribution
sharpened distribution
distribution sharpening
base model likelihood
diversity collapse
autoregressive MCMC
Metropolis-Hastings algorithm
```

过滤掉太泛的短语：

```text
this paper
our method
the result
different tasks
```

如果不想引入 NLP 依赖，可以先用轻量规则：

```text
(形容词/名词)* + 名词
含 sampling / distribution / model / likelihood / algorithm / reward / verifier 等领域词
长度 2-5
出现次数 >= 2，或出现在标题/摘要/图注中
```

第三种：LLM 辅助抽取。  
把标题、摘要、章节标题、图注、每节前几段发给 LLM，让它只输出 JSON 候选术语：

```json
[
  {
    "source": "power sampling",
    "suggested_target": "幂采样",
    "reason": "paper-level core method name",
    "confidence": "high"
  }
]
```

LLM 只负责“提名”和“建议译法”，不要直接让它覆盖用户词表。

**3. 合并、评分、锁定**

对候选术语做 canonical normalize：

```text
Power Sampling -> power sampling
power-sampling -> power sampling
power sampler -> power sampler
power samplers -> power sampler
```

然后打分：

```text
score =
  位置权重：标题/摘要/section heading/caption 加分
  频次权重：出现越多越高
  领域词权重：sampling/distribution/MCMC/RL 等加分
  词表命中：已有词表或用户词表命中加分
  LLM 置信度：high 加分
```

最终生成项目级术语表，例如：

```json
{
  "power sampling": {
    "target": "幂采样",
    "locked": true,
    "source_variants": ["Power Sampling", "power-sampling"],
    "forbidden_targets": ["功率采样", "幂抽样"],
    "source": "project_scan",
    "confidence": "high",
    "first_seen": {"part": "section", "id": "title"}
  }
}
```

**关键规则**

不要锁定单词 `power -> 幂`。  
应该锁定短语：

```text
power sampling -> 幂采样
power distribution -> 幂分布
power sampler -> 幂采样器
```

否则会误伤普通语境里的 `power`，比如 computational power、statistical power。

**建议的扫描范围**

第一版可以扫这些就够了：

```text
title
abstract
section/subsection headings
figure/table captions
每个 section 的前 1-2 段
全文中高频 2-5 gram
```

不需要一开始扫所有正文并做复杂 NLP。核心术语通常在这些位置已经足够明显。

最终效果是：翻译前就已经知道 `power sampling` 应固定为“幂采样”，翻译时每个块只要命中这个 source term，就注入对应 glossary；翻译后 validator 再检查有没有“功率采样/幂抽样”这种偏离。

## USER

那抽取完成后，如果术语不在项目的术语表中，那就不知道中文翻译了。这个怎么解决？

## LLM

这个要分清两件事：**抽取术语** 和 **确定译名** 是两步。术语不在现有词表里时，不应该直接跳过，而是进入“候选译名生成与确认”流程。

推荐做成这样的解析顺序：

```text
1. 用户词表 exact match
2. 项目术语表 exact/variant match
3. category 词表 / default 词表 match
4. 规则归一化匹配，比如复数、大小写、连字符
5. LLM 根据上下文生成候选译名
6. 按置信度自动锁定 / 等用户确认 / 保留英文
```

对未知术语，LLM 可以负责“建议译法”，但不要无条件锁定。给它的输入应该包含：

```json
{
  "term": "power sampling",
  "contexts": [
    "We propose power sampling as a training-free inference-time algorithm...",
    "Power sampling matches or exceeds RL post-training..."
  ],
  "paper_title": "Reasoning by Sampling...",
  "nearby_terms": {
    "sampling": "采样",
    "power distribution": "幂分布",
    "MCMC": "MCMC"
  }
}
```

要求它输出结构化结果：

```json
{
  "source": "power sampling",
  "recommended_target": "幂采样",
  "alternatives": ["功率采样", "幂抽样"],
  "forbidden_targets": ["功率采样", "幂抽样"],
  "confidence": "high",
  "reason": "这里的 power 指 p^alpha 的幂分布语义，不是物理功率。"
}
```

然后按置信度处理：

```text
high：自动加入 project_terms.json，并 locked=true
medium：加入候选术语表，翻译前让用户确认
low：不锁定，首次出现可译为“英文术语（English）”或保留英文
```

关键是要有一个**人工确认入口**。比如翻译前生成：

```csv
source,recommended_target,alternatives,confidence,action
power sampling,幂采样,"功率采样;幂抽样",high,auto_lock
distribution sharpening,分布锐化,"分布尖锐化",high,auto_lock
annealed distribution,退火分布,"回火分布",medium,needs_review
```

用户只需要审 medium/low，不必审全部术语。

还需要一套默认翻译策略：

- 模型名、数据集名、benchmark：通常保留英文，如 `MATH500`、`HumanEval`、`Qwen2.5-Math-7B`
- 算法名：常见算法用标准译名，如 `Metropolis-Hastings algorithm -> Metropolis-Hastings 算法`
- 论文自造方法名：优先“中文 + 英文括注”首次出现，例如 `幂采样（power sampling）`
- 多义词：不锁单词，锁短语，例如不要锁 `power -> 幂`，只锁 `power sampling -> 幂采样`

所以完整答案是：**未知术语由 LLM 结合上下文生成候选译名，再通过置信度和人工确认机制进入项目级 locked glossary**。这样既能覆盖新论文里的新术语，又不会让模型随意发明并扩散错误译法。