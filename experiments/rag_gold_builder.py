#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the RAG gold evaluation set from the model-judged golden benchmark.

Source of truth: golden_benchmark/gold_test.jsonl (24 items, labels from
gpt-5.6-terra, gold_status=model_judged_not_human). For each item we craft:

- supported facts  -> answerable QA with expected answer, gold evidence id,
                      required conditions, subject/predicate/object;
- unsupported/contradicted facts -> adversarial probes where the claimed
                      relation is NOT supported by evidence (expected: no /
                      the system should not assert the claim).

Question phrasing uses natural domain questions (NOT template boilerplate) and
is generated deterministically from the fact fields; no clue text is embedded
in the question (the anchored-clue leakage problem of the silver sets is
deliberately avoided).

Output: evaluation/gold_qa.jsonl with schema:
  id, question, answerable, gold_answer, gold_evidence_ids, fact_id,
  predicate, subject, object, conditions, label, gold_status, gold_source
"""
from __future__ import annotations
import json, argparse
from pathlib import Path

REL_ZH = {
    "inhibits_deposition": "抑制沉积",
    "accelerates_deposition": "加速沉积",
    "synergizes_with": "与…协同",
    "improves_filling": "改善填充",
}

def craft_question(pred, subj, obj):
    if pred == "inhibits_deposition":
        return f"{subj}对{obj}有什么作用？它是抑制沉积吗？"
    if pred == "accelerates_deposition":
        return f"{subj}对{obj}有什么作用？它会加速沉积吗？"
    if pred == "synergizes_with":
        return f"{subj}和{obj}之间有什么相互作用？"
    if pred == "improves_filling":
        return f"{subj}对{obj}有什么影响？它能改善填充效果吗？"
    return f"{subj}对{obj}有什么作用？"

def craft_gold_answer(fact, g):
    pred = fact["predicate"]
    subj = g["subject"] or fact.get("subject_hint", "")
    obj = g["object"] or fact.get("object_hint", "")
    conds = [c for c in g.get("conditions", []) if c]
    if pred == "inhibits_deposition":
        base = f"{subj}在相应条件下抑制{obj}。"
    elif pred == "accelerates_deposition":
        base = f"{subj}在相应条件下加速{obj}。"
    elif pred == "synergizes_with":
        base = f"{subj}与{obj}存在协同作用。"
    elif pred == "improves_filling":
        base = f"{subj}在相应条件下改善{obj}。"
    else:
        base = f"{subj}与{obj}存在{REL_ZH.get(pred, pred)}关系。"
    if conds:
        base += "关键条件：" + "；".join(conds[:6]) + "。"
    return base

def craft_unsupported_answer(g):
    reason = (g.get("reason") or "").strip()
    return f"不能支持该说法。{reason}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="golden_benchmark/gold_test.jsonl")
    ap.add_argument("--relations", default="strict_extraction_verify/relations.jsonl")
    ap.add_argument("--entities", default="strict_extraction_verify/entities.jsonl")
    ap.add_argument("--out", default="evaluation/gold_qa.jsonl")
    a = ap.parse_args()

    gold = [json.loads(x) for x in Path(a.gold).read_text(encoding="utf-8").splitlines() if x.strip()]
    rel = {r["fact_id"]: r for r in (json.loads(x) for x in Path(a.relations).read_text(encoding="utf-8").splitlines() if x.strip())}
    ent = {e["entity_id"]: e for e in (json.loads(x) for x in Path(a.entities).read_text(encoding="utf-8").splitlines() if x.strip())}

    out = []
    for g in gold:
        r = rel.get(g["fact_id"])
        if not r:
            continue
        subj_name = ent.get(r["subject_id"], {}).get("name", "")
        obj_name = ent.get(r["object_id"], {}).get("name", "")
        answerable = g["label"] == "supported"
        if answerable:
            q = craft_question(r["predicate"], g["subject"] or subj_name, g["object"] or obj_name)
            ans = craft_gold_answer(r, g)
            gold_ev = [g["evidence_id"]]
        else:
            # adversarial probes: ask the question the claim asserts; gold answer is "not supported"
            q = craft_question(r["predicate"], g["subject"] or subj_name, g["object"] or obj_name)
            ans = craft_unsupported_answer(g)
            gold_ev = [g["evidence_id"]]  # evidence exists but does NOT support the claim
        out.append({
            "id": f"gold_{g['fact_id'][:8]}",
            "question": q,
            "answerable": answerable,
            "gold_answer": ans,
            "gold_evidence_ids": gold_ev,
            "fact_id": g["fact_id"],
            "evidence_id": g["evidence_id"],
            "predicate": r["predicate"],
            "original_predicate": g.get("original_predicate"),
            "subject": g["subject"],
            "object": g["object"],
            "conditions": [c for c in g.get("conditions", []) if c],
            "label": g["label"],
            "gold_status": g.get("gold_status"),
            "gold_source": g.get("gold_source"),
            "surface_text": r.get("surface_text", ""),
        })

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for item in out:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    n_ans = sum(1 for x in out if x["answerable"])
    print(json.dumps({"out": a.out, "total": len(out), "answerable": n_ans,
                      "adversarial": len(out) - n_ans,
                      "gold_status": "model_judged_not_human"}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
