// strict_neo4j_import_v2.cypher — v2 严格证据层 + 评审团层导入 Neo4j
// 前置：把 strict_extraction_v2/*.csv 与 jury/consensus.csv 复制到 /var/lib/neo4j/import/
// 执行：cypher-shell -u neo4j -p <pwd> -f strict_neo4j_import_v2.cypher
// CSV 生成见 kg_pipeline/export_v2_csv.py

// ---------- 0. 清理旧层（幂等） ----------
MATCH (n) WHERE n.`_v2` = true DETACH DELETE n;

// ---------- 1. 约束 ----------
CREATE CONSTRAINT v2_doc IF NOT EXISTS FOR (d:StrictDocumentV2) REQUIRE d.doc_id IS UNIQUE;
CREATE CONSTRAINT v2_ev  IF NOT EXISTS FOR (e:StrictEvidenceV2) REQUIRE e.evidence_id IS UNIQUE;
CREATE CONSTRAINT v2_ent IF NOT EXISTS FOR (e:StrictEntityV2) REQUIRE e.entity_id IS UNIQUE;
CREATE CONSTRAINT v2_val IF NOT EXISTS FOR (v:StrictValueV2) REQUIRE v.value_id IS UNIQUE;
CREATE CONSTRAINT v2_fact IF NOT EXISTS FOR (f:StrictCandidateFactV2) REQUIRE f.fact_id IS UNIQUE;
CREATE CONSTRAINT v2_cond IF NOT EXISTS FOR (c:StrictConditionV2) REQUIRE c.cond_id IS UNIQUE;
CREATE CONSTRAINT v2_rev  IF NOT EXISTS FOR (r:StrictPanelReviewV2) REQUIRE r.fact_id IS UNIQUE;

// ---------- 2. 文档 / 证据 / 实体 / 数值 ----------
LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/documents.csv' AS row
MERGE (d:StrictDocumentV2 {doc_id: row.doc_id})
  SET d.`_v2` = true, d.path = row.path, d.title = row.title;

LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/evidence.csv' AS row
MERGE (e:StrictEvidenceV2 {evidence_id: row.evidence_id})
  SET e.`_v2` = true, e.doc_id = row.doc_id, e.line_no = toInteger(row.line_no), e.text = row.text;

LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/entities.csv' AS row
MERGE (n:StrictEntityV2 {entity_id: row.entity_id})
  SET n.`_v2` = true, n.name = row.name, n.type = row.type,
      n.normalized_name = row.normalized_name, n.status = row.status;

LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/values.csv' AS row
MERGE (v:StrictValueV2 {value_id: row.value_id})
  SET v.`_v2` = true, v.evidence_id = row.evidence_id, v.doc_id = row.doc_id,
      v.value = row.value, v.unit = row.unit, v.slot = row.slot, v.raw_text = row.raw_text;

// 实体提及
LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/mentions.csv' AS row
MATCH (e:StrictEvidenceV2 {evidence_id: row.evidence_id})
MATCH (n:StrictEntityV2 {entity_id: row.entity_id})
MERGE (e)-[m:STRICT_MENTIONS_V2 {mention_id: row.mention_id}]->(n)
  SET m.`_v2` = true, m.text = row.text, m.line_no = toInteger(row.line_no);

// 证据-文档、数值-证据
LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/evidence.csv' AS row
MATCH (d:StrictDocumentV2 {doc_id: row.doc_id})
MATCH (e:StrictEvidenceV2 {evidence_id: row.evidence_id})
MERGE (d)-[r:STRICT_HAS_EVIDENCE_V2]->(e) SET r.`_v2` = true;

LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/values.csv' AS row
MATCH (e:StrictEvidenceV2 {evidence_id: row.evidence_id})
MATCH (v:StrictValueV2 {value_id: row.value_id})
MERGE (e)-[r:STRICT_REPORTS_VALUE_V2]->(v) SET r.`_v2` = true;

// ---------- 3. 候选事实 + 主体/客体/证据/条件 ----------
LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/relations.csv' AS row
MERGE (f:StrictCandidateFactV2 {fact_id: row.fact_id})
  SET f.`_v2` = true, f.predicate = row.predicate, f.doc_id = row.doc_id,
      f.evidence_id = row.evidence_id, f.line_no = toInteger(row.line_no),
      f.status = row.status, f.extractor = 'strict_v2';

LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/relations.csv' AS row
MATCH (f:StrictCandidateFactV2 {fact_id: row.fact_id})
MATCH (e:StrictEvidenceV2 {evidence_id: row.evidence_id})
MERGE (f)-[r:STRICT_SUPPORTED_BY_V2]->(e) SET r.`_v2` = true;

// 条件节点 + UNDER_CONDITION 边（条件感知事实表示，论文核心创新落图）
LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/conditions.csv' AS row
MERGE (c:StrictConditionV2 {cond_id: row.cond_id})
  SET c.`_v2` = true, c.fact_id = row.fact_id, c.slot = row.slot, c.value = row.value,
      c.unit = row.unit, c.raw = row.raw, c.scope = row.scope, c.evidence_id = row.evidence_id;

LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/conditions.csv' AS row
MATCH (f:StrictCandidateFactV2 {fact_id: row.fact_id})
MATCH (c:StrictConditionV2 {cond_id: row.cond_id})
MERGE (f)-[r:UNDER_CONDITION_V2]->(c) SET r.`_v2` = true;

// 事实三元组边
LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/relations.csv' AS row
MATCH (f:StrictCandidateFactV2 {fact_id: row.fact_id})
MATCH (s:StrictEntityV2 {entity_id: row.subject_id})
MERGE (f)-[r:STRICT_SUBJECT_V2]->(s) SET r.`_v2` = true;

LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/relations.csv' AS row
MATCH (f:StrictCandidateFactV2 {fact_id: row.fact_id})
MATCH (o:StrictEntityV2 {entity_id: row.object_id})
MERGE (f)-[r:STRICT_OBJECT_V2]->(o) SET r.`_v2` = true;

// ---------- 4. 评审团共识层 ----------
LOAD CSV WITH HEADERS FROM 'file:///jury/consensus.csv' AS row
MERGE (rv:StrictPanelReviewV2 {fact_id: row.fact_id})
  SET rv.`_v2` = true,
      rv.per_model_labels = split(row.per_model_labels, '|'),
      rv.n_supported = toInteger(row.n_supported),
      rv.panel_decision = row.panel_decision,
      rv.consensus_label = row.consensus_label,
      rv.fleiss_kappa = toFloat(row.fleiss_kappa),
      rv.gold_status = 'llm_panel_consensus_needs_human_signoff';

LOAD CSV WITH HEADERS FROM 'file:///jury/consensus.csv' AS row
MATCH (f:StrictCandidateFactV2 {fact_id: row.fact_id})
MATCH (rv:StrictPanelReviewV2 {fact_id: row.fact_id})
MERGE (f)-[r:PANEL_REVIEWED_BY_V2]->(rv) SET r.`_v2` = true;

// 事实状态升级（verified / quarantine / rejected 标签叠加，不覆盖候选层）
LOAD CSV WITH HEADERS FROM 'file:///jury/consensus.csv' AS row
WITH row WHERE row.panel_decision STARTS WITH 'verified'
MATCH (f:StrictCandidateFactV2 {fact_id: row.fact_id})
SET f:VerifiedFactV2, f.panel_status = row.panel_decision;

LOAD CSV WITH HEADERS FROM 'file:///jury/consensus.csv' AS row
WITH row WHERE row.panel_decision = 'quarantine'
MATCH (f:StrictCandidateFactV2 {fact_id: row.fact_id})
SET f:QuarantineFactV2, f.panel_status = row.panel_decision;

LOAD CSV WITH HEADERS FROM 'file:///jury/consensus.csv' AS row
WITH row WHERE row.panel_decision = 'rejected'
MATCH (f:StrictCandidateFactV2 {fact_id: row.fact_id})
SET f:RejectedFactV2, f.panel_status = row.panel_decision;

// ---------- 5. PubChem 链接 ----------
LOAD CSV WITH HEADERS FROM 'file:///strict_extraction_v2/pubchem_links.csv' AS row
WITH row WHERE row.status = 'linked'
MATCH (n:StrictEntityV2 {entity_id: row.entity_id})
SET n.pubchem_cid = toInteger(row.cid), n.pubchem_smiles = row.smiles,
    n.pubchem_inchikey = row.inchikey, n.pubchem_formula = row.formula,
    n.pubchem_matched_term = row.matched_term;

// ---------- 6. 验证查询 ----------
// 6.1 各层计数
MATCH (d:StrictDocumentV2) WITH count(d) AS docs
MATCH (e:StrictEvidenceV2) WITH docs, count(e) AS evs
MATCH (n:StrictEntityV2) WITH docs, evs, count(n) AS ents
MATCH (v:StrictValueV2) WITH docs, evs, ents, count(v) AS vals
MATCH (f:StrictCandidateFactV2) WITH docs, evs, ents, vals, count(f) AS facts
MATCH (c:StrictConditionV2) WITH docs, evs, ents, vals, facts, count(c) AS conds
MATCH (rv:StrictPanelReviewV2)
RETURN docs, evs, ents, vals, facts, conds, count(rv) AS panel_reviews;

// 6.2 条件覆盖
MATCH (f:StrictCandidateFactV2)
OPTIONAL MATCH (f)-[:UNDER_CONDITION_V2]->(c:StrictConditionV2)
RETURN f.predicate,
       count(DISTINCT f) AS total,
       count(DISTINCT c) AS conditions,
       round(100.0 * count(DISTINCT c) / count(DISTINCT f), 1) AS coverage_pct
ORDER BY total DESC;

// 6.3 悬空检查（必须全 0）
MATCH (f:StrictCandidateFactV2) WHERE NOT (f)-[:STRICT_SUBJECT_V2]->() OR NOT (f)-[:STRICT_OBJECT_V2]->() OR NOT (f)-[:STRICT_SUPPORTED_BY_V2]->()
RETURN count(f) AS dangling_facts;

// 6.4 评审团裁决分布
MATCH (f:StrictCandidateFactV2)
RETURN f.panel_status AS decision, count(f) AS n ORDER BY n DESC;

// 6.5 条件感知样例查询：给出带完整条件的已验证填充事实
MATCH (f:VerifiedFactV2)-[:STRICT_SUBJECT_V2]->(s:StrictEntityV2)
MATCH (f)-[:STRICT_OBJECT_V2]->(o:StrictEntityV2)
OPTIONAL MATCH (f)-[:UNDER_CONDITION_V2]->(c:StrictConditionV2)
RETURN s.name AS additive, f.predicate AS predicate, o.name AS object,
       collect(DISTINCT c.slot + '=' + c.value + ' ' + c.unit) AS conditions
LIMIT 25;
