# 实验与评测脚本

本目录收录论文全部检索层/答案层评测与基线对比实验脚本。**统一从仓库根目录运行**，各脚本默认路径与仓库目录布局一致。

> `rag_system.py` + `graph_retriever.py` 是早期平铺版检索系统，作为评测脚本的公共运行库保留（`load_index` / `retrieve` / `extractive_answer`）；其工程化重构版本即仓库根目录的 [`kgrag/`](../kgrag/) 软件包。

## 1. 评测集构建

| 脚本 | 功能 | 产物 |
| --- | --- | --- |
| `rag_eval_builder.py` | 从本地 KG 构建带溯源的 silver 检索集（实体开放题 + 无答案探针） | `evaluation/auto_*_silver.jsonl` |
| `rag_gold_builder.py` | 由 v1 golden 基准构建 gold 评测集 | `evaluation/gold_qa.jsonl` |
| `gold_unified_builder.py` | 统一 v1/v2 两代 gold 集为单一 schema | `evaluation/gold_qa_v1/v2/unified.jsonl` |
| `validate_eval.py` | 校验评测 JSONL 结构与 gold evidence 溯源 | `evaluation/*_validation.json` |

## 2. 检索层评测

| 脚本 | 功能 |
| --- | --- |
| `rag_eval.py` | 词法 BM25 基线评测（Hit@k / Recall@k / Sufficient@k） |
| `rag_compare.py` / `rag_hybrid.py` / `rag_rerank.py` | KG 感知加权 / 混合检索 / 重排对比 |
| `rag_dense_compare.py` / `rag_dense_bge.py` | 稠密检索对照（char TF-IDF proxy / BGE） |
| `rag_gold_retrieval_eval.py` | gold 集上 lexical vs KG-aware 对比 |
| `gold_unified_eval.py` | **统一 gold 检索层评测**（两代真值 × 三种策略），产物 `evaluation/unified_gold_metrics.json` |
| `rag_abstention_eval.py` | 弃答守卫评测（无答案探针误返率） |
| `rag_build_v2.py` | 统一 v2 事实信源并构建 `kg_v2_unified/` 与 `rag_index_v2/` |

## 3. 答案层评测（LLM-as-judge）

| 脚本 | 功能 |
| --- | --- |
| `rag_answer_eval.py` | 答案层 gold 评测：逐题生成回答（需 `RAG_LLM_*` 环境变量） |
| `rag_judge.py` / `rag_judge_retry.py` | 多评委逐条打分 / 失败重试 |
| `rag_judge_aggregate.py` | 汇总评委打分为最终指标 `evaluation/gold_answer_metrics.json` |

## 4. 基线对比实验

| 脚本 | 实验 |
| --- | --- |
| `closedbook_baseline.py` | 对比实验 A：无检索闭卷基线 |
| `llm_extraction_baseline.py` + `llm_extraction_analyze.py` | 对比实验 C：LLM 直接抽取 vs 确定性规则管线 |

## 5. 典型复现流程

```bash
# 0) 准备索引（任选 v1 或 v2 知识库）
cd kgrag && python -m kgrag.cli build --kg ../kg_v2_unified --out ../rag_index_v2 && cd ..

# 1) 检索层统一评测
python experiments/gold_unified_eval.py

# 2) 答案层评测（需配置 RAG_LLM_API_KEY 等）
python experiments/rag_answer_eval.py --index rag_index_v2 --gold evaluation/gold_qa_v2.jsonl \
    --models <model-a> <model-b> --out evaluation/answers.jsonl
python experiments/rag_judge.py --judges <judge-a> <judge-b> <judge-c>
python experiments/rag_judge_aggregate.py
```

指标口径（Hit@k / Evidence Recall@k / Sufficient@k / negative_hit_rate 等）定义见 [`evaluation/README.md`](../evaluation/README.md)。
