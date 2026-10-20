# 电镀领域证据优先 Hybrid RAG（可运行基线）

本目录提供一个不依赖 Neo4j 运行实例的本地 RAG 基线，读取现有 `kg_data/*.csv`，对 4,341 条 Evidence 做词法检索，并利用实体、数值和候选事实进行轻量 KG-aware 加权。

## 设计边界

- `CandidateFact` 仍然只是候选事实；系统不会把它自动升级为科学结论。
- 答案始终返回 `evidence_id`、文献标题和原文证据，方便回溯。
- 没有配置 LLM API 时，使用证据摘录模式；配置 OpenAI-compatible 接口后才生成自然语言答案。
- 当前版本是可运行基线，不替代后续的 neural dense embedding、cross-encoder reranker 和完整 Neo4j 图路径检索。当前新增的 `graph_retriever.py` 只做保守 CSV 证据扩展，不推断未经 KG 明确支持的 subject/object 路径。

## 运行

```bash
python rag_system.py build --kg kg_data --docs 文献提取 --out rag_index
python rag_system.py ask --index rag_index --question "PVP 在钴电沉积中起什么作用？"
python rag_system.py ask --index rag_index --question "哪些添加剂能够改善铜微孔填充？" --json
```

可选 LLM 配置（OpenAI-compatible API）：

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=http://127.0.0.1:4000/v1
export RAG_LLM_MODEL=your-model
python rag_system.py ask --index rag_index --question "..."
```

## 评测

先复制并修改 [rag_eval_gold.example.jsonl](rag_eval_gold.example.jsonl)，为每道题补充人工确认的 `gold_evidence_ids`。然后运行：

```bash
python rag_eval.py --index rag_index --gold rag_eval_gold.example.jsonl --k 5 --out rag_eval_report.json
```

支持的字段：

```json
{
  "id": "q1",
  "question": "...",
  "gold_evidence_ids": ["ev_x", "ev_y"],
  "required_terms": ["铜", "填充"]
}
```

输出包括：

- `evidence_recall_at_k`
- `sufficient_evidence_rate`
- `required_term_coverage`
- 每道题检索到的证据 ID

答案正确性、条件完整性和引用正确性需要在 gold 样本中增加 `required_facts`、标准答案和人工/LLM rubric 后另行评估；当前脚本不会假装在没有标签时计算这些指标。

## API 服务

索引准备好后可启动：

```bash
RAG_INDEX=rag_index uvicorn rag_api:app --host 0.0.0.0 --port 8000
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/ask -H 'Content-Type: application/json' -d '{"question":"PVP 在钴电沉积中起什么作用？"}'
```

生产部署前仍应增加鉴权、限流、日志脱敏、超时、监控和索引版本校验。

## 自动评测集和对比

```bash
python rag_eval_builder.py --kg kg_data --out evaluation/auto_silver.jsonl --per-predicate 100
python rag_compare.py --index rag_index --gold evaluation/auto_silver.jsonl --k 5 --out evaluation/comparison.json
```

自动生成集共覆盖四类候选关系，每类 100 条。它是带原文证据 ID 的 **silver** 数据，适合回归测试；由于问题和证据由候选事实自动生成，不能直接当作人工 gold 或论文最终结论。

完整结果见 [RAG_EVALUATION_REPORT.md](RAG_EVALUATION_REPORT.md)。

当前实际运行结果（400 条 silver 样本，Recall@5）：

| 系统 | Evidence Recall@5 | Sufficient Evidence@5 | 平均检索延迟 |
|---|---:|---:|---:|
| lexical BM25-style | 0.7175 | 0.7175 | 71.8 ms |
| KG-aware boost | 0.7375 | 0.7375 | 119.6 ms |

KG-aware 相对 lexical 的 Recall@5 提升为 2.0 个百分点；该结果仅说明当前 silver 回归集上的检索差异，不代表最终答案准确率，也不能替代人工审核。

## 后续迭代顺序

1. 把当前单行 Evidence 升级为段落/句子/表格/图注证据窗口；
2. 将 CandidateFact 结构化为 subject-predicate-object + qualifiers；
3. 增加真正的 BM25、dense embedding 和 reranker；
4. 增加 Neo4j 实体、关系和路径检索，再回溯原文 Evidence；
5. 建立专家问题集和挑战集；
6. 比较 BM25、Dense、Hybrid、KG-only 与 KG+原文系统。
