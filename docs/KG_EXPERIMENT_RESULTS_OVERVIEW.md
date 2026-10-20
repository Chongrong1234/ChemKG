# 电镀领域 KG 实验结果总览

## 1. 实验目标

本轮实验验证三个问题：

1. 严格证据抽取是否能减少跨领域污染；
2. 候选关系是否具有证据绑定、主体/客体和关系结构完整性；
3. KG 是否已经形成可用于证据型科学问答的扩展层。

由于当前没有独立人工 gold 文档集，本报告不虚构 Entity/Relation Precision、Recall 或 F1；模型判定结果与结构完整性结果分开报告。

## 2. 数据和图谱规模

### 2.1 严格候选层

| 类型 | 数量 |
|---|---:|
| 文档 | 48 |
| 证据片段 | 1,290 |
| 候选实体 | 64 |
| 实体提及 | 3,216 |
| 数值/单位 | 1,295 |
| 候选关系 | 119 |

### 2.2 关系分布

| 关系 | 数量 |
|---|---:|
| `inhibits_deposition` | 64 |
| `improves_filling` | 26 |
| `accelerates_deposition` | 22 |
| `synergizes_with` | 7 |

### 2.3 QA 扩展层

| 类型 | 数量 |
|---|---:|
| 扩充 QA | 184 |
| 覆盖证据片段 | 181 |
| 无证据 QA | 0 |

## 3. 严格过滤实验

严格抽取器采用：

- 领域上下文约束；
- References/参考文献过滤；
- DOI/URL 过滤；
- 催化、CVD、CMP、光催化和腐蚀语境过滤；
- 局部句/分句主体—客体绑定；
- 关系特定约束；
- Evidence 绑定。

### 3.1 污染检查

在 119 条严格候选关系的证据文本中检查以下污染关键词：

```text
catalys, CVD, CMP, cross-coupling,
photocatal, corrosion, reference, doi, http
```

结果：

```text
污染命中关系：0
```

这说明严格过滤在规则层面消除了已定义的污染模式，但不等价于人工事实准确率。

### 3.2 关系字段完整性

| 检查项 | 结果 |
|---|---:|
| 缺失 evidence_id | 0 |
| 缺失 subject_id | 0 |
| 缺失 object_id | 0 |
| 候选关系总数 | 119 |
| Neo4j 严格 Evidence 绑定 | 119/119 |

## 4. GPT-5.6 模型语义复核

使用：

```text
Model: gpt-5.6-terra
Temperature: 0
Input: 119 条严格候选关系
```

模型只根据证据文本输出标签、主体、客体、条件、证据有效性和理由。

### 4.1 全量结果

| 标签 | 数量 | 比例 |
|---|---:|---:|
| `supported` | 95 | 79.83% |
| `partial` | 9 | 7.56% |
| `unsupported` | 10 | 8.40% |
| `contradicted` | 2 | 1.68% |
| `ambiguous` | 3 | 2.52% |
| 合计 | 119 | 100% |

`95/119=79.83%` 是 GPT-5.6 接受率，不是人工 Precision。

### 4.2 按关系类型

| 关系 | 总数 | Supported | Partial | Unsupported | Contradicted | Ambiguous |
|---|---:|---:|---:|---:|---:|---:|
| `improves_filling` | 26 | 17 | 4 | 2 | 2 | 1 |
| `accelerates_deposition` | 22 | 15 | 1 | 6 | 0 | 0 |
| `synergizes_with` | 7 | 6 | 0 | 0 | 0 | 1 |
| `inhibits_deposition` | 64 | 57 | 4 | 2 | 0 | 1 |

可以观察到：`accelerates_deposition` 的拒绝比例高于其他关系，说明“加速电化学过程”和“加速金属沉积”容易混淆，后续应加强该关系定义和条件约束。

## 5. GPT-5.6 Golden Benchmark

使用随机种子 2025，将 119 条模型判定样本固定划分：

```text
Golden test：24
Reference/train：95
```

### 5.1 测试集结果

| 标签 | 数量 |
|---|---:|
| Supported | 19 |
| Unsupported | 4 |
| Contradicted | 1 |
| Partial | 0 |
| Ambiguous | 0 |

测试完整性：

| 检查 | 结果 |
|---|---:|
| 测试样本数 | 24 |
| 唯一 fact_id | 24 |
| Evidence 绑定 | 24/24 |
| 缺失必填字段 | 0 |
| 证据缺失 | 0 |

注意：这是 `GPT-5.6 model-judged golden benchmark`，不是专家 golden standard。

## 6. QA 证据绑定测试

QA 由 GPT-5.6 根据严格 Evidence 生成，并进行问题去重。

| 检查 | 结果 |
|---|---:|
| QA 总数 | 184 |
| 覆盖证据数 | 181 |
| Evidence 绑定数 | 184 |
| Dangling QA | 0 |
| QA 缺少 evidence_id | 0 |

当前 QA 的 `gold_status` 为：

```text
model_generated_needs_review
```

因此只能作为候选评测集，不能直接作为领域事实。

## 7. Neo4j 验证结果

严格层已导入 Neo4j 5.26.32：

| 节点/关系 | 数量 |
|---|---:|
| StrictDocument | 48 |
| StrictEvidence | 1,290 |
| StrictEntity | 64 |
| StrictValue | 1,295 |
| StrictCandidateFact | 119 |
| STRICT_MENTIONS | 3,216 |
| STRICT_SUPPORTED_BY | 119 |
| STRICT_SUBJECT | 119 |
| STRICT_OBJECT | 119 |
| ExpandedEvaluationQuestion | 184 |
| QA SUPPORTED_BY | 184 |

结构检查结果：

```text
StrictCandidateFact dangling evidence = 0
ExpandedEvaluationQuestion dangling evidence = 0
```

## 8. 当前可以支持的结论

当前实验可以支持：

1. 严格证据抽取显著减少了初始宽松抽取中的跨领域污染；
2. 119 条严格候选关系全部具有 subject、object 和 evidence_id；
3. 119 条候选关系全部在 Neo4j 中绑定到证据；
4. GPT-5.6 认为 95 条关系具有直接支持证据；
5. GPT-5.6 发现 24 条关系存在部分支持、证据不足、方向错误或歧义；
6. 已构建 184 条证据绑定 QA，可作为初版 KG-RAG/科学问答评测层。

## 9. 当前不能声称的结论

目前不能声称：

- KG 的人工 Precision 已达到 79.83%；
- KG 已完成领域专家 gold 验证；
- 119 条关系全部正确；
- 184 条 QA 已是人工金标准；
- KG 相比 BM25、向量 RAG 或 Flat Triple 已经获得下游显著提升；
- 已完成完整 Recall 或 OOD 泛化实验。

原因是目前还没有独立人工标注的 Gold-IE 和 Gold-Coverage 文档集，也没有运行统一的 BM25/向量/Flat Triple/KG+Evidence 下游对照实验。

## 10. 下一步论文级实验

1. 对严格关系进行双人专家审计，至少 30–50 条 pilot，随后扩展到 300–500 条；
2. 建立 10–20 篇独立 Gold-Coverage 文档；
3. 报告 Entity/Relation/Qualifier/Value/Evidence P/R/F1；
4. 对 184 条 QA 进行专家审核并固定 test/dev；
5. 对比 Direct LLM、BM25 RAG、Vector RAG、Flat Triple、KG-only 和 KG+Evidence；
6. 完成去条件、去证据、去严格过滤和去 LLM 审计消融；
7. 报告置信区间、标注者一致性和 OOD 测试。

## 11. 可复现实验文件

- `kg_pipeline/strict_extract.py`
- `kg_pipeline/llm_review.py`
- `kg_pipeline/build_golden.py`
- `golden_benchmark/run_tests.py`
- `strict_extraction/summary.json`
- `strict_extraction/gpt56_reviews.jsonl`
- `golden_benchmark/gold_test.jsonl`
- `qa_layer/qa_expanded.jsonl`
- `kg_pipeline/strict_neo4j_import.cypher`
- `kg_pipeline/qa_neo4j_import.cypher`
