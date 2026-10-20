#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build provenance-linked silver retrieval sets from the local KG.

Modes:
- default: entity-conditioned questions (harder, closer to user queries)
- --include-clue: controlled questions with a short source excerpt (retrieval regression)
- --include-negative: answerability/abstention probes with no gold evidence
"""
from __future__ import annotations
import argparse, csv, json, random, re
from collections import defaultdict
from pathlib import Path
TEMPLATES={
"inhibits_deposition":["文献中哪些内容被报道为抑制沉积？","关于抑制沉积，知识库记录了什么证据？"],
"accelerates_deposition":["文献中哪些内容被报道为加速沉积？","关于加速沉积，知识库记录了什么证据？"],
"synergizes_with":["哪些文献讨论了添加剂之间的协同作用？","知识库中有哪些添加剂协同作用的证据？"],
"improves_filling":["哪些研究报道了改善填充性能？","关于改善填充，知识库有哪些证据？"]}
NEGATIVES=["知识库中是否证明氟化铵在铝合金电镀中改善了填充？","知识库中是否有钯纳米线在锂电池中的沉积数据？","是否报道了氮化硼在硅通孔中的铜扩散阻挡性能？","有没有证据表明葡萄糖在镍电镀中提高了孔隙率？"]
def read(path):
 with Path(path).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--kg',default='kg_data');ap.add_argument('--out',default='evaluation/auto_entity_silver.jsonl');ap.add_argument('--per-predicate',type=int,default=100);ap.add_argument('--seed',type=int,default=42);ap.add_argument('--include-clue',action='store_true');ap.add_argument('--include-negative',action='store_true');a=ap.parse_args()
 root=Path(a.kg);facts=read(root/'facts.csv');evid={r['evidence_id']:r for r in read(root/'evidence.csv')};docs={r['doc_id']:r for r in read(root/'documents.csv')};mentions=read(root/'mentions.csv');entities={r['entity_id']:r for r in read(root/'entities.csv')};ev_ent=defaultdict(list)
 for m in mentions:
  ent=entities.get(m.get('entity_id'),{});n=m.get('text') or ent.get('name','');generic={'deposition','electroplating','filling','填充','电镀','沉积','process','method','property','copper','cobalt','铜','钴'}
  etype=ent.get('entity_type') or ent.get('type')
  if n and n.lower() not in generic and etype in {'Chemical','Additive'} and n not in ev_ent[m.get('evidence_id')]:ev_ent[m.get('evidence_id')].append(n)
 by=defaultdict(list)
 for f in facts:
  if f.get('predicate') in TEMPLATES and f.get('evidence_id') in evid:by[f['predicate']].append(f)
 pred_by_ev=defaultdict(set)
 for f in facts:
  if f.get('predicate') in TEMPLATES:pred_by_ev[f.get('evidence_id')].add(f.get('predicate'))
 def multi_gold(entity,pred):
  if not entity:return []
  ent_l=entity.lower()
  return sorted(ev for ev,el in ev_ent.items() if any(x.lower()==ent_l for x in el) and pred in pred_by_ev.get(ev,set()))
 random.seed(a.seed);out=[]
 for pred,fs in sorted(by.items()):
  random.shuffle(fs)
  kept=0
  for f in fs:
   if kept>=a.per_predicate:break
   e=evid[f['evidence_id']];ents=ev_ent.get(f['evidence_id'],[])
   # Un-anchored template questions are ill-posed (hundreds of equally valid golds);
   # the hard set keeps only facts with a Chemical/Additive anchor. Clue mode keeps all.
   if not a.include_clue and not ents:continue
   kept+=1
   q=random.choice(TEMPLATES[pred]);
   if ents:q=f'{ents[0]}：{q}'
   if a.include_clue:
    clue=re.sub(r'<[^>]+>','',e.get('text',''));clue=re.sub(r'\s+',' ',clue).strip()[:80];q+=f' 证据线索：{clue}'
   gold=[f.get('evidence_id')] if a.include_clue else (multi_gold(ents[0],pred) if ents else [f.get('evidence_id')])
   out.append({'id':f'silver_{len(out):05d}','question':q,'answerable':True,'question_type':'relation_evidence','predicate':pred,'reference_answer':f.get('surface_text','')[:1000],'required_facts':[{'fact_id':f.get('fact_id'),'predicate':pred,'importance':'required'}],'gold_evidence_ids':gold,'required_terms':ents[:4],'source_doc_id':f.get('doc_id'),'source_title':docs.get(f.get('doc_id'),{}).get('title',''),'source':'auto_from_candidate_fact','verification_status':'silver_unreviewed','anchored':a.include_clue})
 if a.include_negative:
  for q in NEGATIVES:out.append({'id':f'negative_{len(out):05d}','question':q,'answerable':False,'question_type':'no_answer','gold_evidence_ids':[],'required_facts':[],'source':'handwritten_negative_probe','verification_status':'silver_unreviewed','anchored':False})
 p=Path(a.out);p.parent.mkdir(parents=True,exist_ok=True);p.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in out)+'\n',encoding='utf-8');print(json.dumps({'items':len(out),'anchored':a.include_clue,'negative':a.include_negative,'out':str(p),'warning':'silver; audit before publication'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
