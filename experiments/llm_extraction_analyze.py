#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比实验 C 的分析：LLM 直接抽取 vs 确定性规则管线。

指标：
  - 事实召回：管线抽取的事实（按行）被 LLM 复现的比例（三元组归一化匹配）
  - 命中层次：LLM 三元组匹配管线的 verified / quarantine / rejected / 全新
  - 全新三元组中双模型一致的比例（管线潜在漏抽信号）
  - 空行误抽率：管线无产出的行上 LLM 的抽取密度（幻觉率代理）
"""
import json, sys
from pathlib import Path

recs = [json.loads(x) for x in open(sys.argv[1] if len(sys.argv) > 1 else "evaluation/llm_extraction_baseline.jsonl", encoding="utf-8")]

def norm(s):
    s = (s or "").strip()
    return s if s.isupper() or not any(c.isalpha() for c in s) else s.lower()

models = list(recs[0]["llm"].keys())
print(f"样本 {len(recs)} 行 | 模型 {models}")
print(f"其中有管线事实的行: {sum(1 for r in recs if r['pipeline_facts'])}")

for m in models:
    # 1) 召回：管线事实被 LLM 复现
    total_facts = matched = 0
    for r in recs:
        lt = {(norm(t.get("subject", "")), t.get("predicate", ""), norm(t.get("object", "")))
              for t in (r["llm"][m].get("triples") or [])}
        for f in r["pipeline_facts"]:
            total_facts += 1
            if (norm(f["subject"]), f["predicate"], norm(f["object"])) in lt:
                matched += 1
    # 2) 命中层次与全新
    n_hit_verified = n_hit_quar = n_hit_rej = n_novel = 0
    novel_examples, novel_both = [], 0
    novel_by_model = {}
    for r in recs:
        pf = {(norm(f["subject"]), f["predicate"], norm(f["object"])): f for f in r["pipeline_facts"]}
        tris = r["llm"][m].get("triples") or []
        for t in tris:
            key = (norm(t.get("subject", "")), t.get("predicate", ""), norm(t.get("object", "")))
            if key in pf:
                d = pf[key]["decision"]
                if d == "verified": n_hit_verified += 1
                elif d == "quarantine": n_hit_quar += 1
                else: n_hit_rej += 1
            else:
                n_novel += 1
                novel_by_model[key] = novel_by_model.get(key, 0) + 1
                novel_examples.append((r["text"][:60], t.get("subject"), t.get("predicate"), t.get("object")))
    # 3) 空行误抽
    empty_rows = [r for r in recs if not r["pipeline_facts"]]
    empty_triples = sum(len(r["llm"][m].get("triples") or []) for r in empty_rows)
    empty_rows_with = sum(1 for r in empty_rows if (r["llm"][m].get("triples") or []))
    print(f"\n== {m} ==")
    print(f"  管线事实召回: {matched}/{total_facts} = {matched/total_facts:.4f}")
    print(f"  LLM 三元组命中: verified {n_hit_verified} / quarantine {n_hit_quar} / rejected {n_hit_rej} / 全新 {n_novel}")
    n_all = n_hit_verified + n_hit_quar + n_hit_rej + n_novel
    if n_all: print(f"  全新占比: {n_novel}/{n_all} = {n_novel/n_all:.4f}")
    print(f"  空行误抽: {empty_rows_with}/{len(empty_rows)} 行有产出，共 {empty_triples} 条三元组")
    if empty_rows: print(f"    （空行抽取密度 {empty_triples/len(empty_rows):.2f} 条/行）")

# 4) 双模型在全新三元组上的一致（都抽到同一非管线三元组）
if len(models) == 2:
    a, b = models
    common = common_novel = 0
    for r in recs:
        la = {(norm(t.get("subject", "")), t.get("predicate", ""), norm(t.get("object", "")))
              for t in (r["llm"][a].get("triples") or [])}
        lb = {(norm(t.get("subject", "")), t.get("predicate", ""), norm(t.get("object", "")))
              for t in (r["llm"][b].get("triples") or [])}
        pf = {(norm(f["subject"]), f["predicate"], norm(f["object"])) for f in r["pipeline_facts"]}
        common += len(la & lb - pf)
        common_novel += len((la & lb) - pf)
    print(f"\n双模型全新三元组交集: {common_novel} 条（两模型都抽到、管线没有 → 潜在漏抽信号）")
    print("样例（前 8）:")
    shown = 0
    for r in recs:
        pf = {(norm(f["subject"]), f["predicate"], norm(f["object"])) for f in r["pipeline_facts"]}
        la = {(norm(t.get("subject", "")), t.get("predicate", ""), norm(t.get("object", "")))
              for t in (r["llm"][a].get("triples") or [])}
        lb = {(norm(t.get("subject", "")), t.get("predicate", ""), norm(t.get("object", "")))
              for t in (r["llm"][b].get("triples") or [])}
        for k in (la & lb) - pf:
            print(f"    {k} | {r['text'][:50]}")
            shown += 1
            if shown >= 8: break
        if shown >= 8: break
