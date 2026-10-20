#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional sklearn character/word TF-IDF retrieval baseline.

This is a local dependency-light semantic-ish baseline, not a neural embedding.
It is useful for regression until a model-backed embedding service is configured.
"""
from __future__ import annotations
import argparse,json,statistics,time
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from rag_system import load_index

def evaluate(index, items, k):
    rows=index['rows']; corpus=[r['text']+' '+' '.join(r.get('entities',[])) for r in rows]
    vec=TfidfVectorizer(analyzer='char',ngram_range=(2,5),min_df=1,sublinear_tf=True)
    X=vec.fit_transform(corpus); out=[]
    for g in items:
        t=time.perf_counter(); q=vec.transform([g['question']]); scores=linear_kernel(q,X).ravel(); order=scores.argsort()[::-1][:k]; ids={rows[i]['evidence_id'] for i in order}; gold=set(g.get('gold_evidence_ids',[])); out.append({'recall':len(ids&gold)/len(gold) if gold else None,'sufficient':bool(gold and gold<=ids),'ms':(time.perf_counter()-t)*1000})
    valid=lambda key:[x[key] for x in out if x[key] is not None]
    return {'n':len(out),'evidence_recall_at_k':sum(valid('recall'))/len(valid('recall')),'sufficient_evidence_rate':sum(valid('sufficient'))/len(valid('sufficient')),'latency_ms_p50':statistics.median(valid('ms')),'latency_ms_mean':statistics.mean(valid('ms'))}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--index',default='rag_index'); ap.add_argument('--gold',default='evaluation/auto_silver.jsonl'); ap.add_argument('--k',type=int,default=5); ap.add_argument('--out',default='evaluation/dense_proxy_comparison.json'); a=ap.parse_args(); idx=load_index(Path(a.index)); items=[json.loads(x) for x in Path(a.gold).read_text(encoding='utf-8').splitlines() if x.strip()]; result={'system':'char_tfidf_proxy','result':evaluate(idx,items,a.k),'warning':'not a neural embedding; use a fixed embedding model for publication'}; Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
