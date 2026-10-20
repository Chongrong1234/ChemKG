#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gold_unified_eval.py — 统一 gold 检索层评测（两代真值 × 三种策略）。

对统一后的两代 gold 评测集执行同构评测协议：

  组合 A: gold_qa_v1.jsonl (24 事实/23 题, gpt-5.6 判定) × rag_index_strict (N=1,290)
  组合 B: gold_qa_v2.jsonl (44 事实/34 题, 五模型评审团共识) × rag_index_v2 (N=1,411)

  策略: lexical BM25 / KG-aware BM25 / subject-anchored v3

指标（多 gold 语义：命中任一 gold_evidence_ids 即命中）：
  factual    Hit@k / MRR@k / P50 延迟（主指标）
  partial    同上单列（证据部分支持，检索语义同 factual）
  adversarial 反驳证据命中率（证据存在但不支持声称的关系，理想可检索）
  ambiguous  不计入（证据表述含糊）

输出：evaluation/unified_gold_metrics.json

用法：
  python3 gold_unified_eval.py
  python3 gold_unified_eval.py --k 5 --k2 10
"""
from __future__ import annotations
import argparse, json, statistics, sys, time
from pathlib import Path

sys.path.insert(0, ".")
from rag_system import load_index, retrieve

COMBOS = [
    {"name": "v1_gpt56", "index": "rag_index_strict", "gold": "evaluation/gold_qa_v1.jsonl",
     "desc": "v1 gold (gpt-5.6 model-judged) × strict-v1 index"},
    {"name": "v2_panel", "index": "rag_index_v2", "gold": "evaluation/gold_qa_v2.jsonl",
     "desc": "v2 gold (five-model panel consensus) × unified-v2 index (panel status + conditions)"},
]


def eval_strategy(idx, items, k, **kw):
    """items: 聚合后的 gold 条目。返回分层指标。"""
    by_type = {"factual": [], "partial": [], "adversarial": []}
    for g in items:
        t = g["question_type"]
        if t in by_type:
            by_type[t].append(g)
    out = {}
    for t, group in by_type.items():
        lat, ranks, adv_hit = [], [], 0
        for g in group:
            t0 = time.perf_counter()
            hits = retrieve(idx, g["question"], k, 1, **kw)
            lat.append((time.perf_counter() - t0) * 1000)
            ids = [h["evidence_id"] for h in hits]
            gold = set(g["gold_evidence_ids"])
            # 多 gold：取最靠前的 gold 命中排名
            rank = next((i + 1 for i, eid in enumerate(ids) if eid in gold), None)
            ranks.append(rank)
            if t == "adversarial" and any(eid in gold for eid in ids):
                adv_hit += 1
        if not group:
            out[t] = {"n": 0}
            continue
        if t == "adversarial":
            out[t] = {"n": len(group), "refuting_evidence_hit_at_k": f"{adv_hit}/{len(group)}",
                      "refuting_hit_rate": round(adv_hit / len(group), 4),
                      "latency_ms_p50": round(statistics.median(lat), 2)}
        else:
            hit = sum(1 for r in ranks if r and r <= k)
            mrr = sum(1 / r if r else 0 for r in ranks) / len(ranks)
            out[t] = {"n": len(group), "hit_at_k": round(hit / len(group), 4),
                      "mrr": round(mrr, 4), "latency_ms_p50": round(statistics.median(lat), 2)}
    return out


def eval_anchored(idx, items, k, panel_mode="off"):
    """subject-anchored v3（可选 jury 状态软加权：trust/refute/off）"""
    by_type = {"factual": [], "partial": [], "adversarial": []}
    for g in items:
        if g["question_type"] in by_type:
            by_type[g["question_type"]].append(g)
    out = {}
    for t, group in by_type.items():
        lat, ranks, adv_hit = [], [], 0
        for g in group:
            t0 = time.perf_counter()
            hits = retrieve(idx, g["question"], k, 1, kg_boost=True,
                            subject_anchor=g["subject"], predicate_hint=g["predicate"],
                            panel_mode=panel_mode)
            lat.append((time.perf_counter() - t0) * 1000)
            ids = [h["evidence_id"] for h in hits]
            gold = set(g["gold_evidence_ids"])
            rank = next((i + 1 for i, eid in enumerate(ids) if eid in gold), None)
            ranks.append(rank)
            if t == "adversarial" and any(eid in gold for eid in ids):
                adv_hit += 1
        if not group:
            out[t] = {"n": 0}
            continue
        if t == "adversarial":
            out[t] = {"n": len(group), "refuting_evidence_hit_at_k": f"{adv_hit}/{len(group)}",
                      "refuting_hit_rate": round(adv_hit / len(group), 4),
                      "latency_ms_p50": round(statistics.median(lat), 2)}
        else:
            hit = sum(1 for r in ranks if r and r <= k)
            mrr = sum(1 / r if r else 0 for r in ranks) / len(ranks)
            out[t] = {"n": len(group), "hit_at_k": round(hit / len(group), 4),
                      "mrr": round(mrr, 4), "latency_ms_p50": round(statistics.median(lat), 2)}
    return out


def eval_intent_routed(idx, items, k):
    """意图路由组合：factual/partial → v3+trust（verified 提权），
    adversarial → v3+refute（rejected 提权——反驳证据就是被判 rejected 的证据）。"""
    a = eval_anchored(idx, items, k, panel_mode="trust")
    b = eval_anchored(idx, items, k, panel_mode="refute")
    merged = {
        "factual": a.get("factual", {"n": 0}),
        "partial": a.get("partial", {"n": 0}),
        "adversarial": b.get("adversarial", {"n": 0}),
    }
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--k2", type=int, default=10)
    ap.add_argument("--out", default="evaluation/unified_gold_metrics.json")
    a = ap.parse_args()

    report = {"protocol": "unified gold retrieval evaluation (multi-gold hit semantics)",
              "warning": "v1 gold is model-judged (gpt-5.6-terra, predicate-level protocol); "
                         "v2 gold is five-model panel consensus (triple-level); neither is human gold",
              "combos": {}}

    for combo in COMBOS:
        idx = load_index(Path(combo["index"]))
        items = [json.loads(x) for x in Path(combo["gold"]).read_text(encoding="utf-8").splitlines() if x.strip()]
        report["combos"][combo["name"]] = {
            "desc": combo["desc"], "index": combo["index"], "gold": combo["gold"],
            "corpus_rows": idx.get("N"), "items": len(items),
            "question_types": {t: sum(1 for g in items if g["question_type"] == t)
                               for t in ("factual", "partial", "adversarial", "ambiguous")},
            "systems": {
                "lexical_bm25": {
                    f"k={a.k}": eval_strategy(idx, items, a.k, kg_boost=False),
                    f"k={a.k2}": eval_strategy(idx, items, a.k2, kg_boost=False)},
                "kg_aware_bm25": {
                    f"k={a.k}": eval_strategy(idx, items, a.k, kg_boost=True),
                    f"k={a.k2}": eval_strategy(idx, items, a.k2, kg_boost=True)},
                "subject_anchored_v3": {
                    f"k={a.k}": eval_anchored(idx, items, a.k),
                    f"k={a.k2}": eval_anchored(idx, items, a.k2)},
                "v3_panel_trust": {
                    f"k={a.k}": eval_anchored(idx, items, a.k, panel_mode="trust"),
                    f"k={a.k2}": eval_anchored(idx, items, a.k2, panel_mode="trust")},
                "v3_intent_routed": {
                    f"k={a.k}": eval_intent_routed(idx, items, a.k),
                    f"k={a.k2}": eval_intent_routed(idx, items, a.k2)},
            },
        }

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
