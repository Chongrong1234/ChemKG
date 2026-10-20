#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hybrid RAG retriever: BM25 (jieba tokenization) + dense BGE embeddings, fused
with Reciprocal Rank Fusion (RRF) and optional KG-aware boosting.

Usage:
  HF_ENDPOINT=https://hf-mirror.com LD_PRELOAD=/opt/conda/lib/libstdc++.so.6 \
  python rag_hybrid.py --index rag_index --gold evaluation/auto_entity_silver.jsonl --k 5
"""
from __future__ import annotations
import argparse, json, os, statistics, time
from pathlib import Path
from rag_system import load_index, retrieve

MODEL_NAME = os.environ.get("RAG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
QUERY_PREFIX = os.environ.get("RAG_QUERY_PREFIX", "为这个句子生成表示以用于检索相关文章：")

def rrf_fuse(bm25_hits, dense_rank_ids, k=60, rrf_k=60):
    """Reciprocal Rank Fusion over BM25 hits and dense ranking."""
    scores = {}
    for rank, h in enumerate(bm25_hits):
        scores[h["evidence_id"]] = scores.get(h["evidence_id"], 0.0) + 1.0 / (rrf_k + rank + 1)
    for rank, eid in enumerate(dense_rank_ids):
        scores[eid] = scores.get(eid, 0.0) + 1.0 / (rrf_k + rank + 1)
    return scores

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="rag_index")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--dense-depth", type=int, default=50)
    ap.add_argument("--rrf-k", type=int, default=60)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--out", default="evaluation/hybrid.json")
    ap.add_argument("--no-kg-boost", action="store_true")
    a = ap.parse_args()

    from sentence_transformers import SentenceTransformer
    import numpy as np

    idx = load_index(Path(a.index))
    rows = idx["rows"]
    model = SentenceTransformer(MODEL_NAME)

    t0 = time.perf_counter()
    doc_emb = model.encode([r["text"] for r in rows], batch_size=a.batch,
                           normalize_embeddings=True, show_progress_bar=False)
    enc_ms = (time.perf_counter() - t0) * 1000

    items = [json.loads(x) for x in Path(a.gold).read_text(encoding="utf-8").splitlines() if x.strip()]
    q_emb = model.encode([QUERY_PREFIX + g["question"] for g in items], batch_size=a.batch,
                         normalize_embeddings=True, show_progress_bar=False)

    by_id = {r["evidence_id"]: r for r in rows}
    per = []
    for qi, g in enumerate(items):
        t = time.perf_counter()
        bm25_hits = retrieve(idx, g["question"], a.k * 4, 1, kg_boost=not a.no_kg_boost)
        sims = doc_emb @ q_emb[qi]
        dense_ids = [rows[i]["evidence_id"] for i in np.argsort(-sims)[: a.dense_depth]]
        fused = rrf_fuse(bm25_hits, dense_ids, rrf_k=a.rrf_k)
        top_ids = sorted(fused, key=lambda e: -fused[e])[: a.k]
        hits = [{**by_id[e], "score": round(fused[e], 6), "fusion": "rrf"} for e in top_ids if e in by_id]
        ms = (time.perf_counter() - t) * 1000

        ids = {h["evidence_id"] for h in hits}
        gold = set(g.get("gold_evidence_ids", []))
        per.append({
            "id": g.get("id"),
            "hit": bool(ids & gold) if gold else None,
            "recall": len(ids & gold) / len(gold) if gold else None,
            "sufficient": bool(gold and gold <= ids),
            "retrieved": [h["evidence_id"] for h in hits],
            "latency_ms": ms,
        })

    def avg(key):
        xs = [r[key] for r in per if r[key] is not None]
        return sum(xs) / len(xs) if xs else None

    report = {
        "model": MODEL_NAME,
        "fusion": "rrf",
        "rrf_k": a.rrf_k,
        "kg_boost": not a.no_kg_boost,
        "corpus_n": len(rows),
        "encode_ms_total": round(enc_ms, 1),
        "k": a.k,
        "n": len(per),
        "hit_at_k": avg("hit"),
        "evidence_recall_at_k": avg("recall"),
        "sufficient_evidence_rate": avg("sufficient"),
        "latency_ms_p50": statistics.median([r["latency_ms"] for r in per]),
        "latency_ms_mean": statistics.mean([r["latency_ms"] for r in per]),
        "warning": "silver labels; hybrid BM25+dense with RRF fusion",
    }
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
