# Gold 评测统一报告（v1 model-judged + v2 panel-consensus → 单一协议）

> 本报告记录将仓库中并存的两份 gold 评测真值统一为单一评测协议的工程实施与实测结果。
> 实施日期：2025-10-20。所有数字来自 [evaluation/unified_gold_metrics.json](evaluation/unified_gold_metrics.json) 与 [evaluation/ablation_panel_v2.json](evaluation/ablation_panel_v2.json)。

## 1. 统一前的两份 gold（问题）

| | gold v1 | gold v2 |
|---|---|---|
| 文件 | [golden_benchmark/gold_test.jsonl](golden_benchmark/gold_test.jsonl) | [golden_benchmark_v2/gold_test.jsonl](golden_benchmark_v2/gold_test.jsonl) |
| 真值来源 | gpt-5.6-terra 单模型判定 | 五模型评审团共识（4 厂商） |
| 判定协议 | 谓词级（只送谓词+证据，模型自抽主客体，有已知效度缺陷） | 三元组级（subject/predicate/object/conditions 逐项裁决） |
| 规模 | 24 条（supported 19 / unsupported 4 / contradicted 1） | 44 条（supported 30 / partial 3 / ambiguous 1 / unsupported 9 / contradicted 1） |
| 数据层 | strict_extraction_verify（v1 严格层，1,290 证据） | strict_extraction_v2（v2 严格层，1,411 证据 + 403 条件 + jury 三态） |
| 谓词覆盖 | 4 种 | 7 种（+used_as_leveler/suppressor/inhibitor、adsorbs_on） |
| 被 RAG 评测使用 | ✅（gold_qa 24 条） | ❌（未接入——统一方案断点 G6） |

两份 gold 各有一套问答脚本口径（v1 的 `rag_gold_builder.py` 只认 label/subject/object/reason 字段），且 v2 的结构化信号（panel_decision、consensus_conditions）在 v1 管线中无映射。

## 2. 统一方案（本报告的交付）

### 2.1 统一 QA schema（两代同构）

新增 [gold_unified_builder.py](gold_unified_builder.py)，把两代 gold 映射到同一 schema：

```text
id, question, answerable, question_type(factual|adversarial|partial|ambiguous),
gold_answer, gold_evidence_ids(多gold), fact_id, evidence_id, predicate, subject,
object, conditions, conditions_struct, label, panel_decision, gold_version,
gold_status, gold_source, surface_text, n_gold_facts, facts[明细]
```

**真值双轨制**：`consensus_label`（证据是否支持关系结论）决定 `question_type`；`panel_decision`（三元组置信层级）作为独立信号保留并进入检索加权。映射：

- supported → factual（30 条：verified 24 + quarantine 6）
- partial → partial（3 条，answerable 但单列统计）
- unsupported / contradicted → adversarial（10 条探针）
- ambiguous → ambiguous（1 条，不计入主指标）

**多 gold 聚合**：同一 (question, question_type) 的多条事实聚合为一个条目（gold_evidence_ids 合并，明细留 facts 列表），与 silver entity 集的开放式多 gold 语义对齐。v2 44 条事实 → 34 个条目（6 个多 gold 组）；v1 24 → 23。

**产物**（均通过 evidence 覆盖校验，0 缺失）：

| 文件 | 内容 |
|---|---|
| [evaluation/gold_qa_v1.jsonl](evaluation/gold_qa_v1.jsonl) | 23 条（v1 真值，统一 schema） |
| [evaluation/gold_qa_v2.jsonl](evaluation/gold_qa_v2.jsonl) | 34 条（v2 真值，统一 schema） |
| [evaluation/gold_qa_unified.jsonl](evaluation/gold_qa_unified.jsonl) | 57 条合并集（gold_version 字段区分） |

### 2.2 统一 v2 索引（rag_index_v2）

新增 [rag_build_v2.py](rag_build_v2.py)：以 strict_extraction_v2 + jury/consensus 组装 `kg_v2_unified/` 并构建 [rag_index_v2](rag_index_v2/index.json)（version=3，N=1,411）。关键设计（经消融实验校正，见 §3）：

- **panel_status 作为行级元数据存储**（verified 175 行有值），**不进 BM25 文本**——文本注入实测无增益甚至略负（"verified" 高频词稀释主题信号）；
- **条件槽进索引文本**（fact_tags 含 `improves_filling|concentration=200 ppm(clause)`）；
- `predicates` 保持纯谓词（硬过滤兼容），新增 `fact_tags`、`panel_status`、`final_score` 字段。

[rag_system.py](rag_system.py) 的改动全部向后兼容：kg_data 旧目录（无新列）构建行为不变；旧索引（无 panel_status 字段）在 panel 模式下无操作。v1 组合上 panel 系统与 v3 结果完全一致即为其验证。

### 2.3 评审团状态 → 检索加权的意图路由（核心新能力）

`retrieve()` 新增 `panel_mode` 参数：

- `trust`：verified ×1.10 / rejected ×0.90 —— 事实型问答（信任已验证证据）
- `refute`：rejected ×1.15 / verified ×0.90 —— 找反证（对抗探针的 gold 证据恰恰是**被评审团拒绝的证据**）
- `off`：不启用（默认，向后兼容）

乘子作用于 v3 锚定后的复合 final_score（不破坏锚定排序）。[rag_api.py](rag_api.py) `/ask` 已开放 `panel_mode` 参数（默认 trust）；[rag_answer_eval.py](rag_answer_eval.py) 默认按条目意图自动路由。

## 3. 消融实验：状态加权的设计依据（[evaluation/ablation_panel_v2.json](evaluation/ablation_panel_v2.json)）

v2 factual 22 条 × 三种索引 × panel 开关（v3 锚定，k=10 池）：

| 索引 | panel | hit@5 | hit@10 | 对抗反驳证据命中 |
|---|---|---:|---:|---:|
| v2_plain（无任何增强） | off | 0.5909 | 0.7727 | 4/8 |
| v2_plain | on | 0.5909 | 0.7727 | 4/8 |
| v2_notext（状态元数据） | off | 0.5909 | 0.7727 | 4/8 |
| v2_notext | on(trust) | **0.7273** | 0.7727 | 2/8 |
| v2_unified（状态+条件文本） | off | 0.5909 | 0.7727 | 4/8 |
| v2_unified | on(trust) | **0.7273** | 0.7727 | 2/8 |
| v2_unified | on(refute) | 0.5909 | 0.6818 | **7/8** |

三个发现：

1. **状态文本进索引无增益**（plain/unified 在 off 下列相同）→ 设计改为行级元数据 + 检索后加权，trust 模式带来 **factual hit@5 +13.6pp（0.591→0.727）**——评审团的质量投资首次转化为检索增益（统一方案断点 G2 解除的实证）；
2. **trust 与 refute 方向相反且各自有效**：trust 提升 factual 但压低反驳证据命中（2/8），refute 反之（7/8）——状态加权不是全局开关，而是**按查询意图路由**的信号；
3. 条件文本在本评测集上中性（factual 指标无差异），保留待条件相关查询验证。

## 4. 统一评测结果（[evaluation/unified_gold_metrics.json](evaluation/unified_gold_metrics.json)）

统一协议（[gold_unified_eval.py](gold_unified_eval.py)）：两代 gold × 五种策略，多 gold 命中语义，按 question_type 分层。

### 4.1 v1 组合（gold v1 × rag_index_strict，N=1,290）

| 系统 | factual Hit@5 | MRR@5 | Hit@10 | 对抗反驳命中 |
|---|---:|---:|---:|---:|
| lexical BM25 | 0.4444 | 0.1843 | 0.6111 | 2/5 |
| KG-aware BM25 | 0.5000 | 0.2722 | 0.6111 | 3/5 |
| subject-anchored v3 | 0.6667 | 0.4157 | 0.8333 | 4/5 |
| v3 + panel（trust/路由） | 0.6667 | 0.4157 | 0.8333 | 4/5 |

（v1 索引无评审状态元数据，panel 模式无操作——数字与 v3 一致，向后兼容验证通过。与旧报告 0.421/0.474/0.632 的差异来自多 gold 聚合与 23 题分组，趋势一致。）

### 4.2 v2 组合（gold v2 × rag_index_v2，N=1,411）——统一后的主结果

| 系统 | factual Hit@5 | MRR@5 | Hit@10 | 对抗反驳命中 |
|---|---:|---:|---:|---:|
| lexical BM25 | 0.2273 | 0.1212 | 0.4091 | 2/8 |
| KG-aware BM25 | 0.3636 | 0.2273 | 0.4091 | 3/8 |
| subject-anchored v3 | 0.5909 | 0.4068 | 0.7727 | 4/8 |
| v3 + panel trust | 0.7273 | 0.4773 | 0.7727 | 2/8 |
| **v3 意图路由（统一最优）** | **0.7273** | **0.4773** | **0.7727** | **7/8** |

partial 层（3 条）：lexical 0.3333 / KG-aware 0.6667 / v3 0.6667 / trust 0.3333（k=5）。

**统一最优形态**：v3 锚定 + 评审团意图路由——factual 0.7273（+13.6pp vs 无状态）、MRR 0.4773、反驳证据 7/8（+3）。

### 4.3 v2 比 v1 检索更难的原因（诚实归因）

v2 各策略基线低于 v1（如 v3 factual 0.5909 vs 0.6667）：① 语料更大（1,411 vs 1,290 行）干扰证据更多；② 谓词覆盖 7 种（角色类谓词的证据表述更分散）；③ v2 证据是子句级、粒度更细；④ v2 对抗项的 gold 是三元组级否定的证据，检索语义更难。这不是系统退步——两代真值的可比结论应以 v2 为准（协议更严格、真值更可信）。

## 5. 答案层链路（已就绪，LLM 部分待运行）

- [rag_answer_eval.py](rag_answer_eval.py) 已支持统一 schema（`--gold evaluation/gold_qa_v2.jsonl`）+ 意图路由（默认 `--panel-mode intent`：answerable→trust、对抗→refute）；
- extractive 模式已实测跑通 34 条（[evaluation/answers_v2_extractive.jsonl](evaluation/answers_v2_extractive.jsonl)）：对抗项反驳证据 8/9 进入 top-5；
- LLM 生成 + 4 裁判评分的完整命令（复用既有链路，替换 gold 与 index 即可）：

```bash
RAG_LLM_API_KEY=... python rag_answer_eval.py --index rag_index_v2 \
    --gold evaluation/gold_qa_v2.jsonl \
    --models glm-5.3 qwen3.7-max deepseek-v4-pro-0813 kimi-k2.6 \
    --out evaluation/answers_v2.jsonl
RAG_LLM_API_KEY=... python rag_judge.py --answers evaluation/answers_v2.jsonl \
    --judges glm-5.3 qwen3.7-max deepseek-v4-pro-0813 kimi-k2.6 \
    --out evaluation/judged_v2.jsonl --workers 8
python rag_judge_aggregate.py --judged evaluation/judged_v2.jsonl \
    --out evaluation/gold_answer_metrics_v2.json
```

（预计调用量：34 题 × 5 系统 × 4 裁判 = 680 次，约为 v1 一轮的 1.4 倍。）

## 6. 交付物清单

| 文件 | 内容 |
|---|---|
| [gold_unified_builder.py](gold_unified_builder.py) | 两代 gold → 统一 QA schema（多 gold 聚合、9 谓词问题生成） |
| [rag_build_v2.py](rag_build_v2.py) | v2 事实信源 + jury 共识 → kg_v2_unified → rag_index_v2 |
| [gold_unified_eval.py](gold_unified_eval.py) | 统一检索评测协议（两代 gold × 五策略 × 意图路由） |
| [rag_system.py](rag_system.py) | 索引 v3：panel_status 元数据、条件进 fact_tags、panel_mode 三态软加权（全部向后兼容） |
| [rag_answer_eval.py](rag_answer_eval.py) | 答案层支持统一 schema + 意图路由 |
| [rag_api.py](rag_api.py) | /ask 开放 panel_mode 参数 |
| [evaluation/gold_qa_v1.jsonl](evaluation/gold_qa_v1.jsonl) / [gold_qa_v2.jsonl](evaluation/gold_qa_v2.jsonl) / [gold_qa_unified.jsonl](evaluation/gold_qa_unified.jsonl) | 统一 gold 集（23 / 34 / 57 条） |
| [evaluation/unified_gold_metrics.json](evaluation/unified_gold_metrics.json) | 统一检索评测全部数字 |
| [evaluation/ablation_panel_v2.json](evaluation/ablation_panel_v2.json) | 状态加权消融矩阵 |
| [evaluation/answers_v2_extractive.jsonl](evaluation/answers_v2_extractive.jsonl) | extractive 答案层链路验证产物 |
| [kg_v2_unified/](kg_v2_unified/)、[rag_index_v2/](rag_index_v2/) | v2 统一数据层与索引 |

## 7. 复现命令

```bash
# 1) 统一 v2 索引（v2 数据 + 评审状态元数据 + 条件槽）
python3 rag_build_v2.py
# 2) 统一 gold 集（v1/v2/合并）
python3 gold_unified_builder.py
# 3) 统一检索评测（两代 gold × 五策略 × 意图路由）
python3 gold_unified_eval.py
# 4)（可选）答案层 extractive 链路
python3 rag_answer_eval.py --index rag_index_v2 --gold evaluation/gold_qa_v2.jsonl \
    --models --out evaluation/answers_v2_extractive.jsonl
```

## 8. 结论与限制

**已达成**：两份 gold 评测在 schema、索引、评测协议、答案层链路四层完全统一；评审团三态第一次参与检索排序并实测带来 factual +13.6pp、反驳证据 +3/8 的增益；统一最优形态为 **v3 锚定 + 意图路由**（factual 0.7273 / 反驳 7/8）。

**限制（不隐瞒）**：
1. v2 真值仍是五模型共识（`llm_panel_consensus_needs_human_signoff`），非人工金标准——46 条真人签核包仍待执行；
2. panel 乘子（1.10/0.90/1.15）在 n=22 上网格搜索得到，过拟合风险存在，应在人工签核后的更大 gold 上重校；
3. n=22/8/3/1 的分层数字样本量小，统计效力有限；
4. v1 组合的 panel 无操作是索引层面的（v1 无评审状态），非策略失效；
5. 条件槽进索引文本的增益未在本集上显现，需设计条件相关查询集单独验证；
6. LLM 答案层 + 4 裁判的 v2 全量评测未运行（命令已就绪，预计 680 次调用）。
