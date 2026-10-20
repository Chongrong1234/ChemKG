# KG_RAG 统一系统方案与评测体系总览

> 本文从系统角度串联本工程的知识图谱（KG）构建与 RAG 检索问答两部分：先给出当前实际状态的端到端架构与全部实测数字，再诊断两工程的衔接断点，最后给出统一目标架构与分阶段落地路线。所有数字均来自本仓库实测产物（`strict_extraction_v2/summary.json`、`jury/agreement_summary.json`、`evaluation/*.json` 及各报告），未引入任何外部估计。

---

## 0. 一句话总结

本工程是一条**证据优先（evidence-first）、条件感知（condition-aware）、候选与验证分离**的电镀领域 KG-RAG 流水线：上游从 48 篇文献的 MinerU 解析结果中严格抽取证据/实体/条件/候选事实，经五模型评审团交叉验证分层为 verified / quarantine / rejected 并落图 Neo4j；下游以证据行为检索单元，用 BM25 + KG-aware 加权 + 主体锚定（v3）检索，再以摘录式或 LLM 生成答案。两工程原在数据上只接到 v1 层（KG 宽松层/严格层 v1）——**2025-10-20 的统一实施（[GOLD_UNIFIED_EVALUATION_REPORT.md](GOLD_UNIFIED_EVALUATION_REPORT.md)）已将 v2 严格层（218 条事实 + 403 条条件 + 评审状态）接入 RAG：统一索引 rag_index_v2、统一 gold 评测协议、评审团三态的意图路由加权（factual hit@5 0.591→0.727、反驳证据命中 4/8→7/8）**。剩余主要断点为 subject 自动锚定（G4）、Neo4j 路径检索（G5）与真人签核（P5）。

---

## 1. 系统全景（当前实际状态）

```text
┌─────────────────────────── 原始语料层 ───────────────────────────┐
│ 分类文献库/（48 篇选定领域文献） + 文献提取/（MinerU 解析：full.md）│
└────────────────────────────────┬─────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────┐
│                     KG 构建工程（kg_pipeline/）                  │
│                                                                │
│  build_kg.py          → kg_data/           （v1 宽松层）        │
│    48 docs / 4,341 evidence / 36 entities / 1,063 candidate     │
│    facts（含 cross-coupling 催化污染等缺陷）                    │
│                                                                │
│  strict_extract.py    → strict_extraction/    （v1 严格层）      │
│    48 / 1,290 / 64 / 119 facts                                 │
│    + deepseek-v4.1-flash 审计（77 supported）                   │
│    + gpt-5.6-terra 审计（95 supported = 79.83%，谓词级协议）    │
│    → golden_benchmark/（24 条 model-judged gold）               │
│    → qa_layer/（184 条证据绑定 QA，GPT-5.6 生成）               │
│                                                                │
│  strict_extract_v2.py → strict_extraction_v2/  （v2 严格层★）   │
│    48 / 1,411 / 126(12 类) / 218 facts(9 谓词)                 │
│    + 403 条条件（52.8% 事实覆盖）+ mg 幽灵实体 61→0              │
│    + entity_link_pubchem.py（15/35 实体链接 PubChem）           │
│                                                                │
│  llm_jury.py（五模型评审团，1,090 次调用，三元组级协议）         │
│    → jury/（Verified 120 / Quarantine 21 / Rejected 77）       │
│  jury_aggregate.py → golden_benchmark_v2/（test 44 条）        │
│  llm_signoff.py + jury_consistency.py → 46 条签核包 dry run    │
│    （评审团 verified 精确率 93.33% vs 独立预标注）              │
│                                                                │
│  export_v2_csv.py + strict_neo4j_import_v2.cypher               │
│    → Neo4j 5.x 条件感知图谱（在线，127.0.0.1:7474/7687）        │
│      StrictDocumentV2 48 / StrictEvidenceV2 1,411 /            │
│      StrictEntityV2 126 / StrictValueV2 1,778 /                 │
│      StrictCandidateFactV2 218 / StrictConditionV2 403 /        │
│      StrictPanelReviewV2 218；悬空 0；三态标签就位              │
└────────────────────────────────┬───────────────────────────────┘
                                 │（当前只接到 v1 层 ↓）
┌────────────────────────────────▼───────────────────────────────┐
│                    RAG 检索问答工程（根目录 rag_*.py）           │
│                                                                │
│  rag_system.py build：以 evidence 为检索单元，enriched 文本 =    │
│    原文 + 实体名 + 数值 + 谓词(+条件槽)，jieba 分词 + BM25 索引   │
│    rag_index/       ← kg_data（v1 宽松层，N=4,341）【旧生产索引】│
│    rag_index_strict ← strict_extraction_verify（v1 严格层，     │
│                        N=1,290）【旧 gold 评测索引】            │
│    rag_index_v2     ← strict_extraction_v2 + jury 共识          │
│     ★统一层（N=1,411）：行级 panel_status 元数据 + 条件进文本  │
│                                                                │
│  rag_system.py retrieve：BM25(k1=1.2,b=0.75) + 覆盖率归一        │
│    + 实体词命中 +0.35 + 关系词 +0.5/+1.0（KG-aware boost）      │
│    + subject_anchor ×2.5 + predicate_hint ×1.35（v3 锚定）       │
│    + panel_mode 意图路由（trust: verified×1.10 / refute:        │
│      rejected×1.15）★评审团三态参与排序                          │
│    + 同文档邻近窗口扩展 + graph_retriever 保守扩展（可选）       │
│    + unknown_entity_guard 拒答守卫                              │
│                                                                │
│  答案层：extractive（确定性摘录，score<1.0 拒答）                │
│         或 OpenAI-compatible LLM（只依据证据/保留条件/引用 ID） │
│  rag_api.py：FastAPI /health /ask /metrics，限流+可选 API key   │
│                                                                │
│  dense/rerank 基线：rag_dense_bge.py（bge-small-zh-v1.5）、     │
│    rag_hybrid.py（RRF）、rag_rerank.py —— 代码完备、结论暂不启用│
└────────────────────────────────┬───────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────┐
│                        统一评测体系（§4）                         │
│  KG 侧：结构完整性/污染检查 → 评审团交叉验证 → 人工签核 →        │
│         golden v1(24, gpt-5.6) / v2(44, panel consensus)        │
│  RAG 侧：silver 自动集(400+237+4 负例) → gold 集(24) →          │
│          检索层指标 → 答案层 5 系统 × 4 裁判 LLM-as-judge       │
└─────────────────────────────────────────────────────────────────┘
```

★ 号标注的 v2 严格层已通过 2025-10-20 统一实施接入 RAG（rag_index_v2 + 统一 gold 协议，见 [GOLD_UNIFIED_EVALUATION_REPORT.md](GOLD_UNIFIED_EVALUATION_REPORT.md)）；生产服务默认索引仍为 rag_index（kg_data v1 宽松层），切换至 rag_index_v2 前建议先完成 P0 的污染清理确认。

---

## 2. KG 构建工程（上游）

### 2.1 三层演进：为什么有三份数据

| 层 | 产物目录 | 证据 | 实体 | 候选事实 | 谓词数 | 条件绑定 | 主要缺陷/定位 |
|---|---|---:|---:|---:|---:|---:|---|
| v1 宽松层 | `kg_data/` | 4,341 | 36（4 类） | 1,063 | 4 | 0 | 无领域门控，含催化/交叉偶联污染；单模型审计仅 447/1,063 supported |
| v1 严格层 | `strict_extraction/`（+`strict_extraction_verify/`） | 1,290 | 64 | 119 | 4 | 0 | 谓词顺序错误、mg/MG 幽灵实体（卷入 61 条）、审计协议只判"关系存在"不判"三元组正确" |
| **v2 严格层** | `strict_extraction_v2/` | **1,411** | **126（12 类）** | **218** | **9** | **403 条 / 覆盖 52.8%** | 当前最优；效应类谓词验证率 36–50% 待改进 |

v2 修复的十项缺陷（F1–F10，详见 [CROSS_VALIDATION_REPORT.md](CROSS_VALIDATION_REPORT.md) §1）中，对下游最关键的三项：**F1** mg/MG/Mg 大小写敏感守卫（幽灵实体事实 61→0）；**F3** 主客体必须在谓词触发词所在子句内（跨句错绑消除）；**F5** 九类条件槽（concentration/potential/geometry/…）以 `UNDER_CONDITION` 边绑定到事实节点。

### 2.2 Schema 全貌（v2）

- **实体 12 类**：Additive(21)、Chemical(14)、Metal(3)、Method(15)、Process(18)、Via(12)、Property(19)、Electrolyte(5)、Substrate(4)、Mechanism(10)、Role(4)、Surface(1)。
- **谓词 9 种**（判定顺序：synergizes → improves_filling → inhibits → accelerates → used_as_* → adsorbs_on）：角色类 `used_as_leveler/suppressor/accelerator/inhibitor`、效应类 `inhibits_deposition / accelerates_deposition / improves_filling`、协同类 `synergizes_with`、界面类 `adsorbs_on`。
- **条件 9 槽**：concentration(123)、potential(81)、geometry(96)、time(39)、rotation(24)、percentage(27)、impedance(9)、pH(3)、temperature(1)；高频单位 μm(86)、mg/L(77)、V(61)、ppm(31)。
- **事实表示**：`事实 = 主体 + 谓词 + 客体 + 条件 + 证据 + 审核状态`，Neo4j 图模型见 [kg_pipeline/strict_neo4j_import_v2.cypher](kg_pipeline/strict_neo4j_import_v2.cypher)。

### 2.3 质量分层与评审团（KG 侧的核心方法学贡献）

1. **协议效度修复**：v1 审计（gpt-5.6，79.83% 接受率）只送"谓词+证据"，模型自抽主客体，测的是"关系是否存在"而非"三元组是否正确"；v2 将管线抽取的 subject/predicate/object/conditions 一并送审，对三元组本身逐项裁决（label + 三项布尔 + 修正建议 + 独立条件抽取）。
2. **五模型评审团**：deepseek-v4-pro-0813 / glm-5.3-shouyun / qwen3.7-max / qwen3.6-plus / kimi-k2.6（4 厂商 5 模型，temperature=0，共 1,090 次调用全部完成，断点续跑）。
3. **共识裁决**：verified（≥4/5 支持 + 逐项过半）120 条 55.05%（Wilson 95% CI [48.41%, 61.51%]）、quarantine（3/5）21 条、rejected（≤2/5 或 ≥2 contradicted）77 条。
4. **一致性统计**：Fleiss' κ 五分类 0.5661 / 二分类 0.6379；成对 Cohen's κ 0.42–0.73；单模型支持率 44.95%（deepseek）–70.18%（kimi）。
5. **按谓词验证率**：used_as_inhibitor 89.7%、used_as_leveler 81.3%、adsorbs_on 76.2%、improves_filling 50.0%、accelerates_deposition 39.3%、inhibits_deposition 36.4%——角色类可靠、效应类待加强。
6. **人工签核层**：46 条签核包（quarantine 全量 21 + verified/rejected 分层抽样）；dry run 用评审团之外的双模型盲标验证流程端到端可用（评审团 verified 精确率 93.33%，硬冲突仅 2/46）；产出标记为 `llm_pre_annotated_pseudo_gold`，真人签核待执行。

### 2.4 落图状态

Neo4j Community 5.26.32 实例在线（127.0.0.1:7474/7687，Java 进程实测 HTTP 200；`systemctl` 显示 inactive 是因为该实例以独立 Java 进程运行而非 systemd 托管）。v2 严格层已实测导入：StrictDocumentV2 48 / StrictEvidenceV2 1,411 / StrictEntityV2 126 / StrictValueV2 1,778 / StrictCandidateFactV2 218 / StrictConditionV2 403 / StrictPanelReviewV2 218，**悬空事实 0**，VerifiedFactV2 120 / QuarantineFactV2 21 / RejectedFactV2 77 标签就位。条件感知查询实测可用（如 `CMHT improves_filling Microvia [time=1h, geometry=150μm/80μm/19.1μm]`）。

---

## 3. RAG 检索问答工程（下游）

### 3.1 索引与检索单元

`rag_system.py build` 读取 KG CSV（documents/evidence/facts/entities/mentions/values），以**证据行（evidence）为检索单元**，enriched 文本 = 原文 + 提及实体名 + 数值 + 关联谓词，jieba 词级分词后建 BM25 索引（k1=1.2, b=0.75，含 df/倒排/长度归一），并记录源 CSV 的 sha1 指纹。两个现存索引：

- `rag_index/`（N=4,341，源自 `kg_data` v1 宽松层）——**生产服务默认索引**；
- `rag_index_strict/`（N=1,290，源自 `strict_extraction_verify` v1 严格层，46 篇文档、115 行带谓词、12,42 行带实体）——gold 评测用索引，属**一次性 ad-hoc 构建（仓库中无对应构建脚本，索引内记录 5 个源 JSONL 的 sha1 指纹）**，需在 P1 统一时补建可复现脚本。

### 3.2 检索策略谱系（演进与实测）

| 版本 | 机制 | silver entity 集 Hit@5 | gold 集 Hit@5 | 结论 |
|---|---|---:|---:|---|
| lexical BM25 | jieba + BM25 | 0.5193 | 0.4211 | 词法精确匹配缩写（JGB/SPS/PEG）天然占优 |
| KG-aware boost | + 实体命中 0.35、关系词 0.5/1.0 | **0.5408** | 0.4737 | 稳定 +2.15pp，代价 +2.6ms |
| BGE dense | bge-small-zh-v1.5 | 0.3305 | 0.053 | 模板问题+单行证据形态下全面落后，暂不启用 |
| RRF hybrid / rerank | BM25+dense 融合 | 0.4592 / 0.3476 | 0.263 | 均低于纯 BM25，不为混合而混合 |
| **subject-anchored v3** | + 主语锚定 ×2.5、谓词提示 ×1.35 | — | **0.6316**（MRR 0.394；Hit@10 0.7895） | **当前最优**；对抗探针证据 4/5 可检索 |

v3 的两个前置修复：拒答守卫误伤（旧 n-gram guard 导致 17/19 问题空返回，修复后 Hit@5 0.105→0.632）、长段落稀释（gold 证据平均 909 字符，锚定后 0.474→0.632）。

*注：gold 集上 BGE dense 0.053 / RRF 0.263 / clause 级 hybrid 0.316 三个数字仅载于 [GOLD_EVALUATION_REPORT.md](GOLD_EVALUATION_REPORT.md)，`evaluation/` 目录无对应 JSON 产物——复现实验时建议以 silver 集的 dense/hybrid JSON 为准或重跑。*

### 3.3 答案层与服务层

- **extractive 模式**（无 LLM 依赖）：确定性摘录证据原文 + 文献标题 + evidence_id；top1 score<1.0 时明确拒答。
- **LLM 模式**：OpenAI-compatible 接口；系统提示约束"只根据证据、保留条件、引用 evidence_id"。
- **服务**：`rag_api.py` FastAPI，`/health`（索引版本与规模）、`/ask`（支持 topk/window/predicate/doc_id/graph_expand/subject/predicate_hint 参数）、`/metrics`（请求/错误/拒答计数）；内存限流 + 可选 API key + 异常不泄露内部错误。

### 3.4 答案层实测（gold 集 24 条：19 可回答 + 5 对抗探针，4 裁判平均）

| 系统 | correctness | evidence_support | condition_retention | 对抗拒答率 |
|---|---:|---:|---:|---:|
| extractive | 0.993 | 1.000 | **0.797** | 0.267 |
| glm-5.3 | 0.958 | 0.924 | 0.639 | **0.842** |
| kimi-k2.6 | 0.979 | 0.937 | 0.648 | 0.722 |
| qwen3.7-max | 0.978 | 0.913 | 0.594 | 0.471 |
| deepseek-v4-pro-0813 | 0.910 | 0.896 | 0.639 | 0.667 |

裁判间 exact 一致率 0.83–0.96、within-1 ≥0.99。核心结论：**extractive 条件保留最强但不会拒答；LLM 的真正优势在对抗性拒答（0.47–0.84 vs 0.27）**；condition_retention 是所有 LLM 的共同短板（0.59–0.65）。

---

## 4. 统一评测体系（四层）

```text
第1层 结构与污染检查（KG 构建内部）
  · 119/119 严格候选关系字段完整、Neo4j 悬空 0
  · 污染关键词（catalys/CVD/CMP/cross-coupling/photocatal/corrosion/…）命中 0
第2层 语义验证（三元组级，真值逼近）
  · v1 单模型：deepseek-v4.1-flash（77/119）→ gpt-5.6-terra（95/119=79.83%，协议有缺陷）
  · v2 五模型评审团：120/218=55.05% + Fleiss' κ + 按谓词切片 + 共识条件融合（65/120 verified 带条件）
  · 人工签核层：46 条包（dry run：评审团 verified 精确率 93.33%；待真人签核）
第3层 基准集（Golden）
  · golden_benchmark v1：24 条（19 supported + 5 unsupported/contradicted），gpt-5.6 model-judged
  · golden_benchmark_v2：test 44 / train 174（seed 2025），五模型 panel consensus，待人工签核
  · qa_layer：184 条证据绑定 QA（GPT-5.6 生成，model_generated_needs_review）
第4层 下游 RAG 评测（检索层 + 答案层）
  · silver 自动集（可回归）：anchored 400 条（带原文线索）、entity 237 条（多有效 gold，实测
    平均 32.95 gold/题、中位 42、最大 53——注意 evaluation/README.md 写"约 9 条/题"
    与现评测集不符，属文档滞后）+ 4 条无答案探针；provenance 校验（validate_eval.py）
  · gold 集：24 条（rag_gold_builder.py 从 golden v1 生成自然语言问题，避免线索泄漏）
  · 检索层指标：Hit@k / Evidence Recall@k / Sufficient@k / MRR / 对抗证据命中 / 负例命中率 / 延迟
  · 答案层指标：correctness / evidence_support / condition_retention / 对抗拒答率
    （4 裁判 LLM-as-judge：temperature=0、0-2 分制归一、3 次重试 + reasoning_content 兜底，
     480 次调用成功 445）
```

**评测诚实性原则**（全仓库一贯执行）：silver ≠ gold；model-judged ≠ human gold；panel consensus ≠ 双人专家金标准；所有基准均带 `gold_status` 字段显式声明其真值等级。

### 4.1 两套真值源的统一（2025-10-20 已完成）

原断点 G6（真值源分裂）已通过 [gold_unified_builder.py](gold_unified_builder.py) 统一：两代 gold 映射为同一 QA schema（question_type 双轨制 + 多 gold 聚合），由 [gold_unified_eval.py](gold_unified_eval.py) 以统一协议评测。

| 基准 | 真值来源 | 规模 | 统一后状态 |
|---|---|---|---|
| golden_benchmark v1 | gpt-5.6 单模型判定 | 24 事实 → 23 条 | ✅ evaluation/gold_qa_v1.jsonl（统一 schema） |
| golden_benchmark v2 | 五模型评审团共识 | 44 事实 → 34 条 | ✅ evaluation/gold_qa_v2.jsonl（统一 schema，主真值） |
| 合并集 | — | 57 条 | ✅ evaluation/gold_qa_unified.jsonl（gold_version 区分） |
| jury/golden_final.jsonl | 双模型盲标 dry run | 46 | 待人工签核后并入（P5） |
| qa_layer 184 条 | GPT-5.6 生成 | 184 | 待审核后并入扩展集（P3 剩余） |

统一后主结果（v2 gold × rag_index_v2，v3 锚定 + 意图路由）：**factual Hit@5 0.7273 / MRR 0.4773 / Hit@10 0.7727，对抗反驳证据命中 7/8**——评审团三态加权相对无状态基线 factual +13.6pp、反驳 +3。全部数字见 [GOLD_UNIFIED_EVALUATION_REPORT.md](GOLD_UNIFIED_EVALUATION_REPORT.md)。

---

## 5. 两工程衔接现状诊断

> 2025-10-20 统一实施后更新：G1/G2/G3/G6 已解除，G4/G5/G7/G8 仍开放。

### 5.1 已接通的链路

1. `kg_data`（v1 宽松层）→ `rag_index` → 旧生产检索服务；KG-aware boost 消费 entities/mentions/values/facts 的谓词字段。
2. `golden_benchmark` v1 → `rag_gold_builder.py` → gold QA 24 条 → 检索层 + 答案层完整评测闭环。
3. `graph_retriever.py` 以 CSV 做保守图扩展（按谓词/共享实体扩展候选，不推断路径）。
4. **（统一新增）** `strict_extraction_v2` + `jury/consensus` → [rag_build_v2.py](rag_build_v2.py) → `kg_v2_unified/` → **rag_index_v2**（N=1,411，行级 panel_status 元数据 + 条件槽进文本）；两代 gold → [gold_unified_builder.py](gold_unified_builder.py) → 统一评测协议（[gold_unified_eval.py](gold_unified_eval.py)）；`retrieve()` 新增 panel_mode 意图路由（trust/refute）并已开放到 `rag_api` /ask 与答案层评测。

### 5.2 断点清单（G1–G8，含解除状态）

| # | 断点 | 状态 | 说明 |
|---|---|---|---|
| G1 | RAG 生产索引基于 v1 宽松层 | ✅ 已解除（能力侧） | rag_index_v2 以 v2 严格层为唯一信源；生产服务默认索引仍指向旧 rag_index，切换需 P0 污染确认 |
| G2 | 评审状态未进检索 | ✅ 已解除 | panel_status 行级元数据 + trust/refute 意图路由；实测 factual +13.6pp、反驳 +3/8 |
| G3 | 条件槽未进检索与生成 | 🟡 部分解除 | 条件文本已进索引（fact_tags）；问题侧条件解析过滤（按浓度/pH 匹配证据）尚未实现 |
| G4 | subject_anchor 依赖人工提供 | ❌ 开放 | v3 锚定信息仍来自评测字段/API 参数；需问题→实体表自动锚定 |
| G5 | Neo4j 未接入检索 | ❌ 开放 | 仍为 CSV 保守扩展；Cypher 路径/条件过滤查询待接 |
| G6 | 真值源分裂 | ✅ 已解除 | 统一 QA schema + 统一评测协议；v2 为主真值 |
| G7 | qa_layer 184 条 QA 未复用 | ❌ 开放 | 待人工审核后并入统一集 |
| G8 | 安全：明文 API key | ❌ 开放（最高优先） | auto_pipeline.sh 硬编码 router key，应立即轮换 |

---

## 6. 统一目标架构（v3 整合方案）

设计原则：**单一事实信源（v2 严格层 + 评审团共识）、状态贯穿（评审状态从构建传导到检索与生成）、条件一等公民（条件进检索过滤与答案约束）、评测同源（KG 与 RAG 用同一套 golden 真值）。**

```text
                    ┌──────────── 统一事实信源 ────────────┐
                    │ strict_extraction_v2 + jury 共识      │
                    │ evidence 1,411 / facts 218(三态)      │
                    │ conditions 403 / entities 126        │
                    └───────┬───────────────┬──────────────┘
                            │               │
                 ┌──────────▼──────┐   ┌────▼─────────────────┐
                 │  Neo4j 条件感知 │   │  v3 统一 RAG 索引     │
                 │  图谱（已有）    │   │  rag_index_v3（新建） │
                 │  · 三态标签     │   │  enriched +=         │
                 │  · 条件边       │   │   · panel_decision   │
                 │  · PubChem     │   │   · 条件槽 KV        │
                 └──────────┬──────┘   └────┬─────────────────┘
                            │               │
        ┌───────────────────▼───────────────▼──────────────────┐
        │              统一检索层（v3+）                          │
        │  1) 问题实体自动锚定：问题 → KG 实体表（126 实体 + 别名  │
        │     + PubChem 同义）匹配 → 自动 subject_anchor（解 G4）│
        │  2) BM25 + KG-aware boost（保持现有最优形态）           │
        │  3) 状态加权/过滤：verified ×boost，rejected 降权或     │
        │     仅在"检索否定证据"模式下保留（解 G2）                │
        │  4) 条件过滤：问题中解析出的条件（浓度/电位/pH…）与       │
        │     证据条件槽匹配，硬过滤或加权（解 G3）                │
        │  5) 图路径扩展（Phase 后期）：Neo4j Cypher 多跳邻居       │
        │     回溯原文证据，替代 CSV 保守扩展（解 G5）             │
        └────────────────────────┬────────────────────────────┘
                                 │
        ┌────────────────────────▼────────────────────────────┐
        │              统一答案层（双模式路由）                    │
        │  · 可回答/事实型 → extractive 或 LLM+强制条件清单        │
        │    （输出附 evidence_id + 条件 + 评审状态徽标）          │
        │  · 对抗/开放型 → LLM 判定支持性（发挥 0.84 拒答优势）   │
        │  · rejected 证据只在用户显式要求"找反例"时呈现          │
        └────────────────────────┬────────────────────────────┘
                                 │
        ┌────────────────────────▼────────────────────────────┐
        │              统一评测协议（同源真值）                    │
        │  · 真值：golden_benchmark_v2（44 test）为主，人工签核  │
        │    后的 golden_final 为最终 gold；qa_layer 184 条经    │
        │    审核后作扩展集（解 G6/G7）                          │
        │  · 检索层指标 + 答案层指标在同一 gold 上产出            │
        │  · silver 集保留为 CI 回归                             │
        │  · 消融：去评审状态加权 / 去条件过滤 / 去锚定 / 去 KG   │
        └──────────────────────────────────────────────────────┘
```

### 6.1 为什么这样统一（对应实测证据）

- 检索形态选 BM25+锚定而非 dense：本语料（单行/缩写主导证据、模板问题）实测 dense 全面落后（0.053–0.33 vs 0.63）；证据窗口化与真实问题积累后重测再议。
- 答案层双模式路由：extractive 条件保留 0.797 但拒答仅 0.267；LLM 拒答 0.47–0.84 但条件保留 0.59–0.65——两者互补，而非互斥。
- 状态加权有真值基础：评审团 verified 相对独立盲标的精确率 93.33%，rejected 中 70% 被确认拒绝、32/77 五票一致——用它们调节检索权重是可信的。

---

## 7. 分阶段实施路线

| 阶段 | 内容 | 验收标准 | 状态 |
|---|---|---|---|
| **P0 安全与止血（立即）** | 轮换 auto_pipeline.sh 泄漏的 API key，改环境变量注入；kg_data 宽松层与 rag_index 标记为 deprecated 或重建 | 仓库无明文 key；生产索引不含已知污染证据 | ❌ 待办 |
| **P1 v3 统一索引** | rag_system build 支持 strict_extraction_v2 + jury/consensus：panel_status 元数据与条件槽进索引；新建 `rag_index_v2` | 索引 N≈1,411；silver 集回归不劣化；G1/G2 解除 | ✅ **已完成**（2025-10-20：N=1,411、175 行带状态、115 事实带条件；trust 模式 factual +13.6pp） |
| **P2 实体自动锚定（2–3 天）** | 问题 → 实体表（entities.csv 126 实体 + 别名 + PubChem 同义词）匹配 → 自动 subject_anchor；接入 rag_api `/ask` | gold 集 Hit@5 在无人工 subject 字段下接近 0.63 上限；G4 解除 | ❌ 待办 |
| **P3 统一评测切换** | gold_qa 改从 golden_benchmark_v2 构建；qa_layer 审核后并入扩展集；跑通 v3 全量评测 | v2 真值上的检索+答案指标报告；G6/G7 解除 | 🟡 **核心已完成**（统一 schema + 统一评测协议 + 意图路由；qa_layer 并入与 LLM 答案层全量评测待运行，命令见统一报告 §5） |
| **P4 图检索与消融（1–2 周）** | Neo4j Cypher 路径检索 + 条件过滤查询接入 retrieve；对照实验（BM25 / +状态 / +条件 / +图路径）与消融 | 论文级对照表；G5 解除 | ❌ 待办（状态加权消融已完成，见统一报告 §3） |
| **P5 人工金标准（长期）** | 46 条签核包真人签核 → human_expert_signed golden；扩充 gold-coverage 文档集测召回 | 双人 κ 与专家级 golden 落地 | ❌ 待办 |

---

## 8. 产物清单与复现命令

### 8.1 核心产物

| 类别 | 路径 | 说明 |
|---|---|---|
| KG v1 宽松层 | `kg_data/`（6 CSV） | 48 docs / 4,341 evidence / 1,063 facts |
| KG v1 严格层 | `strict_extraction/`、`strict_extraction_verify/` | 119 facts + gpt-5.6 审计 |
| KG v2 严格层 | `strict_extraction_v2/`（jsonl+csv+summary） | 218 facts + 403 条件 + PubChem 链接 |
| **统一数据层** | `kg_v2_unified/` | v2 + jury 共识组装的 RAG 兼容目录（facts.csv 含状态与条件列） |
| 评审团产物 | `jury/`（reviews×5、consensus、三态事实、签核包） | 1,090 次调用原始记录 |
| Golden 基准 | `golden_benchmark/`（v1, 24）、`golden_benchmark_v2/`（44+174） | 真值等级见各 gold_status |
| **统一 gold 评测集** | `evaluation/gold_qa_{v1,v2,unified}.jsonl` | 23 / 34 / 57 条，统一 schema |
| QA 层 | `qa_layer/`（45 / 184） | 证据绑定候选评测题（待并入统一集） |
| RAG 索引 | `rag_index/`（4,341）、`rag_index_strict/`（1,290）、**`rag_index_v2/`（1,411，统一层）** | BM25 索引（含源指纹） |
| 评测产物 | `evaluation/`（silver/gold 集、对比 JSON、裁判记录、**unified_gold_metrics.json、ablation_panel_v2.json**） | 全部实测数字来源 |
| 报告 | 根目录 `*_REPORT.md` ×8 + `论文_KG构建与评测章节大纲_v2.md` | 各阶段实验报告（含 [GOLD_UNIFIED_EVALUATION_REPORT.md](GOLD_UNIFIED_EVALUATION_REPORT.md)） |

### 8.2 复现命令（关键链路）

```bash
# —— KG 构建链（v2）——
python3 kg_pipeline/strict_extract_v2.py --input 文献提取 --out strict_extraction_v2
python3 kg_pipeline/entity_link_pubchem.py
python3 kg_pipeline/llm_jury.py --input strict_extraction_v2/relations.jsonl \
    --out jury --base-url $URL --api-key $KEY \
    --models "deepseek-v4-pro-0813,glm-5.3-shouyun,qwen3.7-max,qwen3.6-plus,kimi-k2.6"
python3 kg_pipeline/jury_aggregate.py --facts strict_extraction_v2/relations.jsonl \
    --jury jury --golden-out golden_benchmark_v2 --seed 2025
python3 kg_pipeline/export_v2_csv.py
cypher-shell -u neo4j -p $PWD -f kg_pipeline/strict_neo4j_import_v2.cypher

# —— RAG 构建与服务 ——
python rag_system.py build --kg kg_data --docs 文献提取 --out rag_index
RAG_INDEX=rag_index uvicorn rag_api:app --host 0.0.0.0 --port 8000

# —— 评测链（silver 回归）——
python rag_eval_builder.py --kg kg_data --out evaluation/auto_anchored_silver.jsonl --per-predicate 100 --include-clue
python rag_compare.py --index rag_index --gold evaluation/auto_anchored_silver.jsonl --k 5 --out evaluation/comparison.json

# —— 评测链（gold 检索+答案）——
python rag_gold_builder.py --gold golden_benchmark/gold_test.jsonl \
    --relations strict_extraction_verify/relations.jsonl \
    --entities strict_extraction_verify/entities.jsonl --out evaluation/gold_qa.jsonl
python rag_gold_retrieval_eval.py --index rag_index_strict --gold evaluation/gold_qa.jsonl --out evaluation/gold_retrieval_metrics.json
RAG_LLM_API_KEY=... python rag_answer_eval.py --index rag_index_strict --gold evaluation/gold_qa.jsonl \
    --models glm-5.3 qwen3.7-max deepseek-v4-pro-0813 kimi-k2.6 --out evaluation/answers.jsonl
RAG_LLM_API_KEY=... python rag_judge.py --answers evaluation/answers.jsonl \
    --judges glm-5.3 qwen3.7-max deepseek-v4-pro-0813 kimi-k2.6 --out evaluation/judged.jsonl --workers 8
python rag_judge_aggregate.py --judged evaluation/judged.jsonl --out evaluation/gold_answer_metrics.json

# —— 统一 gold 评测链（2025-10-20 新增，主评测协议）——
python3 rag_build_v2.py                     # v2 数据 + jury 共识 → rag_index_v2
python3 gold_unified_builder.py             # 两代 gold → 统一 schema（v1/v2/unified）
python3 gold_unified_eval.py                # 统一检索评测（两代 × 五策略 × 意图路由）
python3 rag_answer_eval.py --index rag_index_v2 --gold evaluation/gold_qa_v2.jsonl \
    --models --out evaluation/answers_v2_extractive.jsonl   # extractive 链路（零 API 成本）
# LLM 答案层全量（预计 680 次调用，命令见 GOLD_UNIFIED_EVALUATION_REPORT.md §5）
```

---

## 9. 风险与治理

1. **安全（立即处理）**：`kg_pipeline/auto_pipeline.sh` 第 40 行硬编码 router API key——应轮换凭据并改为 `$API_KEY` 环境变量。
2. **真值等级**：全部现有基准均为 model-judged / panel-consensus / LLM 预标注伪金标准；论文级结论前必须完成 46 条真人签核（流程与脚本已就绪）。
3. **样本量**：gold 集 n=19（可回答）/ 5（探针），模型间差异不可信（报告已自我声明）；扩大 gold 是 P3 的一部分。
4. **dense 结论的条件性**：BGE 落后仅适用于"模板问题 + 单行证据"形态；证据窗口化后必须重测。
5. **召回未测**：KG 侧漏抽（recall）无独立 gold-coverage 文档集，属 P5 长期项。
6. **仓库内文档-数据不一致**：`evaluation/README.md` 与 `RAG_EVALUATION_REPORT.md` 写 entity 集"平均约 9 条 gold/题"，实测为平均 32.95（中位 42）；gold 报告中 dense/hybrid 三个数字无 JSON 产物。统一时（P3）应一并清理历史文档，以 JSON 产物为准。
7. **许可**：48 篇文献多为出版商版权物，服务对外发布前需审查文献许可。

---

*本文档基于 2025-10-20 仓库状态实测编写；对应代码/数据/报告均已存在于本仓库，引用处见文中链接。*
