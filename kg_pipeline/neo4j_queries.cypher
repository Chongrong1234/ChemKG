// Useful verification queries after import.
MATCH (n) RETURN labels(n) AS labels, count(n) AS count ORDER BY labels;
MATCH ()-[r]->() RETURN type(r) AS relationship, count(r) AS count ORDER BY relationship;
MATCH (f:CandidateFact) WHERE NOT (f)-[:SUPPORTED_BY]->(:Evidence) RETURN f.fact_id LIMIT 100;
MATCH (e:Evidence) OPTIONAL MATCH (e)-[:HAS_EVIDENCE]-(d:Document) WHERE d IS NULL RETURN e.evidence_id LIMIT 100;
MATCH (n:Entity) WHERE NOT ()-[:MENTIONS]->(n) RETURN n.entity_id, n.name LIMIT 100;
MATCH (v:Value) WHERE NOT ()-[:REPORTS_VALUE]->(v) RETURN v.value_id LIMIT 100;
MATCH (r:Review) RETURN r.label, count(*) AS count ORDER BY r.label;
MATCH (v:TriageSupportedFact) WHERE v.human_adjudication <> 'required' RETURN v.fact_id;
MATCH (v:TriageSupportedFact)-[:DERIVED_FROM]->(c)<-[:DERIVED_FROM]-(r:RejectedFact) RETURN v.fact_id, r.fact_id;
