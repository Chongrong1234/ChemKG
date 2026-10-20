# 电镀领域知识图谱详细构建与评测流程

## 1. 研究对象

本项目面向铜/钴电沉积、酸性铜电镀、PCB 通孔/盲孔/微盲孔填充、添加剂作用机理和电化学表征文献。

主要知识对象：

- 添加剂：CMHT、PEP、SPS、JGB、PVP、ZPS、MPS 等；
- 电解液：铜盐、钴盐、硫酸、氯离子及添加剂组合；
- 工艺：电镀、电沉积、通孔/盲孔填充；
- 条件：浓度、温度、电流密度、pH、时间、流速、孔径和孔深；
- 表征：CV、EIS、GM、过电位、极化、沉积速率；
- 结果：填充性能、表面铜厚度、空洞、接缝、硬度、导电性。

## 2. 总体构建架构

```text
PDF/HTML/实验数据
  → 文档解析与版本记录
  → 严格领域筛选
  → 实体识别
  → 实体规范化与消歧
  → 关系识别
  → 数值、单位和实验条件抽取
  → Evidence 证据绑定
  → CandidateFact
  → LLM/规则审计
  → Verified / Rejected / Quarantine
  → Neo4j Property Graph
```

系统采用证据优先设计：自动抽取结果不能直接成为最终事实。

## 3. 当前实现的模型和规则

### 3.1 文档筛选

当前实现使用严格领域关键词和排除词：

- 领域词：electroplating、electrodeposition、microvia、blind via、through-hole、filling、copper、cobalt 等；
- 排除词：catalysis、CVD、CMP、photocatalysis、corrosion、cross-coupling、reference、DOI、HTTP 等。

### 3.2 实体识别

当前严格抽取器使用领域词典和正则表达式识别：

- Additive；
- Chemical；
- Method；
- Process；
- Property。

可扩展模型包括 SciBERT Token Classification、GLiNER、BERT-CRF，但本轮正式结果使用的是可复现的严格规则抽取器。

### 3.3 实体规范化

执行 Unicode NFKC、大小写、空格和单位规范化；缩写与中英文同义词只作为候选，不自动强制合并。

### 3.4 关系识别

当前关系候选必须满足局部证据约束：

- `inhibits_deposition`：出现抑制词且证据明确涉及电镀/沉积；
- `accelerates_deposition`：出现加速词且证据明确涉及电镀/沉积；
- `improves_filling`：出现改善词且涉及填充、通孔、盲孔或孔；
- `synergizes_with`：至少两个化学物/添加剂实体和协同语义。

### 3.5 数值与条件

抽取数值、单位、浓度、温度、电流密度、时间、孔径和孔深。所有数值保留 raw text 和 evidence_id，后续需要进行 DOI/页码、单位大小写、范围和量词绑定检查。

### 3.6 LLM 复核

使用用户提供的 OpenAI-compatible API：

```text
Model: deepseek-v4.1-flash / gpt-5.6-terra
Temperature: 0
```

模型只根据证据文本返回结构化 JSON：主体、关系、客体、条件、证据有效性、标签、置信度和理由。模型支持结果仍标记为待审核。

## 4. Neo4j 图模型

基础严格层：

```text
(:StrictDocument)-[:STRICT_HAS_EVIDENCE]->(:StrictEvidence)
(:StrictEvidence)-[:STRICT_MENTIONS]->(:StrictEntity)
(:StrictEvidence)-[:STRICT_REPORTS_VALUE]->(:StrictValue)
(:StrictCandidateFact)-[:STRICT_SUPPORTED_BY]->(:StrictEvidence)
(:StrictCandidateFact)-[:STRICT_SUBJECT]->(:StrictEntity)
(:StrictCandidateFact)-[:STRICT_OBJECT]->(:StrictEntity)
```

QA 层：

```text
(:ExpandedEvaluationQuestion)-[:SUPPORTED_BY]->(:StrictEvidence)
```

事实状态：

```text
StrictCandidateFact
  → LLM review
  → VerifiedFact / RejectedFact / QuarantineFact
```

## 5. 评测数据划分

### 5.1 抽取 Gold

从原始文献独立选择文档，由领域专家标注实体、关系、条件、数值和证据。

### 5.2 事实审计集

从最终 KG 分层随机抽样，回查原文，标注：

```text
supported / partial / unsupported / contradicted / ambiguous / not_verifiable
```

### 5.3 QA 测试集

QA 必须绑定 evidence_id 和 evidence_quote；不能仅使用模型答案作为知识事实。

### 5.4 OOD 测试

加入新年份、新子领域、长尾添加剂和新文献类型，测试泛化。

## 6. 质量指标

### 抽取

- Entity Precision/Recall/F1；
- Relation Precision/Recall/F1；
- Relation Direction Accuracy；
- Qualifier F1；
- Value Accuracy；
- Unit Accuracy；
- Evidence Span F1。

### 图谱事实

- Strict Support Rate；
- Relaxed Support Rate；
- Unsupported Claim Rate；
- Contradiction Rate；
- Evidence Coverage；
- Entity Linking Pairwise/B³ F1。

### 下游 QA

- Evidence Recall；
- Recall@k；
- MRR；
- Answer F1；
- Condition Completeness；
- Citation Precision/Recall；
- Unsupported Claim Rate。

## 7. 推荐对照实验

```text
B0: 宽松关键词抽取
B1: 严格规则抽取
B2: LLM 直接抽取
B3: Schema-constrained LLM
Ours: 严格抽取 + LLM 审计 + Evidence
```

下游检索/问答比较：

```text
Direct LLM
BM25 RAG
Vector RAG
Flat Triple RAG
KG-only
KG + Evidence
Ours
```

消融：

- 去除严格过滤；
- 去除实体规范化；
- 去除条件；
- 去除 Evidence；
- 去除 LLM 审计；
- 去除 Quarantine。

## 8. 最终审核规则

只有以下条件同时满足，才能升级为 VerifiedFact：

1. 主体、关系、客体明确；
2. 关系方向正确；
3. 原文证据直接支持；
4. 数值和单位正确；
5. 实验条件绑定正确；
6. 非催化/CVD/CMP/腐蚀等污染；
7. 两名审核者一致或领域专家裁决。

GPT-5.6 生成的 golden 只能称为 model-judged benchmark，不能替代人工 gold。
