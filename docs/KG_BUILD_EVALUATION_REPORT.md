# 电镀领域 KG 构建与质量评测报告（初版）

## 1. 当前数据与目标

当前工作区包含已清洗的论文全文 `full.md`、PDF、表格/图像解析结果。文献主题集中在：铜/钴电沉积、电镀添加剂、抑制剂/加速剂/整平剂、PCB 通孔/盲孔填充、电化学表征和沉积性能。

目标是构建一个可追溯的领域 KG，并用 Neo4j 存储；同时保留原始证据、候选事实、人工审核结果和外部 QA 评测数据的边界。

## 2. 已实现的代码

- `kg_pipeline/build_kg.py`：递归读取 `文献提取/**/full.md`，筛选领域文献，生成 CSV，并提供 Neo4j Bolt 导入入口。
- `kg_pipeline/evaluate_kg.py`：为候选事实生成随机人工审核模板。
- `kg_pipeline/README.md`：运行、图模型、审核和评测说明。

当前管线的设计原则是**保守候选化**：自动匹配只能产生 `CandidateFact`，不能直接产生 `VerifiedFact`。每条候选事实保存 `doc_id`、`evidence_id`、文献行号及证据文本。

## 3. Neo4j 图模型

```text
(:Document)-[:HAS_EVIDENCE]->(:Evidence)
(:Evidence)-[:MENTIONS]->(:Entity)
(:Evidence)-[:REPORTS_VALUE]->(:Value)
(:CandidateFact)-[:SUPPORTED_BY]->(:Evidence)
(:CandidateFact)-[:EXTRACTED_FROM]->(:Document)
```

后续人工确认后使用：

```text
(:VerifiedFact)-[:SUPPORTED_BY]->(:Evidence)
```

QA 数据单独建模为：

```text
(:EvaluationQuestion)-[:HAS_GOLD_ANSWER]->(:GoldAnswer)
(:GoldAnswer)-[:SUPPORTED_BY]->(:EvaluationEvidence)
```

SciQ、WorldTree、ScienceQA、OpenBookQA、MMLU、QASPER 等数据不应因为存在 gold answer 就自动成为领域事实。只有回溯原始证据、补全实验条件并通过领域审核后，才可升级为候选或验证事实。

## 4. 领域 Schema 建议

### 核心实体

- `Chemical` / `Additive`
- `Metal`
- `Electrolyte`
- `Substrate`
- `Via`
- `Process`
- `Experiment`
- `ElectrochemicalMethod`
- `Property`
- `Measurement`
- `Condition`
- `Morphology`
- `Mechanism`
- `Paper`
- `Evidence`
- `EvaluationQuestion`

### 核心关系

- `used_as_suppressor`
- `used_as_accelerator`
- `used_as_leveler`
- `used_as_inhibitor`
- `added_to_electrolyte`
- `synergizes_with`
- `adsorbs_on`
- `inhibits_deposition`
- `accelerates_deposition`
- `improves_filling`
- `measured_by`
- `performed_under_condition`
- `produces_measurement`
- `affects_nucleation`
- `affects_growth`
- `affects_mass_transfer`
- `forms_complex_with`

### 必须作为限定信息保留

- 电流密度；
- 波形；
- 温度；
- pH；
- 时间；
- 电解液组成；
- 添加剂浓度；
- 搅拌/流速；
- 基材和种子层；
- 孔径、孔深、深宽比；
- 测试方法；
- 数值、单位和误差；
- 证据文档、章节、表格/图片位置。

## 5. 数据源融合方案

### 5.1 主事实来源

当前已清洗的电镀论文、补充材料、专利和实验 CSV。它们是 Verified KG 的主来源。

### 5.2 化学实体背景

优先接入 PubChem，用于补充名称、同义词、CAS、分子式、SMILES、InChI 和化学实体 ID。Materials Project、OQMD、NOMAD、JARVIS 可作为材料结构和计算性质背景，但必须区分计算性质与实验电镀性能。

### 5.3 QA 数据

- QASPER：优先用于科学全文问答、证据召回和 provenance 评测；重新按本项目 Schema 抽取后才可能进入 CandidateFact。
- SciQ / WorldTree：基础科学和解释链背景；默认不进入主事实图。
- ScienceQA：图表、实验图、多模态 challenge set。
- OpenBookQA：基础科学多跳推理。
- MMLU：`high_school_chemistry`、`college_chemistry`、`conceptual_physics`、`college_physics`、工程子集的冻结外部评测；它没有专门的材料科学子集。
- ChemQA、MatSciQA 等同名数据集在版本、许可和来源上容易混淆，在核对论文、官方仓库、数据卡和许可证前不纳入正式管线。

## 6. 质量评测

### 6.1 图中事实正确性

从最终图中分层抽样，回查原文或表格：

- `supported`
- `partially_supported`
- `unsupported`
- `contradicted`
- `ambiguous`
- `not_verifiable`

重点抽查：数值/单位、浓度、温度、电流密度、孔径/孔深、否定、比较句、跨句关系、表格关系、长尾添加剂和新文献。

### 6.2 独立 gold 完整性

另选文档，由领域专家从原文独立标注实体和事实，然后测：

- Entity strict P/R/F1；
- Relation strict P/R/F1；
- Qualifier F1；
- 数值/单位准确率；
- Evidence span accuracy；
- 实体融合 Pairwise/B³ F1。

不要从 KG 内部反向生成 gold，否则无法测漏抽。

### 6.3 下游效用

对比：原文 BM25/向量 RAG、KG-only、KG+原文证据、非图平铺检索和图结构检索。报告 Recall@k、MRR、证据召回、答案 F1、引用准确率和 unsupported claim rate。

### 6.4 Schema 与数据约束

执行 domain/range、单位、数值范围、关系方向、重复边、证据覆盖、时间冲突和 SHACL 约束检查。

## 7. 当前必须人工检查的地方

1. 实体规范化和同名异物；
2. 添加剂角色，尤其是 suppressor / inhibitor / leveler 的边界；
3. 关系方向和关系粒度；
4. 数值、单位与单位换算；
5. 实验条件是否绑定到具体事实，而不是作为全局属性；
6. 否定、假设、可能性和比较句；
7. 表格、图、跨句和跨文档关系；
8. 文献之间的矛盾；
9. 候选事实是否升级为 VerifiedFact；
10. 外部 QA 的答案是否真的有原始证据支持。

## 8. 已执行构建与审计

本轮已实际运行构建脚本，得到：

| 类型 | 数量 |
|---|---:|
| 文档 | 48 |
| 候选实体 | 36 |
| 实体提及 | 8,552 |
| 证据片段 | 4,341 |
| 候选事实 | 1,063 |
| 数值/单位记录 | 2,905 |

已生成 `kg_review.csv`，包含 400 条随机审核模板；其 `review_label` 全部为空，因此它不是已完成的人审结果。

另外增加 `kg_pipeline/audit_and_promote.py`，运行了保守的子代理辅助初筛。该初筛不是领域专家最终裁决，只用于优先级分流：

| 初筛标签 | 数量 |
|---|---:|
| supported（triage_supported，仍需人工确认） | 399 |
| partially_supported（隔离待审） | 178 |
| unsupported（拒绝候选） | 486 |

结果位于 `kg_audit/`：

- `fact_reviews.csv`：1,063 条带初筛标签的审计记录；
- `verified_candidates.csv`：399 条，仅表示机器/子代理规则初筛通过，不是最终 VerifiedFact；
- `rejected_candidates.csv`：486 条污染或证据不足候选；
- `quarantine.csv`：178 条需要人工裁决；
- `audit_summary.csv`：汇总统计。

子代理审计发现的主要问题是：有机催化、纳米催化、腐蚀、CVD、CMP、涂层附着/硬度和纯参考文献条目被错误映射到电沉积关系。因此 **399 条 triage_supported 不能直接作为论文中的 KG 准确率或已验证事实数量**。

审计还发现数值抽取存在 DOI/页码/URL 污染。需要优先处理：百分比超范围 19 条、nm 负值或大于 1000 的 17 条、h 负值 9 条，并对含 DOI/http/参考文献模式的证据禁止自动生成数值。

## 9. Neo4j 部署状态

已创建：

- `kg_pipeline/neo4j_schema.cypher`：基础候选图导入；
- `kg_pipeline/neo4j_audit.cypher`：Review、TriageSupportedFact、RejectedFact、QuarantineFact 导入和审计查询。

本轮已通过官方 Neo4j Debian repository 安装 Neo4j Community 5.26.32，并启动本地服务。连接验证成功：`cypher-shell -u neo4j -p kgpass123 'RETURN 1 AS ready'` 返回 `ready=1`。

已将 `kg_data/*.csv` 和 `kg_audit/*.csv` 复制到 `/var/lib/neo4j/import/`，并成功执行：

- `kg_pipeline/neo4j_schema.cypher`；
- `kg_pipeline/neo4j_audit.cypher`。

候选图导入后节点统计：Document 48、Entity 36、Evidence 4,341、Value 2,905、CandidateFact 1,063。关系统计：HAS_EVIDENCE 4,341、MENTIONS 8,552、REPORTS_VALUE 2,905、SUPPORTED_BY 1,063、EXTRACTED_FROM 1,063。

审计层导入后新增：Review 1,063、TriageSupportedFact 399、RejectedFact 486、QuarantineFact 178。审计查询返回三类标签计数为：supported 399、partially_supported 178、unsupported 486；候选事实 dangling evidence 数为 0。

最终关系统计中 `SUPPORTED_BY` 为 1,462，是因为 1,063 个 CandidateFact 的证据关系和 399 个 TriageSupportedFact 的证据关系同时保留。该结果符合“保留候选事实、不覆盖来源”的设计。

Neo4j 验证查询已另存为 `kg_pipeline/neo4j_queries.cypher`。

## 10. LLM 语义复核结果

用户提供了 OpenAI-compatible API，本轮已完成连通性测试，并使用 `deepseek-v4.1-flash`、temperature 0 对严格版本的 119 条候选关系进行结构化语义复核。每条请求要求模型只依据证据文本输出关系标签、主体、客体、条件、证据有效性、置信度和理由。

结果如下：

| 标签 | 数量 |
|---|---:|
| supported | 77 |
| partial | 29 |
| unsupported | 11 |
| contradicted | 2 |
| 合计 | 119 |

其中 77 条是 LLM 支持候选，29 条进入隔离复核，13 条被 LLM 判定为证据不足或关系方向错误。该结果不是最终人工 Precision；所有记录仍标记 `human_adjudication=required`。

输出：

- `strict_extraction/llm_reviews.jsonl`；
- `strict_extraction/llm_reviews.csv`；
- `strict_extraction/llm_verified_candidates.csv`；
- `strict_extraction/llm_rejected_candidates.csv`；
- `strict_extraction/llm_quarantine.csv`。

Neo4j 已导入 `StrictLLMReview` 审计层，查询统计返回 119 条审核记录；其中严格候选节点有 77 条 `llm_supported`、13 条 `llm_rejected`，其余为 `llm_quarantine`。导入脚本为 `kg_pipeline/llm_audit_neo4j.cypher`。

## 11. 当前必须人工检查的优先级

P0：

1. 纯参考文献、章节标题、图表标题、DOI/URL 误抽取；
2. 催化/CVD/CMP/腐蚀/涂层等跨领域污染；
3. 添加剂主语、关系方向和对象是否明确；
4. `synergizes_with` 是否同时有两个实体和协同结果；
5. `improves_filling` 是否真的有孔填充结果，而不是附着、硬度或催化性能。

P1：

1. 浓度、电流密度、温度、pH、时间和孔几何条件绑定；
2. 负值、异常单位、H/h、K/k、V/v 的语义判定；
3. CV/EIS/GM 等缩写与全称对齐；
4. 中英文同义词和化学式规范化；
5. 文献冲突和条件依赖结论。

只有满足“证据明确支持＋主体/关系/客体完整＋条件和数值适用＋两名独立审核者一致或主管裁决”的事实，才应进入最终 `VerifiedFact`。
