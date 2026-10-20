// Copy strict_extraction/llm_reviews.csv to Neo4j import/llm_reviews.csv first.
CREATE CONSTRAINT strict_review_id IF NOT EXISTS FOR (n:StrictLLMReview) REQUIRE n.review_id IS UNIQUE;
LOAD CSV WITH HEADERS FROM 'file:///llm_reviews.csv' AS row
MERGE (r:StrictLLMReview {review_id: row.fact_id + ':deepseek-v4.1-flash'})
SET r += row, r.model='deepseek-v4.1-flash', r.human_adjudication='required';
MATCH (r:StrictLLMReview),(f:StrictCandidateFact {fact_id:r.fact_id})
MERGE (f)-[:HAS_LLM_REVIEW]->(r);
MATCH (r:StrictLLMReview),(e:StrictEvidence {evidence_id:r.evidence_id})
MERGE (r)-[:REVIEWS_EVIDENCE]->(e);
// LLM-supported facts remain provisional until human adjudication.
MATCH (r:StrictLLMReview),(f:StrictCandidateFact {fact_id:r.fact_id})
WHERE r.label='supported'
SET f.llm_status='llm_supported', f.llm_model='deepseek-v4.1-flash', f.human_adjudication='required';
MATCH (r:StrictLLMReview),(f:StrictCandidateFact {fact_id:r.fact_id})
WHERE r.label IN ['unsupported','contradicted']
SET f.llm_status='llm_rejected', f.human_adjudication='required';
MATCH (r:StrictLLMReview),(f:StrictCandidateFact {fact_id:r.fact_id})
WHERE r.label IN ['partial','ambiguous']
SET f.llm_status='llm_quarantine', f.human_adjudication='required';
MATCH (r:StrictLLMReview) RETURN r.label AS label, count(*) AS count ORDER BY label;
