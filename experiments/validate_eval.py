#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate evaluation JSONL structure and provenance against the KG/index."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from rag_system import load_index

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--gold',required=True); ap.add_argument('--index',default='rag_index'); ap.add_argument('--out'); a=ap.parse_args()
    idx=load_index(Path(a.index)); ids={r['evidence_id'] for r in idx['rows']}; errors=[]; count=0; silver=0
    for n,line in enumerate(Path(a.gold).read_text(encoding='utf-8').splitlines(),1):
        if not line.strip(): continue
        count+=1
        try: x=json.loads(line)
        except Exception as e: errors.append({'line':n,'error':f'invalid_json:{e}'}); continue
        for field in ('id','question','gold_evidence_ids'):
            if field not in x: errors.append({'line':n,'error':f'missing:{field}'})
        missing=[e for e in x.get('gold_evidence_ids',[]) if e not in ids]
        if missing: errors.append({'line':n,'error':'evidence_not_in_index','ids':missing})
        if x.get('verification_status','').startswith('silver'): silver+=1
    report={'items':count,'errors':len(errors),'silver_items':silver,'valid':not errors,'errors_detail':errors[:100]}
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if a.out: Path(a.out).write_text(text,encoding='utf-8')
    print(text)
    raise SystemExit(1 if errors else 0)
if __name__=='__main__': main()
