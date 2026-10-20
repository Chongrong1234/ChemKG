# 评测集说明

## 文件

- `auto_anchored_silver.jsonl`：400 条带原文短线索的确定性回归集（含 4 类候选关系各 100 条）。
- `auto_entity_silver.jsonl`：237 条困难集 = 233 条实体条件开放题（多有效 gold，平均约 9 条/题）+ 4 条无答案探针。
- `anchored_comparison.json` / `entity_comparison.json`：lexical vs KG-aware 检索对比（含 Hit@k）。
- `entity_eval_metrics.json`：实体集上按可回答/负例分离的完整指标。
- `dense_proxy_comparison.json`：char TF-IDF proxy 对照（非神经 embedding）。
- `validation.json` / `entity_validation.json` / `anchored_validation.json`：JSONL 结构与 gold evidence 溯源校验。

## 指标定义

- `Hit@k`：top-k 命中任意一条 gold 即记为相关命中 —— 开放式多 gold 问题的主指标。
- `Evidence Recall@k`：top-k 覆盖 gold 的比例 —— 多 gold 开放集下偏低属预期，主用于回归集。
- `Sufficient@k`：top-k 完整覆盖全部 gold。
- `negative_hit_rate`：无答案探针被错误返回证据的比例。

## 评测集语义与限制

自动集从 `CandidateFact` 和 `Evidence` 构造（silver，未人工审核），只适合：

- 检索回归与索引/tokenizer 变更比较；
- 关系类型切片；
- 证据 ID 召回检查。

它不能直接用于论文中的科学答案准确率。正式 gold 集必须由领域专家独立审核：问题真实性、可回答性、必要事实、实验条件、有效证据集合（允许多组）、否定/不确定性与文献冲突。

历史注意：旧版实体集用单一 gold 评估开放式问题（Recall@5≈0.005 的假象），且无锚点模板题不可判定。当前版本已改为多有效 gold + 仅保留有化学实体锚点的题。分词从 char+bigram 修复为 jieba 词级分词后，回归集 Recall@5 从 0.8525 提升到 0.99。

## 生成与校验

```bash
# 困难集（实体锚定 + 多有效 gold + 负例）
python rag_eval_builder.py --kg kg_data --out evaluation/auto_entity_silver.jsonl --per-predicate 100 --include-negative
# 回归集（带原文线索）
python rag_eval_builder.py --kg kg_data --out evaluation/auto_anchored_silver.jsonl --per-predicate 100 --include-clue
# 溯源校验
python validate_eval.py --gold evaluation/auto_entity_silver.jsonl --index rag_index
# 对比实验
python rag_compare.py --index rag_index --gold evaluation/auto_entity_silver.jsonl --k 5 --out evaluation/entity_comparison.json
```
