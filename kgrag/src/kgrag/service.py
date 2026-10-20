"""问答编排服务.

将检索流水线、联网学术检索与 LLM 生成组装为端到端问答::

    service = QAService.from_settings()
    result = service.ask(question="PVP 在钴电沉积中起什么作用？")

弃答语义：本地检索与联网检索均为空（或首位得分过低）时，不调用 LLM
生成结论，直接返回证据摘录式说明（可审计的诚实弃答）。

Agent 过程：``on_status`` 回调推送各阶段事件（本地检索 / 英文检索式
生成 / 联网检索 / 综合分析），供前端展示思考链路（CoT 过程面板）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from kgrag.config import Settings, get_settings
from kgrag.generation.llm import LLMClient
from kgrag.generation.prompts import build_answer_messages, extractive_answer
from kgrag.index.store import IndexStore
from kgrag.retrieval.pipeline import RetrievalPipeline, is_abstained
from kgrag.retrieval.websearch import WebSearchClient
from kgrag.schemas import RetrievalHit, RetrievalRequest, RETRIEVAL_STRATEGIES, DEFAULT_STRATEGY

logger = logging.getLogger("kgrag.service")

DeltaCallback = Callable[[str, str], None]
StatusCallback = Callable[[dict], None]


@dataclass
class AskResult:
    """一次问答的完整结果."""

    question: str
    answer: str
    evidence: list[dict] = field(default_factory=list)
    latency_ms: float = 0.0
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    abstained: bool = False
    strategy: str = DEFAULT_STRATEGY
    model: str = ""
    llm_error: str | None = None
    reasoning: str = ""
    # ---- 联网检索 ----
    web_search: bool = False
    local_count: int = 0
    web_count: int = 0
    web_query: str = ""


class QAService:
    """端到端问答服务（检索 -> [联网检索] -> 生成 -> 引用编排）."""

    def __init__(self, store: IndexStore, llm: LLMClient, settings: Settings | None = None,
                 web_search_client: WebSearchClient | None = None):
        self.settings = settings or get_settings()
        self.store = store
        self.llm = llm
        self.pipeline = RetrievalPipeline(store)
        self.web = web_search_client or WebSearchClient(
            timeout_s=self.settings.web_search_timeout_s)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "QAService":
        settings = settings or get_settings()
        store = IndexStore.load(settings.index_dir)
        return cls(store=store, llm=LLMClient(settings), settings=settings)

    # ------------------------------------------------------------------
    def meta(self) -> dict:
        """服务元信息（供前端展示）."""
        return {
            **self.store.stats(),
            "strategies": RETRIEVAL_STRATEGIES,
            "default_strategy": DEFAULT_STRATEGY,
            "llm_enabled": self.settings.llm_enabled,
            "llm_model": self.settings.llm_model,
            "default_topk": self.settings.topk,
        }

    # ------------------------------------------------------------------
    def _retrieve(self, question: str, strategy: str, topk: int, window: int,
                  subject: str | None, predicate_hint: str | None, doc_id: str | None
                  ) -> tuple[list[RetrievalHit], float, str]:
        """检索并返回 (命中, 检索耗时ms, 实际生效的策略名)."""
        t0 = time.perf_counter()
        req = RetrievalRequest(
            question=question, strategy=strategy, topk=topk, window=window,
            subject=subject, predicate_hint=predicate_hint, doc_id=doc_id,
        )
        hits = self.pipeline.retrieve(req)
        effective = req.strategy if req.strategy in RETRIEVAL_STRATEGIES else DEFAULT_STRATEGY
        return hits, (time.perf_counter() - t0) * 1000, effective

    # ------------------------------------------------------------------
    def _client_for(self, llm_config: dict | None) -> LLMClient:
        """按用户级配置返回本次请求的 LLM 客户端（未覆盖时用服务端默认）."""
        if llm_config:
            return LLMClient.with_overrides(**llm_config)
        return self.llm

    # ------------------------------------------------------------------
    def _web_augment(self, question: str, local_hits: list[RetrievalHit],
                     llm: LLMClient, on_status: StatusCallback | None) -> tuple[list[RetrievalHit], str]:
        """联网检索并合并证据：本地证据优先，网络证据补足至总数上限.

        :return: (合并后证据, 英文检索式)
        """
        s = self.settings
        cap = s.evidence_total_cap
        slots = max(0, cap - len(local_hits))
        if slots == 0:
            on_status and on_status({"step": "web", "status": "skipped",
                                      "reason": f"本地证据已达上限 {cap} 条"})
            return local_hits, ""

        # 1) LLM 转写英文检索式
        t0 = time.perf_counter()
        query = self.web.build_query(question, llm)
        on_status and on_status({"step": "web_query", "status": "done", "query": query,
                                 "ms": round((time.perf_counter() - t0) * 1000, 1)})

        # 2) OpenAlex 白名单期刊检索
        t1 = time.perf_counter()
        web_hits = self.web.search(query, limit=min(s.web_search_max_results, slots))
        journals = list(dict.fromkeys(h.row.journal for h in web_hits))
        on_status and on_status({
            "step": "web", "status": "done" if web_hits else "empty",
            "query": query, "count": len(web_hits), "journals": journals,
            "ms": round((time.perf_counter() - t1) * 1000, 1),
        })
        return local_hits + web_hits[:slots], query

    # ------------------------------------------------------------------
    def test_llm(self, llm_config: dict | None = None) -> dict:
        """测试 LLM 接口连通性（用户自带配置或服务端默认）.

        :param llm_config: {base_url, api_key, model}，任意字段可缺省
        :return: {ok, model, latency_ms, error} — 失败也不抛异常，供前端展示原因
        """
        client = self._client_for(llm_config)
        t0 = time.perf_counter()
        result = client.chat(
            [{"role": "user", "content": "连接测试，请只回复：OK"}],
            thinking=False, max_tokens=16,
        )
        return {
            "ok": result.ok,
            "model": result.model or client.settings.llm_model,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "error": result.error,
        }

    # ------------------------------------------------------------------
    def ask(self, question: str, *, strategy: str = DEFAULT_STRATEGY, topk: int | None = None,
            window: int | None = None, subject: str | None = None,
            predicate_hint: str | None = None, doc_id: str | None = None,
            history: list[dict[str, str]] | None = None,
            thinking: bool | None = None, llm_config: dict | None = None,
            web_search: bool | None = None,
            on_status: StatusCallback | None = None) -> AskResult:
        """非流式问答.

        :param llm_config: 用户级 LLM 覆盖 {base_url, api_key, model}（可选）
        :param web_search: 联网学术检索开关（None 用服务端默认）
        :param on_status: agent 过程状态回调（可选）
        """
        t_start = time.perf_counter()
        s = self.settings
        topk = topk or s.topk
        window = s.window if window is None else window
        web_search = s.web_search_enabled if web_search is None else web_search

        # --- 阶段 1：本地知识库检索 ---
        on_status and on_status({"step": "local", "status": "start"})
        hits, retrieval_ms, strategy = self._retrieve(question, strategy, topk, window, subject, predicate_hint, doc_id)
        local_hits = hits
        on_status and on_status({"step": "local", "status": "done",
                                 "count": len(local_hits), "ms": round(retrieval_ms, 1)})

        llm = self._client_for(llm_config)
        web_query = ""
        local_abstained = is_abstained(local_hits)

        # --- 阶段 2：联网学术检索（目标期刊白名单）---
        if web_search:
            hits, web_query = self._web_augment(question, local_hits, llm, on_status)
        else:
            hits = local_hits

        web_hits = [h for h in hits if h.row.source == "web"]
        abstained = local_abstained and not web_hits

        if abstained:
            answer = extractive_answer([])
            return AskResult(question=question, answer=answer, evidence=[], latency_ms=0.0,
                             retrieval_ms=round(retrieval_ms, 2), generation_ms=0.0,
                             abstained=True, strategy=strategy,
                             web_search=web_search, local_count=len(local_hits))

        # --- 阶段 3：综合分析生成 ---
        on_status and on_status({"step": "generate", "status": "start",
                                  "evidence_total": len(hits),
                                  "local": len(hits) - len(web_hits), "web": len(web_hits)})
        t_gen = time.perf_counter()
        result = llm.chat(build_answer_messages(question, hits, history), thinking=thinking)
        generation_ms = (time.perf_counter() - t_gen) * 1000
        answer = result.content if result.ok else extractive_answer(hits)
        if not result.ok and result.error:
            logger.warning("LLM 生成失败，退化为证据摘录：%s", result.error)

        return AskResult(
            question=question, answer=answer,
            evidence=[h.to_dict() for h in hits],
            latency_ms=round((time.perf_counter() - t_start) * 1000, 2),
            retrieval_ms=round(retrieval_ms, 2),
            generation_ms=round(generation_ms, 2),
            abstained=False, strategy=strategy,
            model=result.model or self.settings.llm_model,
            llm_error=result.error, reasoning=result.reasoning,
            web_search=web_search, local_count=len(hits) - len(web_hits),
            web_count=len(web_hits), web_query=web_query,
        )

    # ------------------------------------------------------------------
    def ask_stream(self, question: str, *, on_evidence: Callable[[list[dict]], None],
                   on_delta: DeltaCallback, on_status: StatusCallback | None = None,
                   **kwargs) -> AskResult:
        # kwargs 额外支持 thinking / llm_config / web_search
        """流式问答：先推送 agent 过程状态，再推送证据，最后流式推送生成增量.

        事件顺序（经上层 SSE）::

            status(local) -> status(web_query) -> status(web) -> status(generate)
            -> evidence -> reasoning/content 增量 -> done

        :param on_evidence: 证据就绪回调（本地 + 联网合并后的完整列表）
        :param on_delta: 增量回调（"reasoning" | "content", piece）
        :param on_status: agent 过程状态回调（CoT 过程面板数据源）
        """
        t_start = time.perf_counter()
        s = self.settings
        strategy = kwargs.get("strategy", DEFAULT_STRATEGY)
        topk = kwargs.get("topk") or s.topk
        window = s.window if kwargs.get("window") is None else kwargs["window"]
        web_search = s.web_search_enabled if kwargs.get("web_search") is None else kwargs["web_search"]

        # --- 阶段 1：本地知识库检索 ---
        on_status and on_status({"step": "local", "status": "start"})
        hits, retrieval_ms, strategy = self._retrieve(question, strategy, topk, window,
                                                      kwargs.get("subject"), kwargs.get("predicate_hint"),
                                                      kwargs.get("doc_id"))
        local_hits = hits
        on_status and on_status({"step": "local", "status": "done",
                                 "count": len(local_hits), "ms": round(retrieval_ms, 1)})

        llm = self._client_for(kwargs.get("llm_config"))
        web_query = ""
        local_abstained = is_abstained(local_hits)

        # --- 阶段 2：联网学术检索 ---
        if web_search:
            hits, web_query = self._web_augment(question, local_hits, llm, on_status)
        web_hits = [h for h in hits if h.row.source == "web"]
        abstained = local_abstained and not web_hits

        on_evidence([h.to_dict() for h in hits])

        if abstained:
            return AskResult(question=question, answer=extractive_answer([]), evidence=[],
                             latency_ms=0.0, retrieval_ms=round(retrieval_ms, 2), generation_ms=0.0,
                             abstained=True, strategy=strategy, web_search=web_search,
                             local_count=len(local_hits))

        # --- 阶段 3：综合分析生成（流式） ---
        on_status and on_status({"step": "generate", "status": "start",
                                  "evidence_total": len(hits),
                                  "local": len(hits) - len(web_hits), "web": len(web_hits)})
        t_gen = time.perf_counter()
        result = llm.chat_stream(build_answer_messages(question, hits, kwargs.get("history")),
                                 on_delta, thinking=kwargs.get("thinking"))
        generation_ms = (time.perf_counter() - t_gen) * 1000
        answer = result.content if result.ok else extractive_answer(hits)
        if result.ok and result.reasoning:
            on_delta("reasoning_done", result.reasoning)

        return AskResult(
            question=question,
            answer=answer,
            evidence=[h.to_dict() for h in hits],
            latency_ms=round((time.perf_counter() - t_start) * 1000, 2),
            retrieval_ms=round(retrieval_ms, 2),
            generation_ms=round(generation_ms, 2),
            abstained=False,
            strategy=strategy,
            model=result.model or self.settings.llm_model,
            llm_error=result.error,
            reasoning=result.reasoning,
            web_search=web_search,
            local_count=len(hits) - len(web_hits),
            web_count=len(web_hits),
            web_query=web_query,
        )

    # ------------------------------------------------------------------
    def evidence_by_id(self, evidence_id: str) -> dict | None:
        """按 ID 查询证据详情（含同文档窗口）."""
        row = self.store.row_by_id(evidence_id)
        if row is None:
            return None
        hit = RetrievalHit(row=row, score=0.0, matched_terms=[])
        self.pipeline._attach_neighbors([hit], 2)
        return hit.to_dict()
