// Run in Neo4j Browser or cypher-shell after copying kg_data/*.csv to Neo4j's import directory.
CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.doc_id IS UNIQUE;
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.entity_id IS UNIQUE;
CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.evidence_id IS UNIQUE;
CREATE CONSTRAINT value_id IF NOT EXISTS FOR (n:Value) REQUIRE n.value_id IS UNIQUE;
CREATE CONSTRAINT candidate_fact_id IF NOT EXISTS FOR (n:CandidateFact) REQUIRE n.fact_id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///documents.csv' AS row
MERGE (n:Document {doc_id: row.doc_id}) SET n += row;
LOAD CSV WITH HEADERS FROM 'file:///entities.csv' AS row
MERGE (n:Entity {entity_id: row.entity_id}) SET n += row;
LOAD CSV WITH HEADERS FROM 'file:///evidence.csv' AS row
MERGE (n:Evidence {evidence_id: row.evidence_id}) SET n += row;
LOAD CSV WITH HEADERS FROM 'file:///values.csv' AS row
MERGE (n:Value {value_id: row.value_id}) SET n += row;
LOAD CSV WITH HEADERS FROM 'file:///facts.csv' AS row
MERGE (n:CandidateFact {fact_id: row.fact_id}) SET n += row;

LOAD CSV WITH HEADERS FROM 'file:///mentions.csv' AS row
MATCH (m:Entity {entity_id: row.entity_id}), (e:Evidence {evidence_id: row.evidence_id})
MERGE (e)-[:MENTIONS {mention_id: row.mention_id, text: row.text, line_no: row.line_no}]->(m);
LOAD CSV WITH HEADERS FROM 'file:///values.csv' AS row
MATCH (v:Value {value_id: row.value_id}), (e:Evidence {evidence_id: row.evidence_id})
MERGE (e)-[:REPORTS_VALUE]->(v);
MATCH (e:Evidence), (d:Document) WHERE e.doc_id = d.doc_id
MERGE (d)-[:HAS_EVIDENCE]->(e);
MATCH (f:CandidateFact), (e:Evidence) WHERE f.evidence_id = e.evidence_id
MERGE (f)-[:SUPPORTED_BY]->(e);
MATCH (f:CandidateFact), (d:Document) WHERE f.doc_id = d.doc_id
MERGE (f)-[:EXTRACTED_FROM]->(d);
