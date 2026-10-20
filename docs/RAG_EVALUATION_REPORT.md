# 电镀领域 RAG 自动评测与对比报告（第 3 版）

## 运行条件

- 知识库：`kg_data`，48 篇文献、4,341 条 Evidence、1,063 条候选事实、36 个实体。
- 检索器：jieba 词级中文分词 + BM25（k1=1.2, b=0.75）；KG-aware boost（实体/关系别名加权）；BGE 神经 dense（BAAI/bge-small-zh-v1.5，512 维）；RRF 融合与 dense rerank 两种混合策略。
- 指标：Hit@k（命中任一 gold 即相关命中，开放式多 gold 集的主指标）、Evidence Recall@k、Sufficient@k、检索延迟、负例命中率。
- 所有系统使用同一索引、同一分词、同一评测集。

## 评测集（自动 silver，均通过 provenance 校验）

| 数据集 | 数量 | 说明 |
|---|---|---|
| `auto_anchored_silver.jsonl` | 400 | 带原文短线索，确定性回归集 |
| `auto_entity_silver.jsonl` | 237 | 233 条实体条件开放题（多有效 gold，平均约 9 条/题）+ 4 条无答案探针 |

## 结果 1：实体条件开放集（k=5，主指标 Hit@5）

| 系统 | Hit@5 | Recall@5 | P50 延迟 |
|---|---:|---:|---:|
| lexical BM25 | 0.5193 | 0.0415 | 5.7 ms |
| **KG-aware BM25（当前最优）** | **0.5408** | 0.0579 | 8.3 ms |
| BGE dense（bge-small-zh-v1.5） | 0.3305 | 0.0112 | 0.3 ms* |
| RRF hybrid（BM25+dense） | 0.4592 | 0.0358 | 12.7 ms |
| BM25 候选 + dense rerank | 0.3476 | 0.0186 | 2508 ms |

*dense 延迟不含 4341 条文档的一次性编码时间（约 63 s，可离线预计算）。

k=10 消融：lexical hit@10 = 0.5365，KG-aware hit@10 = 0.5665（+3.0 pp）。

分关系切片（KG-aware，hit@5）：

| 关系 | hit@5 | 说明 |
|---|---:|---|
| inhibits_deposition | 0.840 | 实体锚定最充分（124 条可锚定事实） |
| synergizes_with | 0.582 | — |
| improves_filling | 0.118 | 仅 17 条可锚定事实，统计意义有限 |
| accelerates_deposition | 0.020 | 49 条可锚定，但金证据集中在少数证据行 |

## 结果 2：anchored 回归集（k=5）

| 系统 | Hit@5 | Recall@5 | P50 延迟 |
|---|---:|---:|---:|
| **lexical BM25（最优）** | **0.9900** | 0.9900 | 54.7 ms |
| KG-aware BM25 | 0.9900 | 0.9900 | 94.7 ms |
| RRF hybrid | 0.9600 | 0.9600 | 116.3 ms |
| BGE dense | 0.4175 | 0.4175 | 0.3 ms* |

## 关键发现

1. **本语料+本评测集上，词法 BM25 是最强检索器，神经 dense 全面落后。**原因：(a) 问题由模板自动生成，非自然中文表达；(b) 证据是脱离上下文的单行 Markdown，dense 向量在单行上语义信号弱；(c) 实体缩写（JGB/SPS/PEG）是主要判别特征，词法精确匹配天然占优。
2. **KG-aware boost 提供稳定增益**（hit@5 +2.15 pp、hit@10 +3.0 pp），代价可忽略（P50 +2.6 ms）。
3. **不建议为引入 dense 而引入 dense**：RRF 混合与 dense rerank 在两个集上均低于纯 BM25。dense 的正确用法应等真实用户问题积累后，在自然语言问句上重测。
4. **拒答 guard 有效但样本极小**：4 条无答案探针全部正确拒答（negative hit rate 0.0）。
5. 检索层瓶颈在数据侧而非算法侧：36 个实体太少、候选事实缺 subject/object 结构、`improves_filling` 关系覆盖不足。

## 重要限制

1. 两套评测集均为自动 silver，未人工审核；问题措辞不代表真实用户。
2. 只覆盖检索层，无答案正确性、条件保留、引用蕴含、幻觉率评估。
3. dense 基线的结论仅适用于"模板问题 + 单行证据"的当前形态；证据窗口化（段落/表格）后需要重测。
4. 拒答只有 4 条探针。

## 运行环境说明

- BGE 模型经 `hf-mirror.com` 下载（本机不能直连 HF）。
- 依赖 `LD_PRELOAD=/opt/conda/lib/libstdc++.so.6`（系统 libstdc++ 缺 GLIBCXX_3.4.29，conda 自带版本可用）。
- 编码 4341 条证据约 63 s，可离线预计算后查询延迟 <1 ms。

## 结论与建议

当前可上线的检索形态：**jieba + BM25 + KG-aware boost**。dense/embedding 已具备完整基线代码（`rag_dense_bge.py`、`rag_hybrid.py`、`rag_rerank.py`），但按当前证据形态不应启用；待 (a) 证据升级为段落/表格窗口、(b) 收集真实用户问题后重测。

下一步优先级：
1. 证据窗口化（段落/表格/图注），这同时改善 BM25 与 dense；
2. 事实结构化（subject/predicate/object/qualifiers）补齐 KG；
3. 人工 gold 评测集（覆盖条件、多跳、比较、机制、无答案）；
4. 答案级评测（正确性、条件保留、引用蕴含）。
