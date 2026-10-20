"""KG 感知的检索增强.

三类信号（沿用原系统经过评测验证的权重）：
1. 关系词加权：问题中的关系表述（如“抑制/加速/填充”）与证据谓词匹配时加分；
2. 实体字面匹配：问题中的拉丁实体词出现在证据文本中时加分；
3. 主体锚定重排：用户指明材料主体时，包含该主体的证据大幅提权
   （mult_subject≈2.5），谓词提示词作为次级加权。
"""

from __future__ import annotations

from kgrag.retrieval.bm25 import overlap_ratio
from kgrag.schemas import RetrievalHit
from kgrag.textproc import latin_terms, zh_terms

REL_WORDS = {
    "inhibit": "inhibits_deposition",
    "抑制": "inhibits_deposition",
    "accelerat": "accelerates_deposition",
    "加速": "accelerates_deposition",
    "synerg": "synergizes_with",
    "协同": "synergizes_with",
    "filling": "improves_filling",
    "填充": "improves_filling",
    "improv": "improves_filling",
}

REL_ALIASES = {
    "inhibits_deposition": ["inhibit", "inhibits", "抑制", "inhibitor", "suppressor", "抑制剂"],
    "accelerates_deposition": ["accelerat", "accelerated", "accelerator", "加速", "加速剂"],
    "synergizes_with": ["synerg", "synergy", "协同", "协同作用"],
    "improves_filling": ["improv", "filling", "superfilling", "改善", "填充", "整平", "leveler"],
}

PRED_TERM_HINTS = {
    "inhibits_deposition": ["inhibit", "suppress", "inhibitor", "抑制", "阻碍"],
    "accelerates_deposition": ["accelerat", "加速", "催化", "accelerator"],
    "synergizes_with": ["synerg", "协同"],
    "improves_filling": ["improve", "fill", "enhanc", "填充", "改善", "整平"],
}


def _principal_entity(store, entity_terms: list[str], min_idf: float = 4.0) -> str | None:
    """选出查询中判别力最强的拉丁实体词（隐式主语锚点）.

    idf 阈值过滤掉通用词（如 deposition/effect），只留材料缩写、
    化合物名等高判别力实体；df 为 0（未知词）不参与提权。
    """
    if store is None or not entity_terms:
        return None
    import math

    best, best_idf = None, 0.0
    for term in entity_terms:
        df = store.doc_freq(term)
        if df <= 0:
            continue
        idf = math.log((max(1, store.n) + 1) / (df + 1)) + 1
        if idf >= min_idf and idf > best_idf:
            best, best_idf = term, idf
    return best


def kg_boost(hits: list[RetrievalHit], question: str, term_set: set[str],
            store=None) -> list[RetrievalHit]:
    """对词法命中施加 KG 感知加权（原位修改并返回）.

    实体字面匹配按词元 idf 加权；查询中判别力最强的主实体词
    （如材料缩写 PVP/JGB）额外获得乘法提权，避免被
    "钴/电沉积"等高频通用词淹没。
    """
    q_lower = question.lower()
    entity_terms = [t for t in latin_terms(question, min_len=2)]
    principal = _principal_entity(store, entity_terms)

    def entity_bonus(term: str) -> float:
        if store is None:
            return 0.35
        import math
        idf = math.log((max(1, store.n) + 1) / (store.doc_freq(term) + 1)) + 1
        return 0.5 * idf + 0.35  # idf 加权 + 基础分

    for hit in hits:
        text = (hit.row.text + " " + " ".join(hit.row.entities)).lower()
        # 查询覆盖率折扣
        hit.score *= 0.65 + 0.35 * overlap_ratio(hit, term_set)
        # 实体字面匹配（idf 加权）
        for t in entity_terms:
            if t in text:
                hit.score += entity_bonus(t)
        # 主实体乘法提权
        if principal and principal in text:
            hit.score *= 1.8
        # 关系词 -> 谓词匹配
        for word, pred in REL_WORDS.items():
            if word in q_lower and pred in hit.row.predicates:
                hit.score += 0.5
        for pred, aliases in REL_ALIASES.items():
            if any(a in q_lower for a in aliases) and pred in hit.row.predicates:
                hit.score += 1.0
    return hits


def anchor_rerank(
    hits: list[RetrievalHit],
    subject: str | None,
    predicate_hint: str | None,
    *,
    mult_subject: float = 2.5,
    mult_predicate: float = 1.35,
) -> list[RetrievalHit]:
    """主体锚定重排：包含主体材料名/谓词提示词的证据提权."""
    if not (subject or predicate_hint):
        return hits
    latin_sub = latin_terms(subject or "", min_len=2)
    zh_sub = zh_terms(subject or "")
    pred_terms = PRED_TERM_HINTS.get(predicate_hint or "", [])

    def anchored(hit: RetrievalHit) -> float:
        score = hit.score
        text = hit.row.text.lower()
        if latin_sub and any(s in text for s in latin_sub):
            score *= mult_subject
        if zh_sub and any(s in text for s in zh_sub):
            score *= mult_subject
        if pred_terms and any(p in text for p in pred_terms):
            score *= mult_predicate
        return score

    return sorted(hits, key=anchored, reverse=True)
