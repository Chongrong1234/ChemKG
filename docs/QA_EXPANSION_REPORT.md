# 通用化学/科学问答扩充报告

## 结论

当前领域关系数从严格层的 119 条扩展到 184 条去重后的证据绑定问答。没有直接把通用 QA 的 gold answer 灌入 VerifiedFact，避免污染电镀事实层。由于网络访问官方通用 QA 下载源不稳定，本轮采用用户提供的 GPT-5.6 API，以现有严格证据片段生成可追溯的化学/电化学/电镀 QA 层；每题绑定原文 Evidence。

## 生成配置

```text
Model: gpt-5.6-terra
Temperature: 0.2
证据候选: 1,108
生成并去重 QA: 184
覆盖证据: 181
```

部分证据片段因 API 超时或返回无效结构未生成 QA；生成器不会凭空补充缺失证据。每题包含：

- qa_id；
- question；
- answer；
- evidence_id；
- evidence_quote；
- category；
- difficulty；
- source_dataset；
- gold_status。

当前 `gold_status=model_generated_needs_review`，因此这些 QA 是证据绑定候选评测题，不是人工 gold。

## 数据位置

- `qa_layer/qa_full.jsonl`：模型生成原始结果；
- `qa_layer/qa_expanded.jsonl`：去重后的最终 JSONL；
- `qa_layer/qa_expanded.csv`：Neo4j 导入文件；
- `qa_layer/qa.jsonl`：之前的 45 条小规模 QA；
- `kg_pipeline/generate_qa.py`：生成脚本；
- `kg_pipeline/qa_neo4j_import.cypher`：原始 QA 导入脚本。

## Neo4j 导入结果

新增节点：

```text
(:ExpandedEvaluationQuestion)
```

导入后统计：

```text
ExpandedEvaluationQuestion = 184
SUPPORTED_BY = 184
dangling = 0
```

问答节点与严格证据层连接：

```text
(:ExpandedEvaluationQuestion)-[:SUPPORTED_BY]->(:StrictEvidence)
```

## 为什么不直接加入通用 QA

SciQ、WorldTree、ScienceQA、OpenBookQA、MMLU 等适合做：

- 基础化学/物理能力测试；
- 外部 QA 回归测试；
- Schema sanity check；
- 解释链评测。

但它们不适合未经证据回溯直接写入电镀 VerifiedFact。答案通常是二手标注，领域粒度与当前铜/钴电镀场景也不一致。

本轮使用证据生成 QA，是为了扩充**问答覆盖和评测层**，而不是伪造新的领域事实。

## 当前规模是否太少

分层看：

- 文献事实候选：119 条严格关系；
- 文献证据：1,290 条；
- 实体：64 个；
- 数值/单位：1,295 条；
- 原有证据绑定 QA：45 条；
- 扩充后证据绑定 QA：184 条。

对于毕业论文的方法验证和 KG-RAG 初步评测，184 条题目已经可以构成初版测试集；对于完整领域 benchmark，仍建议人工审核后扩展到 300–500 条，并对类别、关系和难度进行均衡采样。

## QA 质量审核

优先审核：

1. QA 答案是否完全由 evidence_quote 支持；
2. 是否遗漏浓度、温度、电流密度、pH、时间、孔径等条件；
3. 是否把实验观察扩写成因果结论；
4. 是否把析氢/腐蚀/附着力误写成金属沉积/孔填充；
5. 数值和单位是否正确；
6. 问题是否存在唯一答案；
7. 生成题是否重复或过度相似；
8. 是否应标记 `unknown` 或 `insufficient_evidence`。

最终可把 QA 分成：

```text
VerifiedQA
RejectedQA
QuarantineQA
```

但不应把 QA gold answer 自动变成 `VerifiedFact`。
