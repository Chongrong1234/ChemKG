#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare lexical baseline and KG-aware retrieval on a gold/silver JSONL set."""
from __future__ import annotations
import argparse, json, statistics, time
from pathlib import Path
from rag_system import load_index, retrieve

def run(index, items, k, kg_boost):
    results=[]
    for g in items:
        t=time.perf_counter(); hits=retrieve(index,g["question"],k,1,kg_boost=kg_boost); ms=(time.perf_counter()-t)*1000
        ids={h["evidence_id"] for h in hits}; gold=set(g.get("gold_evidence_ids",[])); recall=len(ids&gold)/len(gold) if gold else None
        results.append({"id":g.get("id"),"recall":recall,"hit":bool(ids&gold) if gold else None,"sufficient":bool(gold and gold<=ids),"latency_ms":ms})
    vals=lambda key:[x[key] for x in results if x[key] is not None]
    return {"n":len(results),"evidence_recall_at_k":sum(vals("recall"))/len(vals("recall")) if vals("recall") else None,"hit_at_k":sum(vals("hit"))/len(vals("hit")) if vals("hit") else None,"sufficient_evidence_rate":sum(vals("sufficient"))/len(vals("sufficient")) if vals("sufficient") else None,"latency_ms_p50":statistics.median(vals("latency_ms")) if vals("latency_ms") else None,"latency_ms_mean":statistics.mean(vals("latency_ms")) if vals("latency_ms") else None}

def slice_run(index, items, k, kg_boost):
    groups={}
    for g in items:
        key=g.get("predicate", "unknown")
        groups.setdefault(key, []).append(g)
    return {key: run(index, group, k, kg_boost) for key, group in sorted(groups.items())}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--index",default="rag_index"); ap.add_argument("--gold",default="evaluation/auto_silver.jsonl"); ap.add_argument("--k",type=int,default=5); ap.add_argument("--out",default="evaluation/comparison.json"); a=ap.parse_args()
    items=[json.loads(x) for x in Path(a.gold).read_text(encoding="utf-8").splitlines() if x.strip()]; idx=load_index(Path(a.index))
    report={"dataset":a.gold,"k":a.k,"systems":{"lexical":run(idx,items,a.k,False),"kg_aware":run(idx,items,a.k,True)},"by_predicate":{"lexical":slice_run(idx,items,a.k,False),"kg_aware":slice_run(idx,items,a.k,True)},"warning":"automatic silver labels; audit before publication"}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True); Path(a.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
