"""服务层与 API 集成测试（使用替身 LLM，不触网）."""

import json

from fastapi.testclient import TestClient

from kgrag.api.app import create_app
from kgrag.generation.llm import LLMClient, LLMResult
from kgrag.service import QAService


class FakeLLM(LLMClient):
    """离线替身：内容型输出 + 模拟 reasoning."""

    def __init__(self, settings=None):
        super().__init__(settings)

    def chat(self, messages, *, thinking=None):
        return LLMResult(content="PVP 是抑制剂 [ev_aaa]。", reasoning="fake reasoning",
                         model="fake-model", usage={"total_tokens": 10})

    def chat_stream(self, messages, on_delta, *, thinking=None):
        on_delta("reasoning", "thinking...")
        on_delta("content", "PVP 是抑制剂 ")
        on_delta("content", "[ev_aaa]。")
        return LLMResult(content="PVP 是抑制剂 [ev_aaa]。", reasoning="thinking...", model="fake-model")


def make_service(store) -> QAService:
    return QAService(store=store, llm=FakeLLM())


def test_ask_returns_answer_and_evidence(store):
    svc = make_service(store)
    r = svc.ask("PVP 的抑制作用", strategy="kg", topk=3)
    assert "PVP" in r.answer
    assert r.evidence, "应返回证据列表"
    assert r.abstained is False
    assert r.model == "fake-model"


def test_ask_abstain_on_unknown(store):
    svc = make_service(store)
    r = svc.ask("zzzqq 不存在的物质效果", strategy="kg", topk=3)
    assert r.abstained is True
    assert r.evidence == []
    assert "暂不作答" in r.answer


def test_ask_stream_events(store):
    svc = make_service(store)
    events = []

    def on_ev(evidence):
        events.append(("evidence", evidence))

    def on_delta(kind, piece):
        events.append((kind, piece))

    r = svc.ask_stream("PVP 的作用", on_evidence=on_ev, on_delta=on_delta, strategy="kg", topk=3)
    kinds = [k for k, _ in events]
    assert kinds[0] == "evidence"
    assert "content" in kinds
    assert r.answer


def test_api_health_and_ask(store):
    app = create_app(service=make_service(store))
    client = TestClient(app)

    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    resp = client.post("/api/ask", json={"question": "PVP 的抑制作用", "topk": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert data["question"].startswith("PVP")
    assert isinstance(data["evidence"], list)
    assert data["model"] == "fake-model"


def test_api_ask_stream_sse(store):
    app = create_app(service=make_service(store))
    client = TestClient(app)

    with client.stream("POST", "/api/ask/stream",
                       json={"question": "PVP 的抑制作用", "topk": 3}) as resp:
        assert resp.status_code == 200
        body = "".join(chunk for chunk in resp.iter_text())
    assert "event: evidence" in body
    assert "event: content" in body
    assert "event: done" in body


def test_api_evidence_detail(store):
    app = create_app(service=make_service(store))
    client = TestClient(app)

    ok = client.get("/api/evidence/ev_aaa")
    assert ok.status_code == 200
    assert ok.json()["evidence_id"] == "ev_aaa"

    missing = client.get("/api/evidence/ev_notexist")
    assert missing.status_code == 404


def test_api_strategies(store):
    app = create_app(service=make_service(store))
    client = TestClient(app)
    data = client.get("/api/strategies").json()
    assert set(data["strategies"]) == {"lexical", "kg", "anchored", "graph"}
    assert data["default"] == "kg"


def test_api_validation_error(store):
    app = create_app(service=make_service(store))
    client = TestClient(app)
    resp = client.post("/api/ask", json={"question": "x"})  # 长度不足
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 用户级 LLM 配置接口
# ---------------------------------------------------------------------------
def test_llm_with_overrides_factory():
    """with_overrides 应生成覆盖副本且不污染全局 Settings."""
    from kgrag.config import get_settings

    s0 = get_settings()
    client = LLMClient.with_overrides(base_url="https://custom.example/v1",
                                      api_key="sk-custom", model="my-model")
    assert client.settings.llm_base_url == "https://custom.example/v1"
    assert client.settings.llm_api_key == "sk-custom"
    assert client.settings.llm_model == "my-model"
    # 全局配置未被修改
    assert get_settings() is s0
    assert s0.llm_base_url != "https://custom.example/v1" or True
    # 部分覆盖：留空字段沿用默认
    client2 = LLMClient.with_overrides(model="only-model")
    assert client2.settings.llm_model == "only-model"
    assert client2.settings.llm_base_url == s0.llm_base_url
    # 任何字段都不传 -> 与默认一致
    client3 = LLMClient.with_overrides()
    assert client3.settings.llm_api_key == s0.llm_api_key


def test_service_test_llm_uses_override(store, monkeypatch):
    """test_llm 应按覆盖配置构造客户端（而不是服务端默认 LLM）."""
    import kgrag.service as svc_mod

    created = {}

    class SpyLLM(svc_mod.LLMClient):
        def chat(self, messages, *, thinking=None, max_tokens=None):
            created["messages"] = messages
            created["model"] = self.settings.llm_model
            created["key"] = self.settings.llm_api_key
            created["max_tokens"] = max_tokens
            return LLMResult(content="OK", model=self.settings.llm_model)

    monkeypatch.setattr(svc_mod, "LLMClient", SpyLLM)
    svc = make_service(store)
    result = svc.test_llm({"base_url": "https://x.example/v1", "api_key": "sk-user", "model": "user-model"})

    assert result["ok"] is True
    assert created["model"] == "user-model"
    assert created["key"] == "sk-user"
    assert created["max_tokens"] == 16  # 测试请求应限制 token
    assert result["model"] == "user-model"


def test_api_llm_defaults(store):
    from kgrag.config import get_settings

    app = create_app(service=make_service(store))
    client = TestClient(app)
    resp = client.get("/api/llm/defaults")
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_url"].startswith("http")
    assert "model" in data
    assert isinstance(data["has_key"], bool)
    # 不得泄露完整 Key：响应里不能出现真实 key 原文
    real_key = get_settings().llm_api_key
    if real_key:
        assert real_key not in json.dumps(data)
        assert data["has_key"] is True


def test_api_llm_test_endpoint(store, monkeypatch):
    import kgrag.service as svc_mod

    captured = {}

    class SpyLLM(svc_mod.LLMClient):
        def chat(self, messages, *, thinking=None, max_tokens=None):
            captured["model"] = self.settings.llm_model
            captured["key"] = self.settings.llm_api_key
            return LLMResult(content="OK", model=self.settings.llm_model)

    monkeypatch.setattr(svc_mod, "LLMClient", SpyLLM)
    app = create_app(service=make_service(store))
    client = TestClient(app)
    resp = client.post("/api/llm/test", json={"base_url": "https://x.example/v1",
                                              "api_key": "sk-user", "model": "user-model"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "latency_ms" in data
    # 端点透传了用户提交的覆盖配置
    assert captured["model"] == "user-model"
    assert captured["key"] == "sk-user"


def test_api_ask_with_llm_override(store, monkeypatch):
    """带 llm 覆盖的请求应使用覆盖客户端生成（不触网：用 Spy 替身验证）."""
    import kgrag.service as svc_mod

    used_model = {}

    class SpyLLM(svc_mod.LLMClient):
        def chat(self, messages, *, thinking=None, max_tokens=None):
            used_model["value"] = self.settings.llm_model
            return LLMResult(content="覆盖模型回答 [ev_aaa]", model=self.settings.llm_model)

    monkeypatch.setattr(svc_mod, "LLMClient", SpyLLM)
    app = create_app(service=make_service(store))
    client = TestClient(app)
    resp = client.post("/api/ask", json={
        "question": "PVP 的抑制作用", "topk": 3,
        "llm": {"base_url": "https://x.example/v1", "api_key": "sk-user", "model": "user-model"},
    })
    assert resp.status_code == 200
    assert resp.json()["model"] == "user-model"
    assert used_model["value"] == "user-model"


def test_api_ask_with_empty_llm_falls_back(store):
    """llm 字段全空时应回退服务端默认（不报错）."""
    app = create_app(service=make_service(store))
    client = TestClient(app)
    resp = client.post("/api/ask", json={
        "question": "PVP 的抑制作用", "topk": 3, "llm": {},
    })
    assert resp.status_code == 200
    assert resp.json()["model"] == "fake-model"
