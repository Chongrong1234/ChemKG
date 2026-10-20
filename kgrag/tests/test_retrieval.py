"""检索流水线测试（BM25 / KG 增强 / 锚定 / 图扩展 / 弃答）."""

from kgrag.retrieval.pipeline import RetrievalPipeline, is_abstained
from kgrag.schemas import RetrievalRequest


def pipe(store):
    return RetrievalPipeline(store)


def test_lexical_retrieval_basic(store):
    hits = pipe(store).retrieve(RetrievalRequest(question="PVP 的抑制作用", strategy="lexical", topk=3))
    assert hits, "词法检索应有命中"
    assert any("PVP" in h.row.text for h in hits)


def test_kg_strategy_beats_lexical_on_entity(store):
    """实体词（高判别力）应通过 KG 提权进入前排."""
    hits = pipe(store).retrieve(RetrievalRequest(question="JGB 在填充中的作用", strategy="kg", topk=2))
    assert hits, "KG 策略应有命中"
    assert any("JGB" in h.row.text for h in hits[:2])


def test_unknown_entity_abstains(store):
    hits = pipe(store).retrieve(RetrievalRequest(question="xyzqwe 不存在的材料效果如何", topk=3))
    assert hits == [] or is_abstained(hits)


def test_topk_respected(store):
    hits = pipe(store).retrieve(RetrievalRequest(question="电沉积 铜 填充", topk=2))
    assert len(hits) <= 2


def test_neighbor_window_attached(store):
    hits = pipe(store).retrieve(RetrievalRequest(question="MPS 加速", topk=1, window=2))
    assert hits
    # doc_2 中相邻行应被附加为邻居
    if hits[0].row.doc_id == "doc_2":
        assert any(n.evidence_id == "ev_ddd" for n in hits[0].neighbors)


def test_strategy_fallback_invalid(store):
    """非法策略名回退到默认 kg，不抛异常."""
    hits = pipe(store).retrieve(RetrievalRequest(question="PVP 作用", strategy="no-such", topk=3))
    assert isinstance(hits, list)


def test_scores_sorted_desc(store):
    hits = pipe(store).retrieve(RetrievalRequest(question="填充", strategy="kg", topk=6))
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True), "加权后必须按分数降序"


def test_hit_serialization(store):
    hits = pipe(store).retrieve(RetrievalRequest(question="PVP", topk=1))
    d = hits[0].to_dict()
    assert d["evidence_id"] == hits[0].row.evidence_id
    assert "score" in d and "text" in d
