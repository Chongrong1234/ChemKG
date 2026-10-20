# 第 X 章 领域知识图谱构建与质量评测

> 本章适合作为毕业论文中“方法与实验”部分的半章内容。研究对象为铜/钴电沉积、电镀添加剂及 PCB 通孔/盲孔填充领域。当前已完成候选 KG、严格抽取层、GPT-5.6 语义复核、Neo4j 存储和证据绑定 QA 扩展；最终人工 Gold 标注和下游 RAG 对照实验可在后续实验中补充。

## X.1 研究目标与总体思路

传统知识图谱构建方法通常将文本中的实体和关系直接转换为三元组，但对于电镀和电化学文献而言，科学事实往往依赖具体实验条件。例如，某添加剂对沉积行为的影响可能只在特定浓度、电流密度、温度、pH 或孔结构下成立。因此，本文不将知识表示为无条件三元组，而是将事实、实验条件、数值、证据来源和审核状态联合建模。

本文的构建目标包括：

1. 从电镀领域论文中识别化学物质、添加剂、工艺、实验方法和性能指标等实体；
2. 抽取添加剂与电沉积、孔填充及电化学行为之间的关系；
3. 保存浓度、温度、电流密度、时间、孔径和孔深等限定信息；
4. 为每条事实绑定可以回溯到原文的证据片段；
5. 通过规则检查、GPT-5.6 语义复核和人工审核区分可信、拒绝和待裁决事实；
6. 在 Neo4j 中实现图谱存储、多跳查询和质量审计。

总体流程如下：

```text
领域文献
  → 文档解析与清洗
  → 严格领域筛选
  → 实体识别
  → 实体规范化与消歧
  → 关系和属性抽取
  → 数值、单位与实验条件抽取
  → 证据绑定
  → 候选事实生成
  → 规则/模型语义复核
  → VerifiedFact / RejectedFact / QuarantineFact
  → Neo4j 存储与查询
```

## X.2 领域 Schema 设计

### X.2.1 实体类型

根据当前文献内容，本文设计如下主要实体类型：

| 实体类型 | 示例 | 说明 |
|---|---|---|
| Chemical | CuSO₄、H₂SO₄、Cl⁻ | 化学物质或电解液组分 |
| Additive | CMHT、PEP、SPS、JGB、PVP、ZPS | 电镀添加剂 |
| Metal | Cu、Co、Ni | 沉积金属 |
| Electrolyte | 酸性铜电解液、钴电解液 | 电解液体系 |
| Process | 铜电镀、钴电沉积、盲孔填充 | 工艺过程 |
| Substrate | PCB、铜基底、晶圆 | 基底或样品 |
| Via | 通孔、盲孔、微盲孔 | 孔结构 |
| Method | CV、EIS、GM | 电化学或材料表征方法 |
| Property | 填充性能、表面铜厚度、过电位 | 性能指标 |
| Condition | 温度、pH、浓度、电流密度 | 实验条件 |
| Mechanism | 吸附、极化、成核、传质 | 作用机制 |
| Document | 论文、专利、实验记录 | 知识来源 |
| Evidence | 段落、表格单元格、图注 | 事实证据 |

### X.2.2 关系类型

本文重点关注以下关系：

```text
used_as_suppressor
used_as_accelerator
used_as_leveler
used_as_inhibitor
added_to_electrolyte
synergizes_with
adsorbs_on
inhibits_deposition
accelerates_deposition
improves_filling
measured_by
performed_under_condition
produces_measurement
affects_nucleation
affects_growth
affects_mass_transfer
forms_complex_with
```

关系类型不仅表示语义关系，还需要定义主体类型、客体类型、关系方向和适用条件。例如，`improves_filling` 只有在证据明确说明孔填充、填充率、底部填充、无空洞或类似结果时才成立；提高硬度、附着力或催化活性不能直接映射为该关系。

### X.2.3 扩展事实表示

本文将领域事实表示为：

```text
事实 = 主体 + 关系 + 客体 + 条件 + 数值/单位 + 证据 + 审核状态
```

例如：

```text
CMHT
  --improves_filling-->
BlindViaFilling

条件：
  concentration = 6 mg/L
  current_density = 2 A/dm²
  temperature = 293 K
  via_diameter = 150 μm
  via_depth = 80 μm

证据：
  document_id + evidence_id + 原文片段
```

这种表示方式能够避免将特定条件下成立的结论泛化为无条件知识。

## X.3 文献预处理与严格领域筛选

### X.3.1 文献解析

本文使用已经清洗和解析的领域文献作为输入。每篇文献保存唯一文档标识、文档路径、标题、文本哈希和版本信息。文本中保留正文、章节、表格和图注的行号或位置，以便后续绑定证据。

### X.3.2 领域相关性筛选

当前严格抽取器使用领域关键词和排除词进行候选筛选。领域关键词包括：

```text
copper, cobalt, electroplating, electrodeposition,
microvia, blind via, through-hole, filling,
additive, inhibitor, suppressor, accelerator,
leveler, current density, CV, EIS
```

排除条件包括：

```text
References/参考文献
DOI、URL 和典型引用行
catalysis、CVD、CMP、photocatalysis、corrosion
cross-coupling 等非目标领域内容
```

关键词筛选的作用是减少输入噪声，而不是直接判断事实真伪。最终事实是否有效，还需要经过局部关系判断和证据审核。

## X.4 实体识别与实体规范化

### X.4.1 实体识别

当前实现采用领域词典和正则表达式进行候选实体识别，覆盖：

- 化学物质和添加剂；
- 电解液组分；
- 电镀和电沉积过程；
- CV、EIS、GM 等实验方法；
- 填充性能、表面铜、过电位和极化等属性。

每个实体提及保存：

```text
mention_id
entity_id
mention_text
entity_type
document_id
evidence_id
line_no
```

### X.4.2 实体规范化

对实体名称执行 Unicode NFKC、首尾空格去除、大小写统一、空白折叠和化学符号规范化。例如：

```text
μm、µm、um → μm
Cl−、Cl- → Cl-
```

但是，字符串规范化不等同于实体消歧。对于 `CV` 与 `cyclic voltammetry`、`CuSO4` 与“硫酸铜”、中英文名称和同名化学物质，需要结合上下文、实体类型、化学式和外部标识符进行确认。

### X.4.3 实体消歧与融合

本文将实体融合表示为：

```text
Mention → CanonicalEntity
```

候选匹配综合考虑：

- 名称相似度；
- 实体类型一致性；
- 上下文相似度；
- 邻居关系一致性；
- 外部数据库 ID；
- 缩写和全称释义。

当证据不足时不强制合并，而是保留为待审核匹配。这样可以降低错误合并导致的虚假推理路径。

## X.5 关系、属性与实验条件抽取

### X.5.1 关系抽取

初始候选关系通过领域触发词、局部句子和实体对共同确定。严格版本要求关系必须满足领域上下文约束：

- `inhibits_deposition`：抑制语义和沉积/电镀语境同时出现；
- `accelerates_deposition`：加速语义和沉积/电镀语境同时出现；
- `improves_filling`：改善语义与填充、通孔、盲孔或孔结构语义同时出现；
- `synergizes_with`：至少两个化学物或添加剂实体，并明确出现协同语义。

对于复杂关系，本文使用 GPT-5.6 进行结构化语义复核。模型只允许依据证据片段判断，不允许根据外部常识补写关系。

### X.5.2 数值和实验条件抽取

抽取的条件包括：

- 添加剂浓度；
- 金属盐和酸浓度；
- 温度；
- pH；
- 电流密度；
- 电位；
- 电镀时间；
- 搅拌或流速；
- 孔径、孔深和深宽比；
- 测量方法和性能数值。

数值记录保存：

```text
value_id
value
unit
raw_text
evidence_id
document_id
```

重点排除 DOI、页码、URL、地址和化学式中的数字误识别，并对单位大小写、Unicode 符号、负值和量纲范围进行校验。

## X.6 证据优先的事实组织

本文不直接将抽取结果作为最终事实，而是建立候选事实层和验证层。

Neo4j 严格层结构为：

```text
(:StrictDocument)-[:STRICT_HAS_EVIDENCE]->(:StrictEvidence)
(:StrictEvidence)-[:STRICT_MENTIONS]->(:StrictEntity)
(:StrictEvidence)-[:STRICT_REPORTS_VALUE]->(:StrictValue)
(:StrictCandidateFact)-[:STRICT_SUPPORTED_BY]->(:StrictEvidence)
(:StrictCandidateFact)-[:STRICT_SUBJECT]->(:StrictEntity)
(:StrictCandidateFact)-[:STRICT_OBJECT]->(:StrictEntity)
```

事实状态划分为：

```text
StrictCandidateFact
  → VerifiedFact
  → RejectedFact
  → QuarantineFact
```

只有同时满足“主体、关系、客体、方向、条件、数值和证据均可确认”的事实，才可升级为最终 VerifiedFact。

### X.6.1 当前构建规模

基于 48 篇已清洗文献实际运行严格抽取流程，得到的图谱规模如表 X-1 所示。

**表 X-1 严格证据层图谱构建规模**

| 数据类型 | 数量 |
|---|---:|
| 文档（StrictDocument） | 48 |
| 证据片段（StrictEvidence） | 1,290 |
| 候选实体（StrictEntity） | 64 |
| 实体提及（StrictMentions） | 3,216 |
| 数值/单位记录（StrictValue） | 1,295 |
| 候选关系（StrictCandidateFact） | 119 |

候选关系的类型分布如表 X-2 所示。

**表 X-2 候选关系类型分布**

| 关系类型 | 数量 | 占比 |
|---|---:|---:|
| `inhibits_deposition` | 64 | 53.8% |
| `improves_filling` | 26 | 21.8% |
| `accelerates_deposition` | 22 | 18.5% |
| `synergizes_with` | 7 | 5.9% |
| 合计 | 119 | 100% |

抽取的数值/单位记录覆盖浓度、电位、温度、时间和几何尺寸等条件，其单位分布如表 X-3 所示。

**表 X-3 数值/单位记录的单位分布（前 10 项）**

| 单位 | 数量 | 单位 | 数量 |
|---|---:|---|---:|
| mg/L | 246 | rpm | 102 |
| μm | 199 | min | 74 |
| V | 196 | mV | 64 |
| h | 141 | nm | 56 |
| % | 133 | K | 51 |

其余单位包括 g/L（25 条）、A/dm²（4 条）等。需要说明的是，当前数值记录仍为候选状态，需人工校验其与具体实验指标的绑定关系。

## X.7 质量评测设计与实验结果

### X.7.1 抽取质量：宽松基线与严格证据层对比

构建独立 Gold-IE 文档集后，可报告 Entity/Relation Strict Precision、Recall 和 F1。在完成人工标注之前，本文先从领域相关性、结构完整性和污染控制三个可复现角度对比宽松基线与严格证据层，结果如表 X-4 所示。

**表 X-4 宽松基线与严格证据层对比**

| 指标 | 宽松关键词基线 | 严格证据层 |
|---|---:|---:|
| 候选事实数量 | 1,063 | 119 |
| 领域相关率 | 52.4%（557/1,063） | 100%（119/119） |
| 催化/CVD/CMP/参考文献/DOI 污染命中 | 大量混入 | 0 |
| 缺失 evidence_id | — | 0 |
| 缺失 subject_id / object_id | — | 0 |
| Neo4j 中证据悬空事实 | — | 0 |

宽松基线中 506 条候选（47.6%）被判定为催化、CVD、CMP、腐蚀或参考文献等非目标领域内容；严格证据层通过领域上下文约束、参考文献过滤和局部主客体绑定，在规则层面消除了已定义的污染模式。严格层候选数量下降约 88.8%，体现了“宁可降低召回、先保证证据质量”的保守取舍。

### X.7.2 事实正确性：模型辅助语义审计

使用 GPT-5.6（`gpt-5.6-terra`，temperature=0）对 119 条严格候选关系进行结构化语义复核，模型仅依据证据文本判断，结果如表 X-5 所示。

**表 X-5 GPT-5.6 语义审计标签分布**

| 审计标签 | 数量 | 比例 |
|---|---:|---:|
| supported | 95 | 79.83% |
| partial | 9 | 7.56% |
| unsupported | 10 | 8.40% |
| ambiguous | 3 | 2.52% |
| contradicted | 2 | 1.68% |
| 合计 | 119 | 100% |

按关系类型细分的审计结果如表 X-6 所示。

**表 X-6 按关系类型的 GPT-5.6 审计结果**

| 关系类型 | 总数 | supported | partial | unsupported | contradicted | ambiguous |
|---|---:|---:|---:|---:|---:|---:|
| `inhibits_deposition` | 64 | 57 | 4 | 2 | 0 | 1 |
| `improves_filling` | 26 | 17 | 4 | 2 | 2 | 1 |
| `accelerates_deposition` | 22 | 15 | 1 | 6 | 0 | 0 |
| `synergizes_with` | 7 | 6 | 0 | 0 | 0 | 1 |

其中 `accelerates_deposition` 的拒绝比例（6/22，27.3%）明显高于其他关系，说明“加速电化学过程”（如加速析氢、增强电导）与“加速金属沉积”容易混淆，后续应加强该关系的定义和条件约束。GPT-5.6 判定的 118/119 条证据片段有效（evidence_valid=true），仅 1 条被判为证据无效。

需要强调：79.83% 是 GPT-5.6 的模型判定支持率，不能等同于领域专家标注的最终 Precision。

### X.7.3 双模型一致性检验

为降低单一模型判定偏差，本文另使用 `deepseek-v4.1-flash` 对同一批 119 条候选关系独立审计，两模型的一致性如表 X-7 所示。

**表 X-7 两个模型对 119 条候选关系的判定一致性**

| 一致性指标 | 数值 |
|---|---:|
| 五分类完全一致 | 85/119（71.43%） |
| 二分类（supported / 非 supported）一致 | 93/119（78.15%） |

主要分歧集中在（deepseek → GPT-5.6）：`partial`→`supported` 22 条、`unsupported`→`partial` 4 条，说明两模型对“部分支持”边界判定尺度不同。该结果说明模型审计可作为人工审核的优先级排序手段，但最终裁决仍需领域专家完成。

### X.7.4 Golden Benchmark 划分

以随机种子 2025 将 119 条 GPT-5.6 判定样本按 8:2 划分，固定 24 条作为测试集，其完整性与标签分布如表 X-8、表 X-9 所示。

**表 X-8 Golden 测试集完整性检查**

| 检查项 | 结果 |
|---|---:|
| 测试样本数 | 24 |
| fact_id 唯一数 | 24 |
| Evidence 绑定 | 24/24 |
| 必填字段缺失 | 0 |
| 测试集支持率 | 79.17%（19/24） |

**表 X-9 Golden 测试集标签分布**

| 标签 | 数量 |
|---|---:|
| supported | 19 |
| unsupported | 4 |
| contradicted | 1 |

该测试集为 GPT-5.6 model-judged golden benchmark，可作抽取流程的回归测试基准，但不能替代专家金标准。

### X.7.5 证据绑定问答评测层

为支撑后续 KG-RAG 系统评测，本文使用 GPT-5.6 从严格证据层生成证据绑定问答（temperature=0.2），去重后得到 184 条 QA，其规模与完整性如表 X-10 所示。该问答层的构建与筛选属于本章 KG 质量控制范畴，其下游使用效果留待后续章节统一评测。

**表 X-10 问答评测层构建结果**

| 指标 | 数值 |
|---|---:|
| 输入证据候选 | 1,108 |
| 去重后 QA 数量 | 184 |
| 覆盖证据片段 | 181 |
| Neo4j 中 Evidence 绑定 | 184/184 |
| 无证据 QA（dangling） | 0 |

所有 QA 均标注 `gold_status=model_generated_needs_review`，仅作为 KG-RAG 的候选评测集，其答案不得直接写入 VerifiedFact。

### X.7.6 知识完整性评测

完整性评测需要从未参与构图的文献独立标注 gold facts，再计算 Entity Recall、Relation Recall、Qualifier Recall、Value Recall 和 Evidence Recall。该项依赖后续构建 10–20 篇独立 Gold-Coverage 文档，当前尚未完成，本文不以 KG 内部反向生成的数据充当 gold。

### X.7.7 消融实验设计

计划移除以下模块并观察事实支持率、污染命中和证据召回的变化：

- 严格领域过滤；
- 实体规范化；
- 实验条件；
- 证据绑定；
- LLM 语义审核；
- Quarantine 状态。

其中“去除严格领域过滤”可由表 X-4 的宽松基线对比部分体现：去除后候选数增至 1,063 条，但领域相关率由 100% 降至 52.4%。完整消融留待统一评测框架下运行。

下游检索与问答效用评测（BM25 RAG、向量 RAG、Flat Triple、KG-only、KG+Evidence 等系统对比）不在本章展开，将在后续章节结合本文构建的 KG-RAG 系统统一评测。本章生成的 184 条证据绑定问答（表 X-10）将作为该部分的基础评测集。

## X.8 章节小结

本节构建了一个面向电镀科学文献的证据优先知识图谱。与直接抽取无条件三元组不同，本文将实体、关系、数值、实验条件和证据统一组织，并通过严格领域过滤和模型语义审核降低跨领域污染。在 48 篇文献上的实验表明：严格证据层在将候选事实从宽松基线的 1,063 条收紧至 119 条的同时，将领域相关率从 52.4% 提升至 100%，催化/CVD/CMP/参考文献等污染命中降为 0，且全部候选关系均具有主体、客体和证据绑定；GPT-5.6 语义审计将其中 95 条判定为支持候选（79.83%），双模型一致性检验（二分类一致率 78.15%）进一步说明模型审计结果稳定但不可替代专家裁决；此外，本节构建了 184 条证据绑定的候选问答，作为后续 KG-RAG 评测的基础数据集。图谱质量评测体系覆盖抽取准确性、事实正确性、知识完整性和证据可追溯性；人工 Gold 标注、知识完整性召回以及基于该图谱的下游检索与问答实验将在后续章节中结合 KG-RAG 系统统一展开。
