// Import strict evidence-first extraction into a separate Neo4j namespace.
CREATE CONSTRAINT strict_document_id IF NOT EXISTS FOR (n:StrictDocument) REQUIRE n.doc_id IS UNIQUE;
CREATE CONSTRAINT strict_evidence_id IF NOT EXISTS FOR (n:StrictEvidence) REQUIRE n.evidence_id IS UNIQUE;
CREATE CONSTRAINT strict_entity_id IF NOT EXISTS FOR (n:StrictEntity) REQUIRE n.entity_id IS UNIQUE;
CREATE CONSTRAINT strict_value_id IF NOT EXISTS FOR (n:StrictValue) REQUIRE n.value_id IS UNIQUE;
CREATE CONSTRAINT strict_fact_id IF NOT EXISTS FOR (n:StrictCandidateFact) REQUIRE n.fact_id IS UNIQUE;
LOAD CSV WITH HEADERS FROM 'file:///strict_documents.csv' AS row MERGE (n:StrictDocument {doc_id:row.doc_id}) SET n += row;
LOAD CSV WITH HEADERS FROM 'file:///strict_evidence.csv' AS row MERGE (n:StrictEvidence {evidence_id:row.evidence_id}) SET n += row;
LOAD CSV WITH HEADERS FROM 'file:///strict_entities.csv' AS row MERGE (n:StrictEntity {entity_id:row.entity_id}) SET n += row;
LOAD CSV WITH HEADERS FROM 'file:///strict_values.csv' AS row MERGE (n:StrictValue {value_id:row.value_id}) SET n += row;
LOAD CSV WITH HEADERS FROM 'file:///strict_facts.csv' AS row MERGE (n:StrictCandidateFact {fact_id:row.fact_id}) SET n += row;
LOAD CSV WITH HEADERS FROM 'file:///strict_mentions.csv' AS row MATCH (m:StrictEntity {entity_id:row.entity_id}),(e:StrictEvidence {evidence_id:row.evidence_id}) MERGE (e)-[:STRICT_MENTIONS {mention_id:row.mention_id,text:row.text,line_no:row.line_no}]->(m);
MATCH (d:StrictDocument),(e:StrictEvidence) WHERE d.doc_id=e.doc_id MERGE (d)-[:STRICT_HAS_EVIDENCE]->(e);
MATCH (f:StrictCandidateFact),(e:StrictEvidence) WHERE f.evidence_id=e.evidence_id MERGE (f)-[:STRICT_SUPPORTED_BY]->(e);
MATCH (f:StrictCandidateFact),(d:StrictDocument) WHERE f.doc_id=d.doc_id MERGE (f)-[:STRICT_EXTRACTED_FROM]->(d);
MATCH (v:StrictValue),(e:StrictEvidence) WHERE v.evidence_id=e.evidence_id MERGE (e)-[:STRICT_REPORTS_VALUE]->(v);
MATCH (f:StrictCandidateFact),(s:StrictEntity) WHERE f.subject_id=s.entity_id MERGE (f)-[:STRICT_SUBJECT]->(s);
MATCH (f:StrictCandidateFact),(o:StrictEntity) WHERE f.object_id=o.entity_id MERGE (f)-[:STRICT_OBJECT]->(o);
