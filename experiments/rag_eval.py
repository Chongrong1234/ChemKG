#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluate retrieval against a small gold JSONL set.

Each line in the gold file may contain:
{"id":"q1","question":"...","gold_evidence_ids":["ev1"],"required_terms":["铜","填充"]}

The evaluator reports evidence recall@k, sufficient-evidence rate, and lexical
required-term coverage. It deliberately does not manufacture answer correctness
without human/reference labels.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from rag_system import load_index, retrieve


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--index",default="rag_index"); ap.add_argument("--gold",required=True); ap.add_argument("--k",type=int,default=5); ap.add_argument("--window",type=int,default=1); ap.add_argument("--out"); a=ap.parse_args()
    rows=[json.loads(x) for x in Path(a.gold).read_text(encoding="utf-8").splitlines() if x.strip()]
    idx=load_index(Path(a.index)); per=[]
    for g in rows:
        hits=retrieve(idx,g["question"],a.k,a.window); ids={h["evidence_id"] for h in hits}; gold=set(g.get("gold_evidence_ids",[]))
        recall=len(ids&gold)/len(gold) if gold else None
        hit=bool(ids&gold) if gold else None
        terms=[x.lower() for x in g.get("required_terms",[])]; text=" ".join(h["text"] for h in hits).lower()
        term_cov=sum(1 for t in terms if t in text)/len(terms) if terms else None
        per.append({"id":g.get("id"),"evidence_recall":recall,"hit_at_k":hit,"sufficient_evidence":bool(gold and gold<=ids),"required_term_coverage":term_cov,"retrieved_ids":[h["evidence_id"] for h in hits]})
    def avg(key, subset=None):
        xs=[r[key] for r in (subset or per) if r[key] is not None]; return sum(xs)/len(xs) if xs else None
    answerable=[(g,r) for g,r in zip(rows,per) if g.get("answerable",True) is not False]
    negatives=[(g,r) for g,r in zip(rows,per) if g.get("answerable",True) is False]
    report={"n":len(per),"k":a.k,"answerable_n":len(answerable),"negative_n":len(negatives),"evidence_recall_at_k":avg("evidence_recall"),"hit_at_k":avg("hit_at_k"),"answerable_evidence_recall_at_k":avg("evidence_recall",[r for _,r in answerable]),"answerable_hit_at_k":avg("hit_at_k",[r for _,r in answerable]),"sufficient_evidence_rate":avg("sufficient_evidence"),"answerable_sufficient_evidence_rate":avg("sufficient_evidence",[r for _,r in answerable]),"required_term_coverage":avg("required_term_coverage"),"negative_hit_rate":sum(bool(r["retrieved_ids"]) for _,r in negatives)/len(negatives) if negatives else None,"per_question":per}
    out=json.dumps(report,ensure_ascii=False,indent=2)
    if a.out: Path(a.out).write_text(out,encoding="utf-8")
    print(out)
if __name__=="__main__": main()
