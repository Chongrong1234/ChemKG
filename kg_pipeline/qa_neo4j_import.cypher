CREATE CONSTRAINT qa_id IF NOT EXISTS FOR (n:EvaluationQuestion) REQUIRE n.qa_id IS UNIQUE;
LOAD CSV WITH HEADERS FROM 'file:///qa.csv' AS row
MERGE (q:EvaluationQuestion {qa_id:row.qa_id}) SET q += row, q.status='candidate', q.gold_status='model_generated_needs_review';
MATCH (q:EvaluationQuestion),(e:StrictEvidence {evidence_id:q.evidence_id}) MERGE (q)-[:SUPPORTED_BY]->(e);
MATCH (q:EvaluationQuestion),(d:StrictDocument) WHERE q.doc_id=d.doc_id MERGE (q)-[:FROM_DOCUMENT]->(d);
MATCH (q:EvaluationQuestion) RETURN q.category AS category,count(q) AS count ORDER BY category;
MATCH (q:EvaluationQuestion) WHERE NOT (q)-[:SUPPORTED_BY]->(:StrictEvidence) RETURN count(q) AS dangling_qa;
