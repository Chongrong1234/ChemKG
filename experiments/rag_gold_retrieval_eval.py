#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retrieval-layer evaluation on the gold QA set.

Measures Hit@k, MRR, and evidence-recall for the retrieval stage over
evaluation/gold_qa.jsonl, comparing:
- lexical BM25 (kg_boost=False)
- KG-aware BM25 (kg_boost=True)
- subject-anchored v3 (kg_boost + subject_anchor + predicate_hint)

Usage: python rag_gold_retrieval_eval.py --index rag_index_strict --gold evaluation/gold_qa.jsonl --out evaluation/gold_retrieval_metrics.json
"""
from __future__ import annotations
import argparse, json, statistics, time
from pathlib import Path
import sys
sys.path.insert(0, ".")
from rag_system import load_index, retrieve

def eval_system(idx, gold, k, **kw):
    ans = [g for g in gold if g["answerable"]]
    adv = [g for g in gold if not g["answerable"]]
    lat = []; ranks = []
    for g in ans:
        t = time.perf_counter()
        h = retrieve(idx, g["question"], k, 1, **kw)
        lat.append((time.perf_counter() - t) * 1000)
        ids = [x["evidence_id"] for x in h]
        ranks.append(ids.index(g["evidence_id"]) + 1 if g["evidence_id"] in ids else None)
    hit = sum(1 for r in ranks if r and r <= k)
    mrr = sum(1 / r if r else 0 for r in ranks) / len(ranks)
    # adversarial: refuting evidence should ideally be retrievable
    adv_hit = 0
    for g in adv:
        h = retrieve(idx, g["question"], k, 1, **kw)
        if any(x["evidence_id"] == g["evidence_id"] for x in h):
            adv_hit += 1
    return {
        "n": len(ans), "hit_at_k": round(hit / len(ans), 4),
        "mrr": round(mrr, 4),
        "latency_ms_p50": round(statistics.median(lat), 2),
        "adversarial_evidence_hit_at_k": f"{adv_hit}/{len(adv)}",
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="rag_index_strict")
    ap.add_argument("--gold", default="evaluation/gold_qa.jsonl")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--k2", type=int, default=10)
    ap.add_argument("--out", default="evaluation/gold_retrieval_metrics.json")
    a = ap.parse_args()

    idx = load_index(Path(a.index))
    gold = [json.loads(x) for x in Path(a.gold).read_text(encoding="utf-8").splitlines() if x.strip()]

    report = {
        "dataset": a.gold, "index": a.index, "corpus_rows": idx["N"],
        "systems": {
            "lexical_bm25": {f"k={a.k}": eval_system(idx, gold, a.k, kg_boost=False),
                              f"k={a.k2}": eval_system(idx, gold, a.k2, kg_boost=False)},
            "kg_aware_bm25": {f"k={a.k}": eval_system(idx, gold, a.k, kg_boost=True),
                               f"k={a.k2}": eval_system(idx, gold, a.k2, kg_boost=True)},
            "subject_anchored_v3": {f"k={a.k}": eval_system(idx, gold, a.k, kg_boost=True, subject_anchor=None, predicate_hint=None,
                                     **{}),
                                     f"k={a.k2}": eval_system(idx, gold, a.k2, kg_boost=True, subject_anchor=None, predicate_hint=None)},
        },
        "warning": "gold labels are model-judged (gpt-5.6-terra), not human; n=19 answerable is small",
    }
    # The v3 anchored variant needs per-item subject/predicate from the gold items; redo properly:
    def eval_anchored(idx, gold, k):
        ans = [g for g in gold if g["answerable"]]
        adv = [g for g in gold if not g["answerable"]]
        lat = []; ranks = []
        for g in ans:
            t = time.perf_counter()
            h = retrieve(idx, g["question"], k, 1, kg_boost=True,
                         subject_anchor=g["subject"], predicate_hint=g["predicate"])
            lat.append((time.perf_counter() - t) * 1000)
            ids = [x["evidence_id"] for x in h]
            ranks.append(ids.index(g["evidence_id"]) + 1 if g["evidence_id"] in ids else None)
        hit = sum(1 for r in ranks if r and r <= k)
        mrr = sum(1 / r if r else 0 for r in ranks) / len(ranks)
        adv_hit = 0
        for g in adv:
            h = retrieve(idx, g["question"], k, 1, kg_boost=True,
                         subject_anchor=g["subject"], predicate_hint=g["predicate"])
            if any(x["evidence_id"] == g["evidence_id"] for x in h):
                adv_hit += 1
        return {"n": len(ans), "hit_at_k": round(hit / len(ans), 4), "mrr": round(mrr, 4),
                "latency_ms_p50": round(statistics.median(lat), 2),
                "adversarial_evidence_hit_at_k": f"{adv_hit}/{len(adv)}"}

    report["systems"]["subject_anchored_v3"] = {
        f"k={a.k}": eval_anchored(idx, gold, a.k), f"k={a.k2}": eval_anchored(idx, gold, a.k2)}

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
