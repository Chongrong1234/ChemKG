"""联网增强问答编排测试（替身 WebSearchClient，不触网）."""

import pytest

from kgrag.generation.llm import LLMClient, LLMResult
from kgrag.schemas import EvidenceRow, NeighborLine, RetrievalHit
from kgrag.service import QAService


class FakeLLM(LLMClient):
    def chat(self, messages, *, thinking=None, max_tokens=None):
        return LLMResult(content="综合本地与联网文献：结论 [ev_aaa]，网络佐证 [web_11112233]。",
                         model="fake-model")

    def chat_stream(self, messages, on_delta, *, thinking=None):
        on_delta("content", "综合结论 [ev_aaa] / [web_11112233]。")
        return LLMResult(content="综合结论 [ev_aaa] / [web_11112233]。", model="fake-model")


def web_hit(eid: str, journal: str = "Electrochimica Acta") -> RetrievalHit:
    row = EvidenceRow(evidence_id=eid, doc_id="web", line_no=0,
                      text="web abstract about cobalt", title="A Web Paper",
                      source="web", journal=journal, year=2023,
                      authors=["X. Y"], doi="10.1/x")
    return RetrievalHit(row=row, score=0.9, matched_terms=[])


class FakeWebSearch:
    """替身：build_query 返回固定检索式，search 返回 N 条网络证据."""

    def __init__(self, n_results=5):
        self.n = n_results
        self.last_query = None

    def build_query(self, question, llm=None):
        return "cobalt electrodeposition PVP"

    def search(self, query, limit=12):
        self.last_query = query
        return [web_hit(f"web_{i:08d}") for i in range(min(self.n, limit))]


def make_service(store, web=None) -> QAService:
    return QAService(store=store, llm=FakeLLM(), web_search_client=web)


def test_ask_web_search_merges_evidence(store):
    """联网开启时：本地 + 网络证据合并，计数正确."""
    svc = make_service(store, web=FakeWebSearch(n_results=5))
    r = svc.ask("PVP 的抑制作用", topk=3, web_search=True)
    assert r.abstained is False
    assert r.web_search is True
    assert r.local_count == 2  # 迷你库中 PVP 相关证据共 2 条
    assert r.web_count == 5
    assert len(r.evidence) == 7
    assert r.web_query == "cobalt electrodeposition PVP"
    # 证据序列化含 web 字段
    web_evs = [e for e in r.evidence if e.get("source") == "web"]
    assert len(web_evs) == 5
    assert web_evs[0]["journal"] == "Electrochimica Acta"


def test_ask_web_search_disabled(store):
    """联网关闭：行为与旧版一致（仅本地证据）."""
    svc = make_service(store, web=FakeWebSearch())
    r = svc.ask("PVP 的抑制作用", topk=3, web_search=False)
    assert r.web_search is False
    assert r.web_count == 0
    assert all(e.get("source") != "web" for e in r.evidence)


def test_web_evidence_capped_at_total(store):
    """本地 + 网络合并后总数不超过上限（默认 20）."""
    svc = make_service(store, web=FakeWebSearch(n_results=50))
    r = svc.ask("PVP 的抑制作用", topk=8, web_search=True)
    assert len(r.evidence) <= 20
    assert r.local_count == 2  # 库中 PVP 证据仅 2 条
    assert r.web_count == 12  # min(上限12, 20-2)
    assert len(r.evidence) == 14


def test_web_rescues_abstention(store):
    """本地无证据但联网有结果时：不弃答，用网络证据生成."""
    svc = make_service(store, web=FakeWebSearch(n_results=4))
    r = svc.ask("zzzxxx 不存在物质qwe 效果", topk=3, web_search=True)
    assert r.abstained is False
    assert r.web_count == 4
    assert r.local_count == 0  # 本地检索为空


def test_abstain_when_both_empty(store):
    """本地与联网都无结果时：保持弃答."""
    svc = make_service(store, web=FakeWebSearch(n_results=0))
    r = svc.ask("zzzxxx 不存在物质qwe 效果", topk=3, web_search=True)
    assert r.abstained is True
    assert r.evidence == []


def test_status_callback_sequence(store):
    """status 回调按 agent 流程顺序推送各阶段事件."""
    svc = make_service(store, web=FakeWebSearch(n_results=5))
    statuses = []
    r = svc.ask("PVP 的抑制作用", topk=3, web_search=True, on_status=statuses.append)
    steps = [s["step"] for s in statuses]
    # 顺序：local(start/done) -> web_query -> web -> generate
    assert steps[0] == "local"
    assert "web_query" in steps
    assert "web" in steps
    assert steps[-1] == "generate"
    local_done = next(s for s in statuses if s["step"] == "local" and s["status"] == "done")
    assert local_done["count"] == 2
    web_done = next(s for s in statuses if s["step"] == "web" and s["status"] == "done")
    assert web_done["count"] == 5
    assert "Electrochimica Acta" in web_done["journals"]
    gen = statuses[-1]
    assert gen["local"] == 2 and gen["web"] == 5 and gen["evidence_total"] == 7


def test_ask_stream_emits_status_and_merged_evidence(store):
    """流式路径：status 事件先于 evidence，evidence 为合并列表."""
    svc = make_service(store, web=FakeWebSearch(n_results=4))
    events = []
    r = svc.ask_stream("PVP 的抑制作用", on_evidence=lambda ev: events.append(("evidence", ev)),
                       on_delta=lambda k, p: events.append((k, p)),
                       on_status=lambda s: events.append(("status", s)),
                       topk=3, web_search=True)
    kinds = [e[0] for e in events]
    first_status = kinds.index("status")
    first_evidence = kinds.index("evidence")
    assert first_status < first_evidence
    evidence = events[first_evidence][1]
    assert len(evidence) == 6  # 2 本地 + 4 网络
    assert r.web_count == 4
    assert any(s["step"] == "generate" for s in [e[1] for e in events if e[0] == "status"])
