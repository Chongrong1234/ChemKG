"""BM25 词法检索器.

基于倒排索引的 Okapi BM25 实现（k1=1.2, b=0.75），
不依赖 rank_bm25/faiss 等外部库即可运行。
"""

from __future__ import annotations

import math
from collections import defaultdict

from kgrag.index.store import IndexStore
from kgrag.schemas import RetrievalHit
from kgrag.textproc import query_terms

K1 = 1.2
B = 0.75


def score_bm25(store: IndexStore, terms: list[str]) -> dict[int, float]:
    """对整个索引按 BM25 打分，返回 {row_index: score}."""
    scores: dict[int, float] = defaultdict(float)
    n = max(1, store.n)
    for term in set(terms):
        idf = math.log((n + 1) / (store.doc_freq(term) + 1)) + 1
        for i in store.postings(term):
            row = store.rows[i]
            tf = row.tokens.count(term)
            norm = tf * (K1 + 1) / (tf + K1 * (1 - B + B * max(1, row.dl) / max(1.0, store.avgdl)))
            scores[i] += norm * idf
    return scores


def lexical_search(store: IndexStore, question: str, *, pool: int = 80) -> list[RetrievalHit]:
    """纯词法检索，返回去重后的候选命中（未截断到 topk）."""
    terms = query_terms(question)
    if not terms:
        return []
    scores = score_bm25(store, terms)
    term_set = set(terms)
    ranked = sorted(scores, key=lambda i: scores[i], reverse=True)

    hits: list[RetrievalHit] = []
    seen: set[tuple[str, int]] = set()
    matched: dict[int, set[str]] = defaultdict(set)
    # 记录每行命中的词元
    for t in term_set:
        for i in store.postings(t):
            matched[i].add(t)

    for i in ranked:
        row = store.rows[i]
        key = (row.doc_id, row.line_no)
        if key in seen:
            continue
        seen.add(key)
        hits.append(RetrievalHit(row=row, score=scores[i], matched_terms=sorted(matched[i])))
        if len(hits) >= pool:
            break
    return hits


def overlap_ratio(hit: RetrievalHit, term_set: set[str]) -> float:
    """查询词元覆盖率（用于相关性折扣）."""
    if not term_set:
        return 0.0
    return len(set(hit.matched_terms) & term_set) / max(1, len(term_set))
