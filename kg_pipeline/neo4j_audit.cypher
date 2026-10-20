// Run after neo4j_schema.cypher and copying kg_audit CSVs into Neo4j import/.
CREATE CONSTRAINT review_id IF NOT EXISTS FOR (n:Review) REQUIRE n.review_id IS UNIQUE;
CREATE CONSTRAINT triage_verified_id IF NOT EXISTS FOR (n:TriageSupportedFact) REQUIRE n.fact_id IS UNIQUE;
CREATE CONSTRAINT rejected_id IF NOT EXISTS FOR (n:RejectedFact) REQUIRE n.fact_id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///fact_reviews.csv' AS row
MERGE (r:Review {review_id: row.fact_id + ':' + row.audit_method})
SET r += row, r.label = row.review_label;
MATCH (r:Review), (f:CandidateFact {fact_id:r.fact_id})
MERGE (f)-[:HAS_REVIEW]->(r);

LOAD CSV WITH HEADERS FROM 'file:///verified_candidates.csv' AS row
MERGE (v:TriageSupportedFact {fact_id:row.fact_id})
SET v += row, v.verification_status='triage_supported', v.human_adjudication='required';
MATCH (v:TriageSupportedFact), (f:CandidateFact {fact_id:v.fact_id})
MERGE (v)-[:DERIVED_FROM]->(f);
MATCH (v:TriageSupportedFact), (e:Evidence), (f:CandidateFact {fact_id:v.fact_id})
WHERE f.evidence_id=e.evidence_id MERGE (v)-[:SUPPORTED_BY]->(e);

LOAD CSV WITH HEADERS FROM 'file:///rejected_candidates.csv' AS row
MERGE (r:RejectedFact {fact_id:row.fact_id})
SET r += row, r.rejected_reason=row.review_notes;
MATCH (r:RejectedFact), (f:CandidateFact {fact_id:r.fact_id})
MERGE (r)-[:DERIVED_FROM]->(f);

LOAD CSV WITH HEADERS FROM 'file:///quarantine.csv' AS row
MERGE (q:QuarantineFact {fact_id:row.fact_id})
SET q += row, q.review_status='needs_human_adjudication';
MATCH (q:QuarantineFact), (f:CandidateFact {fact_id:q.fact_id})
MERGE (q)-[:DERIVED_FROM]->(f);

// Basic audit checks
MATCH (n) RETURN labels(n) AS labels, count(n) AS count ORDER BY labels;
MATCH (f:CandidateFact) WHERE NOT (f)-[:SUPPORTED_BY]->(:Evidence) RETURN count(f) AS dangling_facts;
MATCH (f:CandidateFact)-[:HAS_REVIEW]->(r:Review) RETURN r.label AS label, count(*) AS count ORDER BY label;
MATCH (v:TriageSupportedFact) WHERE v.human_adjudication <> 'required' RETURN v.fact_id;
MATCH (v:TriageSupportedFact)-[:DERIVED_FROM]->(c)<-[:DERIVED_FROM]-(r:RejectedFact) RETURN v.fact_id, r.fact_id;
