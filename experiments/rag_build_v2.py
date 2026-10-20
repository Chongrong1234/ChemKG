#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rag_build_v2.py — 统一 v2 事实信源并构建 RAG 索引 rag_index_v2。

解决统一方案断点 G1/G2/G3 的构建侧：
  1. 以 strict_extraction_v2（v2 严格层）为唯一证据/实体来源；
  2. 将 jury/consensus.jsonl 的 panel_decision（verified/quarantine/rejected）
     写入 facts.csv 的 panel_decision 列 → 经 rag_system.build 进入索引文本
     （评审状态不再被丢弃）；
  3. 将 strict_extraction_v2/conditions.jsonl 的条件槽聚合为
     condition_text（"concentration=10 ppm; potential=0.547 V"）→ 一并进入
     索引文本（结构化条件首次可用于检索）。

产出：
  kg_v2_unified/            — RAG 兼容目录（6 张 CSV，facts.csv 含增强列）
  rag_index_v2/index.json   — BM25 索引（version=3）

用法：
  python3 rag_build_v2.py
  python3 rag_build_v2.py --kg strict_extraction_v2 --jury jury \
      --stage kg_v2_unified --out rag_index_v2
"""
from __future__ import annotations
import argparse, json, shutil, sys
from collections import defaultdict
from pathlib import Path


def jl(p: Path):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kg", default="strict_extraction_v2")
    ap.add_argument("--jury", default="jury")
    ap.add_argument("--stage", default="kg_v2_unified")
    ap.add_argument("--out", default="rag_index_v2")
    a = ap.parse_args()

    kg = Path(a.kg); jury = Path(a.jury); stage = Path(a.stage)
    stage.mkdir(parents=True, exist_ok=True)

    # 1) 直接复制的五张表（rag_system.build 直接兼容其列结构）
    for name in ("documents.csv", "evidence.csv", "entities.csv", "mentions.csv", "values.csv"):
        src = kg / name
        if not src.exists():
            sys.exit(f"missing {src}")
        shutil.copy(src, stage / name)

    # 2) relations + 共识 + 条件 → 增强 facts.csv
    relations = jl(kg / "relations.jsonl")
    consensus = {c["fact_id"]: c for c in jl(jury / "consensus.jsonl")}
    conditions = jl(kg / "conditions.jsonl")

    cond_by_fact = defaultdict(list)
    for c in conditions:
        # scope 标注条件来自子句还是整行回退，保留在文本中有助于消歧
        scope = c.get("scope") or ""
        txt = f"{c.get('slot','')}={c.get('value','')}{('' + c.get('value2','')) if c.get('value2') else ''} {c.get('unit','')}".strip()
        cond_by_fact[c["fact_id"]].append((txt + f"({scope})" if scope else txt).strip())

    facts = []
    n_status = 0
    for r in relations:
        fid = r["fact_id"]
        dec = consensus.get(fid, {}).get("panel_decision", "")
        if dec and dec != "candidate":
            n_status += 1
        facts.append({
            "fact_id": fid,
            "doc_id": r.get("doc_id", ""),
            "evidence_id": r.get("evidence_id", ""),
            "predicate": r.get("predicate", ""),
            "surface_text": r.get("surface_text", ""),
            "status": r.get("status", "candidate"),
            "panel_decision": dec,
            "consensus_label": consensus.get(fid, {}).get("consensus_label", ""),
            "n_supported": consensus.get(fid, {}).get("n_supported", ""),
            "condition_text": "; ".join(cond_by_fact.get(fid, [])),
        })

    import csv as _csv
    fields = ["fact_id", "doc_id", "evidence_id", "predicate", "surface_text",
              "status", "panel_decision", "consensus_label", "n_supported", "condition_text"]
    with (stage / "facts.csv").open("w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in facts:
            w.writerow(r)

    # 3) 用增强后的目录构建索引（复用 rag_system.build，含 BM25 全部逻辑）
    sys.path.insert(0, ".")
    from rag_system import build as rs_build
    import types
    args = types.SimpleNamespace(kg=str(stage), docs="", out=a.out)
    rs_build(args)

    print(json.dumps({
        "stage_dir": str(stage),
        "facts_total": len(facts),
        "facts_with_panel_decision": n_status,
        "facts_with_conditions": len(cond_by_fact),
        "out_index": a.out,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
