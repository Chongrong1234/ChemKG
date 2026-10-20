#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregate LLM-as-judge scores into the final gold evaluation metrics.

Reads evaluation/judged.jsonl (per-item per-system per-judge scores) and produces:
- per-system mean scores (correctness, evidence_support, condition_retention) on answerable items;
- abstention accuracy on adversarial items;
- inter-judge agreement (Cohen's-style pairwise on correctness bins);
- a system ranking table.

Usage: python rag_judge_aggregate.py --judged evaluation/judged.jsonl --out evaluation/gold_answer_metrics.json
"""
from __future__ import annotations
import argparse, json, itertools, statistics
from pathlib import Path

def valid_score(s, key):
    if not isinstance(s, dict):
        return None
    v = s.get(key)
    return v if isinstance(v, (int, float)) else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judged", default="evaluation/judged.jsonl")
    ap.add_argument("--out", default="evaluation/gold_answer_metrics.json")
    a = ap.parse_args()

    items = [json.loads(x) for x in Path(a.judged).read_text(encoding="utf-8").splitlines() if x.strip()]
    judges = sorted({j for it in items for sc in it["scores"].values() for j in sc})
    systems = sorted({s for it in items for s in it["scores"]})

    answerable = [it for it in items if it["answerable"]]
    adversarial = [it for it in items if not it["answerable"]]

    report = {"n_items": len(items), "n_answerable": len(answerable),
              "n_adversarial": len(adversarial), "judges": judges, "systems": {},
              "judge_agreement": {}, "per_predicate": {}}

    for sys_name in systems:
        # answerable metrics averaged over judges
        agg = {"correctness": [], "evidence_support": [], "condition_retention": []}
        for it in answerable:
            for j in judges:
                sc = it["scores"].get(sys_name, {}).get(j)
                for k in agg:
                    v = valid_score(sc, k)
                    if v is not None:
                        agg[k].append(v)
        # abstention accuracy on adversarial
        abst = []
        for it in adversarial:
            for j in judges:
                sc = it["scores"].get(sys_name, {}).get(j)
                v = valid_score(sc, "abstention")
                if v is not None:
                    abst.append(v)
        report["systems"][sys_name] = {
            "n_answerable_scores": len(agg["correctness"]),
            "correctness": round(statistics.mean(agg["correctness"]) / 2, 4) if agg["correctness"] else None,
            "evidence_support": round(statistics.mean(agg["evidence_support"]) / 2, 4) if agg["evidence_support"] else None,
            "condition_retention": round(statistics.mean(agg["condition_retention"]) / 2, 4) if agg["condition_retention"] else None,
            "adversarial_abstention": round(statistics.mean(abst), 4) if abst else None,
            "n_adversarial_scores": len(abst),
        }

    # inter-judge agreement on correctness (answerable, all systems pooled)
    for j1, j2 in itertools.combinations(judges, 2):
        pairs = []
        for it in answerable:
            for sys_name in systems:
                s1 = valid_score(it["scores"].get(sys_name, {}).get(j1), "correctness")
                s2 = valid_score(it["scores"].get(sys_name, {}).get(j2), "correctness")
                if s1 is not None and s2 is not None:
                    pairs.append((s1, s2))
        if pairs:
            exact = sum(1 for x, y in pairs if x == y) / len(pairs)
            within1 = sum(1 for x, y in pairs if abs(x - y) <= 1) / len(pairs)
            report["judge_agreement"][f"{j1}|{j2}"] = {"exact": round(exact, 4), "within_1": round(within1, 4), "n": len(pairs)}

    # per-predicate correctness for the best system
    for sys_name in systems:
        per_pred = {}
        for pred in {it["predicate"] for it in answerable}:
            xs = []
            for it in answerable:
                if it["predicate"] != pred:
                    continue
                for j in judges:
                    v = valid_score(it["scores"].get(sys_name, {}).get(j), "correctness")
                    if v is not None:
                        xs.append(v)
            if xs:
                per_pred[pred] = round(statistics.mean(xs) / 2, 4)
        report["per_predicate"][sys_name] = per_pred

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
