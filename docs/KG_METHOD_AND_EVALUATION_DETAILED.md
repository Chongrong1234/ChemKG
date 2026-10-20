

## 17. 模型增强版本与当前最终推荐图谱

用户要求使用模型提升识别质量后，本项目增加了严格的证据优先抽取层：`kg_pipeline/strict_extract.py`。

### 17.1 模型环境核查

本环境检测到 `transformers`、`torch` 和 `openai` Python 包，但没有可连接的 Ollama 服务、CUDA 环境或已配置的 API 模型服务。虽然工作区其他位置存在 Baichuan 模型文件，但没有在本项目中加载运行，避免因内存和设备条件不足产生不稳定结果。因此，本轮可复现的“增强版本”实际采用了严格结构化规则基线，并预留 OpenAI-compatible LLM 接口环境变量：

```text
KG_LLM_BASE_URL
KG_LLM_MODEL
```

论文中应诚实表述为：当前完成了严格规则/证据过滤增强，LLM 结构化抽取接口已预留但尚未产生本实验的结果。

### 17.2 严格抽取器的改进

相比初始版本，严格版本：

1. 排除 `References/参考文献` 段落；
2. 排除 DOI、URL 和典型引用行；
3. 排除催化、CVD、CMP、光催化、腐蚀等非目标上下文；
4. 要求证据包含电镀、电沉积、填孔、通孔或盲孔领域语境；
5. 将关系判断限制在局部句子/分句；
6. `synergizes_with` 要求至少两个明确化学物/添加剂实体；
7. `improves_filling` 要求同时出现 filling、via、hole 或填充语义；
8. `accelerates_deposition` 和 `inhibits_deposition` 要求存在沉积/电镀语义；
9. 保存主体、客体、关系、证据和数值的独立字段；
10. 所有结果仍标为 `candidate`，不绕过人工审核。

### 17.3 严格抽取结果

严格版本在 48 篇文献上得到：

| 类型 | 数量 |
|---|---:|
| 文档 | 48 |
| 证据片段 | 1,290 |
| 候选实体 | 64 |
| 实体提及 | 3,216 |
| 数值/单位 | 1,295 |
| 候选关系 | 119 |

关系分布：

| 关系 | 数量 |
|---|---:|
| `inhibits_deposition` | 64 |
| `improves_filling` | 26 |
| `accelerates_deposition` | 22 |
| `synergizes_with` | 7 |

对关系证据进行污染关键词检查，`catalys`、`CVD`、`CMP`、`cross-coupling`、`photocatal`、`corrosion`、`reference`、`doi`、`http` 命中数为 0。这个结果只能说明严格规则过滤有效，不能直接当作关系准确率。

### 17.4 Neo4j 中的严格候选层

严格层没有覆盖旧图，而是使用独立标签：

```text
StrictDocument
StrictEvidence
StrictEntity
StrictValue
StrictCandidateFact
```

关系采用 `STRICT_*` 前缀，避免与初始候选图混淆。导入脚本：

- `kg_pipeline/strict_neo4j_import.cypher`

严格层 Neo4j 实际统计：

- StrictDocument：48；
- StrictEvidence：1,290；
- StrictEntity：64；
- StrictValue：1,295；
- StrictCandidateFact：119；
- STRICT_MENTIONS：3,216；
- STRICT_SUPPORTED_BY：119；
- STRICT_SUBJECT：119；
- STRICT_OBJECT：119。

严格层更适合后续人工审核和 LLM 二次确认，并不意味着 119 条关系都已验证。

### 17.5 模型语义审计结果

另有子代理对原始 1,063 条候选事实进行了逐条语义审计，输出：

- `kg_audit/model_reviews.csv`

统计如下：

| 标签 | 数量 |
|---|---:|
| `supported` | 447 |
| `partial` | 17 |
| `unsupported` | 563 |
| `contradicted` | 9 |
| `ambiguous` | 27 |

其中 `domain_relevant=true` 为 557，`false` 为 506。

该审计结果可以用于优先级排序，但仍属于模型辅助审核，不等价于双人专家 gold。已生成：

- `kg_audit/model_verified_candidates.csv`：447 条模型支持候选；
- `kg_audit/model_rejected_candidates.csv`：572 条拒绝候选；
- `kg_audit/model_quarantine.csv`：44 条待裁决候选。

### 17.6 真实 LLM 语义复核结果

在用户提供的 OpenAI-compatible 服务上完成了 API 连通性测试和 119 条严格候选关系的结构化语义复核。调用配置为：

```text
Base URL: http://llmapi.evolventapi.com/v1
Model: deepseek-v4.1-flash
Temperature: 0
```

每条请求要求模型只根据证据文本输出 JSON，包括：

- label；
- domain_relevant；
- corrected_predicate；
- subject/object；
- conditions；
- evidence_valid；
- confidence；
- reason。

LLM 审计结果：

| 标签 | 数量 |
|---|---:|
| `supported` | 77 |
| `partial` | 29 |
| `unsupported` | 11 |
| `contradicted` | 2 |
| 合计 | 119 |

这意味着严格规则层的 119 条候选关系中，模型认为 77 条可以进入“待人工确认的支持候选”，29 条需要隔离复核，13 条应拒绝或标记为关系方向错误。该结果仍然不是人工 gold，也不能直接写成最终 Precision；它是使用真实 LLM 后得到的语义审计结果。

输出文件：

- `strict_extraction/llm_reviews.jsonl`；
- `strict_extraction/llm_reviews.csv`；
- `strict_extraction/llm_verified_candidates.csv`；
- `strict_extraction/llm_rejected_candidates.csv`；
- `strict_extraction/llm_quarantine.csv`。

Neo4j 中新增 `StrictLLMReview` 节点，并将 119 条严格候选关系分别标记为：

```text
llm_supported
llm_rejected
llm_quarantine
```

所有节点仍设置 `human_adjudication='required'`。导入脚本：`kg_pipeline/llm_audit_neo4j.cypher`。

### 17.7 推荐的最终生产流程

正式生产图建议使用严格层作为候选来源：

```text
StrictCandidateFact
        ↓
LLM/领域模型复核
        ↓
双人专家审核
        ↓
VerifiedFact / RejectedFact / QuarantineFact
```

对于每条关系，结构化模型应输出：

```json
{
  "subject": "...",
  "predicate": "...",
  "object": "...",
  "conditions": [],
  "evidence_quote": "...",
  "negation": false,
  "modality": "asserted",
  "confidence": 0.0
}
```

模型不得根据领域常识补写文献中不存在的事实。凡是条件缺失、关系方向不确定、主体/客体不明确或存在否定/假设表达的样本，应进入 `QuarantineFact`。
