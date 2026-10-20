# GPT-5.6 模型判定 Golden Benchmark 与测试报告

## 1. 目的

本报告记录使用用户提供的 OpenAI-compatible API 和 GPT-5.6 级模型对严格电镀 KG 候选关系进行模型判定，并固定独立测试切分的过程。

重要限定：这里的 golden benchmark 是 **GPT-5.6 model-judged golden set**，不是人工专家 gold。它可以作为可复现的模型评测基准和预审集，但不能替代领域专家标注。

## 2. 模型与调用配置

```text
API: OpenAI-compatible
Model: gpt-5.6-terra
Temperature: 0
Input: strict_extraction/relations.jsonl
Candidates: 119
```

每条样本要求模型只基于原文证据输出：

- label：supported / partial / unsupported / contradicted / ambiguous；
- domain_relevant；
- corrected_predicate；
- subject/object；
- conditions；
- evidence_valid；
- confidence；
- reason。

## 3. 全量模型判定结果

| 标签 | 数量 |
|---|---:|
| supported | 95 |
| unsupported | 10 |
| partial | 9 |
| ambiguous | 3 |
| contradicted | 2 |
| 合计 | 119 |

按原始关系类型：

| 原始关系 | 总数 | supported | partial | unsupported | contradicted | ambiguous |
|---|---:|---:|---:|---:|---:|---:|
| `improves_filling` | 26 | 17 | 4 | 2 | 2 | 1 |
| `accelerates_deposition` | 22 | 15 | 1 | 6 | 0 | 0 |
| `synergizes_with` | 7 | 6 | 0 | 0 | 0 | 1 |
| `inhibits_deposition` | 64 | 57 | 4 | 2 | 0 | 1 |

如果把 `supported` 作为模型接受标签，则模型支持率为：

```text
95 / 119 = 79.83%
```

但这不是 KG Precision，只是 GPT-5.6 对严格候选的接受比例。

## 4. Golden 测试集

使用固定随机种子 `2025`，抽取 20% 作为测试集：

```text
总样本：119
Golden test：24
Reference/train：95
Seed：2025
```

测试集文件：

- `golden_benchmark/gold_test.jsonl`
- `golden_benchmark/gold_test.csv`
- `golden_benchmark/train_reference.jsonl`
- `golden_benchmark/gold_reference.jsonl`

GPT-5.6 判定的测试集标签：

| 标签 | 数量 |
|---|---:|
| supported | 19 |
| unsupported | 4 |
| contradicted | 1 |
| partial | 0 |
| ambiguous | 0 |

测试集完整性检查：

- 样本数：24；
- fact_id 唯一数：24；
- evidence 绑定：24/24；
- 必填字段缺失：0；
- gold 来源：GPT-5.6；
- 状态：`model_judged_not_human`。

测试脚本：`golden_benchmark/run_tests.py`。

## 5. 现阶段如何使用这个 benchmark

### 5.1 作为抽取系统的固定回归测试

每次修改抽取器后，重新生成预测，并与 `gold_test.jsonl` 比较：

- Label Accuracy；
- Macro-F1；
- Supported Precision/Recall/F1；
- Domain relevance F1；
- Predicate correction accuracy；
- Evidence validity accuracy。

### 5.2 作为规则版本对比

可以比较：

```text
宽松关键词版本
严格证据版本
LLM增强版本
```

重点关注：

- 误将非电镀事实识别为电镀事实的比例；
- `improves_filling` 的过度预测；
- `accelerates_deposition` 和 `inhibits_deposition` 的方向错误；
- `synergizes_with` 的实体完整性。

### 5.3 不应作为最终论文 gold 的原因

GPT-5.6 仍可能：

- 误读复杂实验条件；
- 受 prompt 影响；
- 将隐含机制当作明确关系；
- 对边界案例产生系统偏差；
- 在相同模型生成和评判时形成自洽偏差。

因此论文中应称：

```text
GPT-5.6 model-judged golden benchmark
```

而不是：

```text
expert gold standard
```

## 6. 建议的最终人工抽样

从 24 条 golden test 中优先抽取所有：

- `unsupported` 4 条；
- `contradicted` 1 条；
- `improves_filling` 样本；
- `synergizes_with` 样本；
- 含浓度、电流密度、温度和孔几何条件的样本。

由两名领域人员独立审核 GPT-5.6 标签。若人工与 GPT-5.6 不一致，人工裁决结果应覆盖模型标签，并记录：

```text
human_label
human_reason
adjudication_status
```

## 7. 结论

GPT-5.6 对 119 条严格候选关系给出 95 条 supported、9 条 partial、10 条 unsupported、2 条 contradicted、3 条 ambiguous。固定 24 条作为模型判定 golden test 后，得到 19 条 supported、4 条 unsupported 和 1 条 contradicted。

该 benchmark 已具备可重复运行、证据绑定和固定切分特征，适合做抽取系统回归测试；但由于标签来自 GPT-5.6 而非领域专家，它仍是模型判定基准，不是最终科学真值。最终论文应同时报告模型基准结果和小规模人工一致性校验结果。
