#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retry failed judge calls and merge into the existing judged.jsonl."""
from __future__ import annotations
import json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
sys.path.insert(0, ".")
from rag_judge import call_judge

OUT = Path("evaluation/judged.jsonl")
ANSWERS = Path("evaluation/answers.jsonl")

def main():
    items = {it["id"]: it for it in (json.loads(x) for x in ANSWERS.read_text(encoding="utf-8").splitlines() if x.strip())}
    judged = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]

    jobs = []
    for rec in judged:
        it = items[rec["id"]]
        ev = [e["text"] for e in it.get("retrieved_evidence", [])]
        for sys_name, sc in rec["scores"].items():
            for j, s in sc.items():
                if s is None:
                    jobs.append((rec, sys_name, j, it, ev))
    print(f"retrying {len(jobs)} failed judge calls", flush=True)

    def work(job):
        rec, sys_name, j, it, ev = job
        cand = it["answers"].get(sys_name) or ""
        s = call_judge(it["question"], it["gold_answer"], cand, ev, j)
        return rec["id"], sys_name, j, s

    ok = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for rid, sys_name, j, s in ex.map(work, jobs):
            rec = next(r for r in judged if r["id"] == rid)
            rec["scores"][sys_name][j] = s
            if s is not None:
                ok += 1
    print(f"recovered {ok}/{len(jobs)}", flush=True)

    with open(OUT, "w", encoding="utf-8") as f:
        for r in judged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    main()
