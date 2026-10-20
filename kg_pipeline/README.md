# Electroplating KG pipeline

本目录提供一个“证据优先、候选事实与已验证事实分离”的 KG 初始管线，面向当前目录中的铜/钴电沉积、电镀添加剂、PCB 通孔/盲孔填充文献。

## 严格抽取基线

`strict_extract.py` 是比 `build_kg.py` 更严格的 JSONL 抽取器：

```bash
python kg_pipeline/strict_extract.py --input 文献提取 --out strict_extraction
```

输出 `documents.jsonl`、`evidence.jsonl`、`entities.jsonl`、`mentions.jsonl`、`values.jsonl`、`relations.jsonl` 和 `summary.json`。它默认不依赖外部模型/API，执行 References/参考文献、DOI、URL 排除，电镀/电沉积上下文门控，催化/CVD/CMP/腐蚀污染过滤，分句级主客体绑定，协同关系双实体约束，以及数值单位规范化。结果全部仍标为 candidate，必须人工审核。

若配置 OpenAI-compatible 服务，可通过 `KG_LLM_BASE_URL` 和 `KG_LLM_MODEL` 扩展结构化 LLM 抽取；当前环境未检测到本地模型权重、Ollama 服务或 API 环境，因此实际统计来自严格规则基线。

## 当前实现

`build_kg.py` 会：

1. 递归读取输入目录中的 `full.md`；
2. 用保守领域关键词筛选相关文献；
3. 建立 `Document`、`Evidence`、`Entity`、`Mention`、`Value`、`CandidateFact` 数据表；
4. 为每个候选事实保留文档、行号和证据文本；
5. 只把关系线索标成 `candidate`，绝不自动声称 `verified`；
6. 可通过 Neo4j Bolt 连接创建约束并导入文档、实体、证据和候选事实。

## 运行

```bash
python kg_pipeline/build_kg.py --input 文献提取 --out kg_data
```

导出的 CSV 可供人工审核。Neo4j 导入要求 Neo4j 能够访问 `kg_data` 目录中的 CSV；生产环境建议把 CSV 放进 Neo4j `import/` 目录，然后执行 `neo4j_schema.cypher`。也可以安装 `requirements.txt` 后使用 Python driver 的参数化批量写入。

```bash
python kg_pipeline/build_kg.py \
  --input 文献提取 \
  --out kg_data \
  --neo4j-uri bolt://localhost:7687 \
  --neo4j-user neo4j \
  --neo4j-password '<PASSWORD>'
```

## 人工检查重点

当前自动结果仅为候选层，以下内容必须人工或领域规则复核：

- 实体规范化：缩写、同义词、同名异物；
- 添加剂角色：accelerator / suppressor / leveler / inhibitor；
- 关系方向与关系粒度；
- 数值、单位、浓度和换算；
- 温度、电流密度、pH、时间、孔径/孔深等实验条件；
- 否定、假设、可能性和比较句；
- 表格、图片及跨句关系；
- 文献之间的冲突结果；
- CandidateFact 是否升级为 VerifiedFact。

## 推荐的 Neo4j 图模型

```text
(:Document)-[:HAS_EVIDENCE]->(:Evidence)
(:Evidence)-[:MENTIONS]->(:Entity)
(:Evidence)-[:REPORTS_VALUE]->(:Value)
(:CandidateFact)-[:SUPPORTED_BY]->(:Evidence)
(:CandidateFact)-[:EXTRACTED_FROM]->(:Document)
```

验证后的事实应单独使用 `:VerifiedFact` 标签或 `status='verified'`，不要覆盖候选记录。QA 数据应放在 `:EvaluationQuestion`、`:GoldAnswer`、`:EvaluationEvidence` 层，不能因为答案是 gold 就直接写成领域事实。

## 初步质量评测

建议从 `CandidateFact` 中分层抽样，并建立 `manual_review.csv`：

- 随机事实：估计整体原文支持率；
- 每种关系类型：至少 30 条；
- 数值/单位/条件事实；
- 长尾添加剂和新文献；
- 否定、比较、跨句和表格事实；
- 独立文献 gold 子集：测 Entity/Relation/Qualifier P/R/F1；
- QASPER/SciQ/MMLU 等外部数据：优先作为 Evaluation 层，不直接并入 Verified KG。
