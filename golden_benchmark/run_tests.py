import json,sys
from collections import Counter,defaultdict
from pathlib import Path
p=Path(__file__).parent/'gold_test.jsonl'; rs=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()]
labels=Counter(r['label'] for r in rs)
# score a system output if supplied; otherwise report gold distribution and integrity checks
print('gold_test_size',len(rs));print('label_distribution',dict(labels))
print('missing_fields',sum(not all(r.get(k) is not None for k in ['fact_id','evidence_id','label','surface_text']) for r in rs))
print('unique_fact_ids',len({r['fact_id'] for r in rs}))
print('evidence_bound',sum(bool(r.get('evidence_id')) for r in rs))
print('strict_gold_nonhuman',all(r.get('gold_status')=='model_judged_not_human' for r in rs))
