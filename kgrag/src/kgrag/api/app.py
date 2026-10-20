"""FastAPI 应用：REST + SSE 流式问答 + 静态前端托管.

端点一览::

    GET  /api/health            存活与索引状态
    GET  /api/meta              服务元信息（策略/模型/索引统计）
    POST /api/ask               非流式问答
    POST /api/ask/stream        SSE 流式问答（evidence -> reasoning/content -> done）
    GET  /api/evidence/{id}     证据详情（含上下文窗口）
    GET  /api/llm/defaults      服务端默认 LLM 配置（Key 脱敏）
    POST /api/llm/test          测试 LLM 接口连通性（用户配置或默认配置）

鉴权：配置 ``KGRAG_API_KEY`` 后，请求需携带 ``X-API-Key`` 头。
用户级配置：``AskRequest.llm`` 允许请求自带 OpenAI 兼容接口
（base_url / api_key / model），留空字段回退服务端默认。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from kgrag.config import get_settings
from kgrag.schemas import DEFAULT_STRATEGY, RETRIEVAL_STRATEGIES
from kgrag.service import AskResult, QAService

logger = logging.getLogger("kgrag.api")
WEB_DIR = Path(__file__).resolve().parents[3] / "web"

_METRICS = {"requests_total": 0, "errors_total": 0, "abstentions_total": 0,
            "llm_fallbacks_total": 0, "web_searches_total": 0}


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------
class LLMConfig(BaseModel):
    """用户级 LLM 接口覆盖（OpenAI 兼容）：任意字段留空则沿用服务端默认."""

    base_url: str | None = Field(default=None, max_length=500, description="API 地址，如 https://api.epicllmrouter.top/v1")
    api_key: str | None = Field(default=None, max_length=500, description="API Key")
    model: str | None = Field(default=None, max_length=200, description="模型名")


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000, description="用户问题")
    strategy: str = Field(default=DEFAULT_STRATEGY, description="检索策略")
    topk: int = Field(default=8, ge=1, le=30)
    window: int = Field(default=1, ge=0, le=5)
    subject: str | None = Field(default=None, max_length=200, description="主体实体锚点（添加剂名等）")
    predicate_hint: str | None = Field(default=None, description="关系提示")
    doc_id: str | None = Field(default=None, description="限定文档")
    history: list[dict[str, str]] = Field(default_factory=list, max_length=10, description="最近问答历史")
    thinking: bool | None = Field(default=None, description="深度思考开关（None 用服务端默认）")
    llm: LLMConfig | None = Field(default=None, description="用户自带 LLM 接口配置（可选）")
    web_search: bool | None = Field(default=None, description="联网学术检索（目标期刊白名单，None 用服务端默认）")


class AskResponse(BaseModel):
    question: str
    answer: str
    evidence: list[dict]
    latency_ms: float
    retrieval_ms: float
    generation_ms: float
    abstained: bool
    strategy: str
    model: str
    web_search: bool = False
    local_count: int = 0
    web_count: int = 0
    web_query: str = ""


def _result_to_response(r: AskResult) -> AskResponse:
    return AskResponse(
        question=r.question, answer=r.answer, evidence=r.evidence,
        latency_ms=r.latency_ms, retrieval_ms=r.retrieval_ms, generation_ms=r.generation_ms,
        abstained=r.abstained, strategy=r.strategy, model=r.model,
        web_search=r.web_search, local_count=r.local_count,
        web_count=r.web_count, web_query=r.web_query,
    )


def _llm_config_dict(req: AskRequest) -> dict | None:
    """提取请求里的用户级 LLM 覆盖（全空则返回 None，走服务端默认）."""
    if req.llm is None:
        return None
    data = req.llm.model_dump(exclude_none=True)
    return data or None


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------
def create_app(service: QAService | None = None) -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    svc = service or QAService.from_settings()
    api_key = settings.api_key

    app = FastAPI(title="KG-RAG 电镀文献问答系统", version="1.0.0",
                  description="证据优先的电镀领域知识图谱增强检索问答服务")

    def _authorize(x_api_key: str | None) -> None:
        if api_key and x_api_key != api_key:
            raise HTTPException(status_code=401, detail="invalid API key")

    @app.get("/api/health")
    def health():
        return {"status": "ok", **svc.store.stats()}

    @app.get("/api/meta")
    def meta():
        return svc.meta()

    @app.get("/api/metrics")
    def metrics():
        return _METRICS

    @app.post("/api/ask", response_model=AskResponse)
    def ask(req: AskRequest, x_api_key: str | None = Header(default=None)):
        _authorize(x_api_key)
        _METRICS["requests_total"] += 1
        try:
            result = svc.ask(req.question, strategy=req.strategy, topk=req.topk, window=req.window,
                             subject=req.subject, predicate_hint=req.predicate_hint,
                             doc_id=req.doc_id, history=req.history, thinking=req.thinking,
                             llm_config=_llm_config_dict(req), web_search=req.web_search)
        except Exception:
            _METRICS["errors_total"] += 1
            logger.exception("ask failed")
            raise HTTPException(status_code=500, detail="问答处理失败")
        if result.abstained:
            _METRICS["abstentions_total"] += 1
        if result.llm_error:
            _METRICS["llm_fallbacks_total"] += 1
        return _result_to_response(result)

    @app.post("/api/ask/stream")
    async def ask_stream(req: AskRequest, request: Request, x_api_key: str | None = Header(default=None)):
        """SSE 实时流式问答.

        事件序列：status（agent 过程：本地检索/联网检索/生成）-> evidence（证据先达）
        -> reasoning / content（增量）-> done（含延迟统计与本地/网络证据计数）。
        问答编排在线程池执行，增量经 asyncio.Queue 实时推送。
        """
        _authorize(x_api_key)
        _METRICS["requests_total"] += 1
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def emit(kind: str, payload: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

        def on_evidence(evidence: list[dict]) -> None:
            emit("evidence", json.dumps(evidence, ensure_ascii=False))

        def on_delta(kind: str, piece: str) -> None:
            emit(kind, piece)

        def on_status(payload: dict) -> None:
            emit("status", json.dumps(payload, ensure_ascii=False))

        def run_qa() -> None:
            result = svc.ask_stream(req.question, on_evidence=on_evidence, on_delta=on_delta,
                                    on_status=on_status,
                                    strategy=req.strategy, topk=req.topk, window=req.window,
                                    subject=req.subject, predicate_hint=req.predicate_hint,
                                    doc_id=req.doc_id, history=req.history, thinking=req.thinking,
                                    llm_config=_llm_config_dict(req), web_search=req.web_search)
            if result.abstained:
                _METRICS["abstentions_total"] += 1
            if result.llm_error:
                _METRICS["llm_fallbacks_total"] += 1
            if result.web_search:
                _METRICS["web_searches_total"] = _METRICS.get("web_searches_total", 0) + 1
            emit("__done__", json.dumps({
                "answer": result.answer,
                "latency_ms": result.latency_ms,
                "retrieval_ms": result.retrieval_ms,
                "generation_ms": result.generation_ms,
                "abstained": result.abstained,
                "strategy": result.strategy,
                "model": result.model,
                "llm_error": result.llm_error,
                "web_search": result.web_search,
                "local_count": result.local_count,
                "web_count": result.web_count,
                "web_query": result.web_query,
            }, ensure_ascii=False))

        async def event_gen():
            future = loop.run_in_executor(None, run_qa)
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    if future.done() and queue.empty():
                        break
                    continue
                if kind == "__done__":
                    yield {"event": "done", "data": payload}
                    break
                yield {"event": kind, "data": payload}
            await future

        return EventSourceResponse(event_gen())

    @app.get("/api/evidence/{evidence_id}")
    def evidence_detail(evidence_id: str, x_api_key: str | None = Header(default=None)):
        _authorize(x_api_key)
        detail = svc.evidence_by_id(evidence_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="evidence not found")
        return detail

    @app.get("/api/strategies")
    def strategies():
        return {"strategies": RETRIEVAL_STRATEGIES, "default": DEFAULT_STRATEGY}

    # ------------------------------------------------------------------
    # 用户级 LLM 配置接口
    # ------------------------------------------------------------------
    @app.get("/api/llm/defaults")
    def llm_defaults(x_api_key: str | None = Header(default=None)):
        """服务端默认 LLM 配置（Key 脱敏，供前端预填与提示）."""
        _authorize(x_api_key)
        key = settings.llm_api_key
        hint = f"{key[:5]}…{key[-4:]}" if len(key) > 12 else ("已配置" if key else "")
        return {
            "base_url": settings.llm_base_url,
            "model": settings.llm_model,
            "has_key": bool(key),
            "key_hint": hint,
            "llm_enabled": settings.llm_enabled,
        }

    @app.post("/api/llm/test")
    def llm_test(cfg: LLMConfig, x_api_key: str | None = Header(default=None)):
        """测试 LLM 接口连通性：用提交的配置（留空字段回退服务端默认）发一个小请求.

        始终返回 200，以 {ok, model, latency_ms, error} 表达结果，便于前端展示原因。
        """
        _authorize(x_api_key)
        data = cfg.model_dump(exclude_none=True)
        return svc.test_llm(data or None)

    # ------------------------------------------------------------------
    # 静态前端（web/ 目录）
    # ------------------------------------------------------------------
    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(WEB_DIR / "index.html")

    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc: HTTPException):
        """未知路径回退到首页（SPA 行为）."""
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": exc.detail}, status_code=404)
        return FileResponse(WEB_DIR / "index.html")

    return app


# 模块级应用实例：支持 `uvicorn kgrag.api.app:app` 直接启动。
# 测试代码请使用 create_app(service=...) 注入替身，避免加载真实索引。
app = create_app()


def main() -> None:
    """开发服务器入口：``python -m kgrag.api.app``."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
