"""检索流水线.

组合词法 BM25、KG 增强、主体锚定与图扩展，对外提供统一入口::

    pipeline = RetrievalPipeline(store)
    hits = pipeline.retrieve(RetrievalRequest(question=..., strategy="kg"))

策略说明（与前端下拉一一对应）::

    lexical   纯 BM25 词法检索
    kg        BM25 + KG 增强（默认）
    anchored  kg + 主体锚定重排（指明材料的提问）
    graph     kg + 图扩展（沿谓词/实体扩展相邻证据）
"""

from __future__ import annotations

import re

from kgrag.index.store import IndexStore
from kgrag.retrieval import graphexp
from kgrag.retrieval.bm25 import lexical_search
from kgrag.retrieval.kgboost import anchor_rerank, kg_boost
from kgrag.schemas import (
    DEFAULT_STRATEGY,
    RETRIEVAL_STRATEGIES,
    NeighborLine,
    RetrievalHit,
    RetrievalRequest,
)
from kgrag.textproc import query_terms

ABSTAIN_HINT = "当前知识库没有检索到足够的证据，暂不作答。"
MIN_TOP_SCORE = 1.0  # 首位分数低于该阈值视为证据不足（弃答）
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+./-]*")


def _unknown_entity_guard(store: IndexStore, question: str, term_set: set[str]) -> bool:
    """显式未知实体守卫：问题指名了知识库中完全不存在的材料/实体时弃答.

    规则（沿用原系统，防问答模板词误触发）：
    (a) 含拉丁词但无一出现在索引词表中 -> 弃答；
    (b) 所有词元均为未知（只剩模板词） -> 弃答。
    """
    latin = [x for x in _LATIN_RE.findall(question) if len(x) >= 3]
    known_latin = [x.lower() for x in latin if x.lower() in store.df]
    if latin and not known_latin:
        return True
    known = sum(1 for t in term_set if t in store.df)
    return known == 0


class RetrievalPipeline:
    """面向问题的检索编排器（无状态，可并发复用）."""

    def __init__(self, store: IndexStore, *, pool: int = 80):
        self.store = store
        self.pool = pool

    # ------------------------------------------------------------------
    def retrieve(self, req: RetrievalRequest) -> list[RetrievalHit]:
        """执行检索，返回 topk 命中（含同文档邻居窗口）."""
        strategy = req.strategy if req.strategy in RETRIEVAL_STRATEGIES else DEFAULT_STRATEGY
        # 主体锚定：subject 是用户显式给出的实体，直接并入检索词，
        # 确保含主体的证据进入候选池（泛指问题如“这种添加剂的作用”）
        question = req.question
        if strategy == "anchored" and req.subject:
            question = f"{req.question} {req.subject}"
        terms = query_terms(question)
        term_set = set(terms)
        if not term_set or _unknown_entity_guard(self.store, req.question, term_set):
            return []

        # 1) 词法候选
        hits = lexical_search(self.store, question, pool=max(self.pool, req.topk))
        # 2) KG 增强（lexical 策略跳过）；加权改变分数后必须重排序
        if strategy != "lexical":
            hits = kg_boost(hits, req.question, term_set, store=self.store)
            hits.sort(key=lambda h: h.score, reverse=True)

        # 3) 指定文档/谓词过滤（硬过滤）
        if req.doc_id:
            hits = [h for h in hits if h.row.doc_id == req.doc_id]
        if req.predicate_hint and strategy != "lexical":
            hits = [h for h in hits if req.predicate_hint in h.row.predicates] or hits

        # 4) 主体锚定重排
        if strategy == "anchored":
            hits = anchor_rerank(hits, req.subject, req.predicate_hint)

        # 5) 图扩展（扩展后仍截回 topk）
        if strategy == "graph":
            expanded = graphexp.expand(self.store, hits[: req.topk], req.question,
                                      limit=max(req.topk * 3, req.topk))
            hits = expanded[: req.topk]
        else:
            hits = hits[: req.topk]

        # 6) 同文档邻居窗口（不参与独立打分，仅作上下文补充）
        if req.window > 0:
            self._attach_neighbors(hits, req.window)
        return hits

    # ------------------------------------------------------------------
    def _attach_neighbors(self, hits: list[RetrievalHit], window: int) -> None:
        """为每条命中附加同文档相邻行号窗口内的证据."""
        for hit in hits:
            neighbors = []
            for ni in self.store.rows_of_doc(hit.row.doc_id):
                row = self.store.rows[ni]
                if row.evidence_id != hit.row.evidence_id and abs(row.line_no - hit.row.line_no) <= window:
                    neighbors.append(NeighborLine(evidence_id=row.evidence_id, line_no=row.line_no, text=row.text))
            hit.neighbors = sorted(neighbors, key=lambda n: n.line_no)


def retrieve(store: IndexStore, req: RetrievalRequest) -> list[RetrievalHit]:
    """便捷函数：一次性构建流水线并检索."""
    return RetrievalPipeline(store).retrieve(req)


def is_abstained(hits: list[RetrievalHit]) -> bool:
    """弃答判定：无命中，或首位得分低于阈值."""
    return (not hits) or hits[0].score < MIN_TOP_SCORE
