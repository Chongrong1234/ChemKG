#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal production-facing FastAPI wrapper for the local RAG index."""
from __future__ import annotations
import os, time, logging
from collections import defaultdict, deque
from typing import Any
from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel, Field
from rag_system import load_index, retrieve, llm_answer

logging.basicConfig(level=os.environ.get("RAG_LOG_LEVEL", "INFO"))
logger=logging.getLogger("rag_api")
INDEX_PATH=os.environ.get("RAG_INDEX","rag_index")
INDEX=load_index(__import__("pathlib").Path(INDEX_PATH))
API_KEY=os.environ.get("RAG_API_KEY")
RATE_LIMIT=int(os.environ.get("RAG_RATE_LIMIT", "60"))
WINDOW_SECONDS=60
requests_by_client=defaultdict(deque)
metrics={"requests_total":0,"errors_total":0,"abstentions_total":0}
app=FastAPI(title="Evidence-first Electroplating RAG", version="0.2.0")

class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    topk: int = Field(default=8, ge=1, le=30)
    window: int = Field(default=1, ge=0, le=5)
    predicate: str | None = None
    doc_id: str | None = None
    graph_expand: bool = False
    subject: str | None = Field(default=None, max_length=200, description="主语实体锚点（如添加剂名），启用 v3 锚定检索")
    predicate_hint: str | None = Field(default=None, description="关系提示（inhibits_deposition/accelerates_deposition/synergizes_with/improves_filling/used_as_*/adsorbs_on）")
    panel_mode: str = Field(default="trust", description="评审团状态软加权：off/trust(verified提权)/refute(rejected提权,找反证)")

class AskResponse(BaseModel):
    question: str
    answer: str
    evidence: list[dict[str, Any]]
    latency_ms: float
    abstained: bool

@app.get("/health")
def health():
    return {"status":"ok","index_version":INDEX.get("version"),"evidence_count":INDEX.get("N",0)}

@app.get("/metrics")
def metrics_endpoint():
    return {**metrics,"index_version":INDEX.get("version")}

def authorize(request: Request, x_api_key: str | None):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid API key")
    client=request.client.host if request.client else "unknown"
    now=time.time(); q=requests_by_client[client]
    while q and now-q[0] > WINDOW_SECONDS: q.popleft()
    if len(q) >= RATE_LIMIT: raise HTTPException(status_code=429, detail="rate limit exceeded")
    q.append(now)

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, request: Request, x_api_key: str | None = Header(default=None)):
    authorize(request, x_api_key)
    metrics["requests_total"] += 1
    t=time.perf_counter()
    try:
        hits=retrieve(INDEX,req.question,req.topk,req.window,req.predicate,req.doc_id,
                      graph_expand_enabled=req.graph_expand,
                      subject_anchor=req.subject,predicate_hint=req.predicate_hint,
                      panel_mode=req.panel_mode)
        answer=llm_answer(req.question,hits)
    except Exception as exc:
        metrics["errors_total"] += 1
        logger.exception("RAG request failed")
        raise HTTPException(status_code=500, detail="RAG query failed") from exc
    latency=round((time.perf_counter()-t)*1000,2)
    logger.info("rag_query topk=%s hits=%s latency_ms=%s", req.topk, len(hits), latency)
    abstained=not hits or hits[0].get("score", 0) < 1.0
    if abstained: metrics["abstentions_total"] += 1
    return AskResponse(question=req.question,answer=answer,evidence=hits,latency_ms=latency,abstained=abstained)
