#!/usr/bin/env python3
import argparse,csv,json,random
from pathlib import Path

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--reviews',default='strict_extraction/gpt56_reviews.jsonl');ap.add_argument('--relations',default='strict_extraction/relations.jsonl');ap.add_argument('--out',default='golden_benchmark');ap.add_argument('--test-ratio',type=float,default=.2);ap.add_argument('--seed',type=int,default=2025);a=ap.parse_args()
 rs=[json.loads(x) for x in Path(a.reviews).read_text(encoding='utf-8').splitlines() if x.strip()]
 rel={json.loads(x)['fact_id']:json.loads(x) for x in Path(a.relations).read_text(encoding='utf-8').splitlines()}
 rng=random.Random(a.seed); rng.shuffle(rs); n=max(1,round(len(rs)*a.test_ratio)); test=rs[:n]; train=rs[n:]
 out=Path(a.out);out.mkdir(exist_ok=True)
 for name,data in [('gold_test',test),('gold_reference',rs),('train_reference',train)]:
  with (out/f'{name}.jsonl').open('w',encoding='utf-8') as f:
   for r in data:f.write(json.dumps({**r,'gold_source':'gpt-5.6-terra','gold_status':'model_judged_not_human'},ensure_ascii=False)+'\n')
 with (out/'gold_test.csv').open('w',encoding='utf-8',newline='') as f:
  fields=['fact_id','predicate','surface_text','gold_label','domain_relevant','corrected_predicate','evidence_valid','confidence','reason','gold_source','gold_status']
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for r in test:w.writerow({'fact_id':r['fact_id'],'predicate':rel[r['fact_id']]['predicate'],'surface_text':rel[r['fact_id']]['surface_text'],'gold_label':r.get('label'),'domain_relevant':r.get('domain_relevant'),'corrected_predicate':r.get('corrected_predicate'),'evidence_valid':r.get('evidence_valid'),'confidence':r.get('confidence'),'reason':r.get('reason'),'gold_source':'gpt-5.6-terra','gold_status':'model_judged_not_human'})
 print({'total':len(rs),'test':len(test),'reference':len(train),'seed':a.seed})
if __name__=='__main__':main()
