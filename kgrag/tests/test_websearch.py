"""联网学术检索模块测试（mock httpx，不触网）."""

import httpx
import pytest

from kgrag.retrieval.websearch import (
    TARGET_JOURNALS, WebSearchClient, _rebuild_abstract,
)
from kgrag.schemas import EvidenceRow, RetrievalHit


# ---------------------------------------------------------------------------
def test_target_journals_whitelist():
    """白名单覆盖用户指定的 11 本期刊."""
    assert len(TARGET_JOURNALS) == 11
    for name in ["Electrochimica Acta", "ACS Omega", "Small",
                 "Journal of Alloys and Compounds", "Applied Surface Science"]:
        assert any(name in k for k in TARGET_JOURNALS), name


def test_rebuild_abstract():
    inverted = {"Cobalt": [0], "electrodeposition": [1], "was": [2], "studied": [3]}
    assert _rebuild_abstract(inverted) == "Cobalt electrodeposition was studied"
    assert _rebuild_abstract(None) == ""
    assert _rebuild_abstract({}) == ""


def test_fallback_query():
    client = WebSearchClient()
    q = client.build_query("PVP 在钴电沉积中的作用？")  # 无 LLM → 回退
    assert "pvp" in q.lower()
    assert "electrochemistry" in q


def test_search_parses_openalex_response(monkeypatch):
    """OpenAlex 响应解析：摘要重建、期刊过滤、去重、伪 RetrievalHit 结构."""
    fake = {
        "results": [
            {
                "title": "PVP effect on cobalt electrodeposition",
                "publication_year": 2023,
                "doi": "https://doi.org/10.1016/j.electacta.2023.01.001",
                "authorships": [{"author": {"display_name": "A. Wang"}},
                                {"author": {"display_name": "B. Li"}}],
                "abstract_inverted_index": {"Cobalt": [0], "deposition": [1], "with": [2], "PVP": [3]},
                "primary_location": {"source": {"display_name": "Electrochimica Acta"}},
                "relevance_score": 42.1,
            },
            {  # 非白名单期刊 → 应被过滤
                "title": "Something else",
                "publication_year": 2020,
                "doi": "https://doi.org/10.9999/x",
                "authorships": [],
                "abstract_inverted_index": {"x": [0]},
                "primary_location": {"source": {"display_name": "Nature"}},
                "relevance_score": 40.0,
            },
            {  # 与第一条同 DOI → 应去重
                "title": "Duplicate",
                "doi": "https://doi.org/10.1016/j.electacta.2023.01.001",
                "abstract_inverted_index": {"dup": [0]},
                "primary_location": {"source": {"display_name": "Electrochimica Acta"}},
            },
            {  # 无摘要 → 跳过
                "title": "No abstract",
                "doi": "https://doi.org/10.1016/y",
                "abstract_inverted_index": None,
                "primary_location": {"source": {"display_name": "ACS Omega"}},
            },
        ]
    }

    def fake_get(self, url, params=None, **kwargs):
        return httpx.Response(200, json=fake, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = WebSearchClient()
    hits = client.search("PVP cobalt electrodeposition", limit=10)

    assert len(hits) == 1  # 只留白名单 + 有摘要 + 去重后的第一条
    h = hits[0]
    assert isinstance(h, RetrievalHit)
    assert h.row.source == "web"
    assert h.row.evidence_id.startswith("web_")
    assert h.row.journal == "Electrochimica Acta"
    assert h.row.year == 2023
    assert h.row.doi == "10.1016/j.electacta.2023.01.001"
    assert h.row.text == "Cobalt deposition with PVP"
    assert h.row.authors == ["A. Wang", "B. Li"]
    assert h.score > 0  # 按排名赋分
    # to_dict 序列化含 web 扩展字段
    d = h.to_dict()
    assert d["source"] == "web" and d["journal"] == "Electrochimica Acta"


def test_search_network_failure_returns_empty(monkeypatch):
    """网络失败静默降级为空结果."""
    def boom(self, *a, **kw):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx.Client, "get", boom)
    client = WebSearchClient()
    assert client.search("anything") == []


def test_search_uses_cache(monkeypatch):
    """相同检索式命中内存缓存（第二次不再发请求）."""
    calls = {"n": 0}

    def fake_get(self, url, params=None, **kwargs):
        calls["n"] += 1
        return httpx.Response(200, json={"results": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = WebSearchClient()
    client.search("cache test")
    client.search("cache test")
    assert calls["n"] == 1


def test_build_query_via_llm():
    """LLM 转写英文检索式."""
    from kgrag.generation.llm import LLMClient, LLMResult

    class FakeGen(LLMClient):
        def chat(self, messages, *, thinking=None, max_tokens=None):
            return LLMResult(content="PVP cobalt electrodeposition inhibitor mechanism",
                             model="fake")

    client = WebSearchClient()
    q = client.build_query("PVP 在钴电沉积中起什么作用？", llm=FakeGen())
    assert q == "PVP cobalt electrodeposition inhibitor mechanism"


def test_build_query_llm_garbage_falls_back():
    """LLM 输出不合理（过短）时回退到拉丁词."""
    from kgrag.generation.llm import LLMClient, LLMResult

    class BadLLM(LLMClient):
        def chat(self, messages, *, thinking=None, max_tokens=None):
            return LLMResult(content="x", model="fake")

    client = WebSearchClient()
    q = client.build_query("PVP 钴沉积", llm=BadLLM())
    assert "pvp" in q.lower()
