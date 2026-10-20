#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence-first hybrid RAG for the local electroplating KG.

This first version is deliberately local and dependency-light:
- BM25-like lexical retrieval implemented with TF-IDF cosine similarity;
- KG-aware boosting from entities, values, and candidate facts;
- evidence-window expansion around the matched line;
- optional OpenAI-compatible generation, with a deterministic extractive fallback.

Examples:
  python rag_system.py build --kg kg_data --docs 文献提取 --out rag_index
  python rag_system.py ask --index rag_index --question "哪些添加剂改善铜微孔填充？"
  python rag_system.py ask --index rag_index --question "..." --json
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, re, sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from graph_retriever import expand as graph_expand

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+./-]*|[\u4e00-\u9fff]+|\d+(?:\.\d+)?")
STOP = set("the and for with from that this are was were has have into using used under through about which their there then than can may not does how what why where when whose with".split())
# Question/boilerplate Chinese words are removed so discriminative domain terms
# (chemical names, additives, conditions) dominate BM25 instead of template text.
ZH_STOP = set("""的 了 是 在 和 与 对 于 及 其 中 以 由 将 被 中起 也 都 还 有 这 那 个 一 不 可 能 等 作为 起到 时候 起来
什么 如何 是否 没有 哪些 哪 有没有 内容 报道 文献 知识库 记录 证据 线索 问题 作用 时候 起来 进行 关于
研究 报道 过程 记录 能够 可以 具有 出现 表明 说明 结果 以及 因此 另外 其中 这些 那些""".split())
try:
    import jieba
    def zh_words(run: str) -> list[str]:
        return [w.strip() for w in jieba.lcut(run) if w.strip()]
except Exception:  # pragma: no cover - fallback if jieba unavailable
    def zh_words(run: str) -> list[str]:
        return [run[i:i+2] for i in range(len(run)-1)] or ([run] if run else [])
REL_WORDS = {"inhibit": "inhibits_deposition", "抑制": "inhibits_deposition", "accelerat": "accelerates_deposition", "加速": "accelerates_deposition", "synerg": "synergizes_with", "协同": "synergizes_with", "filling": "improves_filling", "填充": "improves_filling", "improv": "improves_filling", "整平": "used_as_leveler", "leveler": "used_as_leveler", "吸附": "adsorbs_on", "adsorb": "adsorbs_on"}
REL_ALIASES = {
    "inhibits_deposition": ["inhibit", "inhibits", "抑制", "inhibitor", "suppressor", "抑制剂"],
    "accelerates_deposition": ["accelerat", "accelerated", "accelerator", "加速", "加速剂"],
    "synergizes_with": ["synerg", "synergy", "协同", "协同作用"],
    "improves_filling": ["improv", "filling", "superfilling", "改善", "填充", "整平", "leveler"],
    # v2 schema predicates (unified gold evaluation): role and interface relations
    "used_as_leveler": ["leveler", "整平剂", "整平"],
    "used_as_suppressor": ["suppressor", "抑制剂", "缓聚"],
    "used_as_accelerator": ["accelerator", "加速剂"],
    "used_as_inhibitor": ["inhibitor", "缓蚀剂"],
    "adsorbs_on": ["adsorb", "吸附"],
}


def tokens(text: str) -> list[str]:
    out=[]
    for x in TOKEN_RE.findall((text or "").lower()):
        if "\u4e00" <= x[:1] <= "\u9fff":
            out.extend(w for w in zh_words(x) if w not in ZH_STOP)
        elif len(x) > 1 and x not in STOP:
            out.append(x)
    return out


def read_csv(path: Path) -> list[dict[str,str]]:
    if not path.exists(): return []
    with path.open(encoding="utf-8", newline="") as f: return list(csv.DictReader(f))


def sha(text: str) -> str: return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:16]


def build(args):
    kg=Path(args.kg); out=Path(args.out); out.mkdir(parents=True, exist_ok=True)
    docs={r["doc_id"]:r for r in read_csv(kg/"documents.csv")}
    evid=read_csv(kg/"evidence.csv")
    facts=read_csv(kg/"facts.csv")
    mentions=read_csv(kg/"mentions.csv")
    entities=read_csv(kg/"entities.csv")
    values=read_csv(kg/"values.csv")
    ent_by_ev=defaultdict(list); val_by_ev=defaultdict(list); fact_by_ev=defaultdict(list); fact_tag_by_ev=defaultdict(list)
    name_by_id={r.get("entity_id"):r.get("name","") for r in entities}
    for r in mentions: ent_by_ev[r.get("evidence_id")].append(r.get("text") or name_by_id.get(r.get("entity_id"),""))
    for r in values: val_by_ev[r.get("evidence_id")].append(f"{r.get('value','')} {r.get('unit','')}")
    # Unified v2 layer support: facts.csv may carry panel_decision (jury consensus)
    # and condition_text (structured condition slots). Panel status is stored as
    # per-row metadata (NOT index text — ablation showed text injection dilutes
    # BM25 signals); condition text stays in fact_tags where it belongs semantically.
    status_rank={"verified":3,"quarantine":2,"rejected":1}
    panel_by_ev=defaultdict(str)
    for r in facts:
        ev=r.get("evidence_id"); p=r.get("predicate","")
        fact_by_ev[ev].append(p)
        tag=p
        ct=(r.get("condition_text") or "").strip()
        if ct:
            tag=f"{tag}|{ct}"
        fact_tag_by_ev[ev].append(tag)
        pd=(r.get("panel_decision") or "").strip()
        if pd in status_rank and status_rank[pd]>status_rank.get(panel_by_ev.get(ev,""),0):
            panel_by_ev[ev]=pd
    rows=[]
    for e in evid:
        text=e.get("text",""); doc=docs.get(e.get("doc_id"),{})
        enriched=" ".join([text]+ent_by_ev[e.get("evidence_id")]+val_by_ev[e.get("evidence_id")]+fact_tag_by_ev[e.get("evidence_id")])
        rows.append({"evidence_id":e.get("evidence_id"),"doc_id":e.get("doc_id"),"title":doc.get("title",""),"path":doc.get("path",""),"line_no":int(e.get("line_no") or 0),"text":text,"entities":ent_by_ev[e.get("evidence_id")],"values":val_by_ev[e.get("evidence_id")],"predicates":fact_by_ev[e.get("evidence_id")],"fact_tags":fact_tag_by_ev[e.get("evidence_id")],"panel_status":panel_by_ev.get(e.get("evidence_id"),""),"tokens":tokens(enriched)})
    # Inverted index and document-frequency weights make this portable without rank_bm25/faiss.
    df=Counter(); inv=defaultdict(list)
    for i,r in enumerate(rows):
        r["dl"] = len(r["tokens"])
        for t in set(r["tokens"]): df[t]+=1; inv[t].append(i)
    avgdl=sum(r["dl"] for r in rows)/max(1,len(rows))
    doc_rows=defaultdict(list)
    for i,r in enumerate(rows): doc_rows[r["doc_id"]].append(i)
    source_files={}
    for name in ("documents.csv", "evidence.csv", "facts.csv", "entities.csv", "mentions.csv", "values.csv"):
        p=kg/name
        if p.exists(): source_files[name]={"bytes":p.stat().st_size,"sha1":hashlib.sha1(p.read_bytes()).hexdigest()}
    corpus_blob=" ".join(r["text"].lower() for r in rows)
    payload={"version":3,"source_kg":str(kg.resolve()),"source_files":source_files,"rows":rows,"df":dict(df),"inv":{k:v for k,v in inv.items()},"N":len(rows),"avgdl":avgdl,"doc_rows":dict(doc_rows),"corpus_blob":corpus_blob}
    (out/"index.json").write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
    n_status=sum(1 for r in rows if r.get("panel_status"))
    print(json.dumps({"evidence":len(rows),"documents":len(docs),"facts":len(facts),"entities":len(entities),"evidence_with_panel_status":n_status,"out":str(out)},ensure_ascii=False,indent=2))


def load_index(path: Path): return json.loads((path/"index.json").read_text(encoding="utf-8"))


def query_terms(q):
    ts=tokens(q); return ts, set(ts)


def unknown_entity_guard(index, question, qset):
    """Return True for an explicit entity-like query with no corpus support.

    Abstains only when: (a) a yes/no question asks about an unknown MATERIAL NAME
    (Latin/short zh token that never appears in the index vocabulary), or (b) the
    query contains Latin chemical-looking tokens none of which are known, or
    (c) an existence probe names a Chinese compound token (compound-suffix char
    or non-domain metal) absent from the KG entity vocabulary.
    Question boilerplate phrases must not trigger abstention.
    """
    df = index.get("df", {})
    latin=[x for x in re.findall(r"[A-Za-z][A-Za-z0-9+./-]*", question) if len(x)>=3]
    known_latin=[x.lower() for x in latin if x.lower() in df]
    unknown_latin=[x.lower() for x in latin if x.lower() not in df]
    known=sum(1 for x in qset if x in df)
    # Material questions: if the query names a specific Latin material token that is
    # entirely unknown AND no Latin token is known, the entity is unrecognizable.
    if latin and not known_latin:
        return True
    # Only known Chinese boilerplate terms, no discriminative content
    if known==0:
        return True
    # Chinese material probe: existence-pattern question naming a compound token
    # (ammonium/sugar/boron/… suffix or non-domain metal) absent from the KG
    # entity vocabulary → the material is outside this corpus, abstain.
    # Only the question core is examined — embedded evidence excerpts (clue
    # suffixes) are corpus text, not user intent.
    core = question.split("证据线索")[0]
    if re.search(r"(是否|有没有|证明|报道|表明|数据)", core):
        vocab=set()
        for r in index.get("rows", []):
            for e in (r.get("entities") or []):
                if e: vocab.add(e.lower())
        toks=[t for t in jieba.lcut(core) if len(t)>=2]
        chem=set("铵糖硼烯酮胺醇")
        metals=set("钯铂银锌锂铝铁锡锰镁钛汞铅")
        mats=[t for t in toks if (t[-1] in chem) or any(c in metals for c in t)]
        if mats and not any(any(m.lower() in v or v in m.lower() or m in df for v in vocab) for m in mats):
            return True
    return False


PRED_TERM_HINTS={
    "inhibits_deposition": ["inhibit","suppress","inhibitor","抑制","阻碍"],
    "accelerates_deposition": ["accelerat","加速","催化","accelerator"],
    "synergizes_with": ["synerg","协同"],
    "improves_filling": ["improve","fill","enhanc","填充","改善"],
    # v2 schema predicates (unified gold evaluation)
    "used_as_leveler": ["leveler","整平","整平剂"],
    "used_as_suppressor": ["suppressor","抑制剂","缓聚"],
    "used_as_accelerator": ["accelerator","加速剂"],
    "used_as_inhibitor": ["inhibitor","缓蚀剂"],
    "adsorbs_on": ["adsorb","吸附"],
}

# Panel-status soft re-weight modes (unified v2 indexes carry per-row panel_status
# from the five-model jury). "trust" promotes verified evidence for factual QA;
# "refute" promotes rejected evidence when hunting refuting evidence for a claim
# (adversarial probes — the gold evidence there IS the rejected one).
PANEL_MULT={"trust":{"verified":1.10,"quarantine":1.0,"rejected":0.90},
            "refute":{"verified":0.90,"quarantine":1.0,"rejected":1.15}}

def retrieve(index, question, topk=8, window=1, predicate=None, doc_id=None, kg_boost=True, graph_expand_enabled=False, subject_anchor=None, predicate_hint=None, pool=80, mult_subject=2.5, mult_predicate=1.35, panel_mode="off"):
    rows=index["rows"]; df=index["df"]; N=max(1,index["N"]); avgdl=index.get("avgdl",1.0); qts,qset=query_terms(question)
    if not qset or unknown_entity_guard(index, question, qset): return []
    scores=defaultdict(float); matched=defaultdict(set)
    for t in qset:
        for i in index["inv"].get(t,[]):
            r=rows[i]; tf=r["tokens"].count(t); idf=math.log((N+1)/(df.get(t,0)+1))+1
            # BM25 term contribution; this is more stable than raw TF-IDF for long evidence lines.
            k1,b=1.2,0.75
            norm=tf*(k1+1)/(tf+k1*(1-b+b*max(1,r.get("dl",1))/max(1,avgdl)))
            scores[i] += norm*idf; matched[i].add(t)
    # Domain/entity/relation-aware boosts; exact chemical abbreviations and relation words matter.
    for i,s in list(scores.items()):
        r=rows[i]; text=(r["text"]+" "+" ".join(r["entities"])).lower()
        if doc_id and r.get("doc_id") != doc_id: scores[i] = -1; continue
        if predicate and predicate not in r.get("predicates", []): scores[i] = -1; continue
        overlap=len(matched[i])/max(1,len(qset)); scores[i] *= 0.65+0.35*overlap
        entity_terms=[x.lower() for x in re.findall(r"[A-Za-z][A-Za-z0-9+./-]*", question) if len(x)>1]
        if any(x in text for x in entity_terms): scores[i] += 0.35
        for w,p in REL_WORDS.items():
            if w in question.lower() and p in r["predicates"]: scores[i]+=0.5
        if kg_boost:
            for p, aliases in REL_ALIASES.items():
                if any(a in question.lower() for a in aliases) and p in r["predicates"]: scores[i] += 1.0
    ranked=sorted((i for i in scores if scores[i] >= 0),key=lambda i:scores[i],reverse=True)
    selected=[]; seen=set()
    for i in ranked:
        r=rows[i]; key=(r["doc_id"],r["line_no"])
        if key in seen: continue
        seen.add(key); selected.append({**r,"score":round(scores[i],6),"matched_terms":sorted(matched[i])})
        if len(selected)>=max(pool, topk): break
    # Subject-anchored re-scoring: evidence that literally contains the subject material
    # (e.g. the additive abbreviation) is far more likely to carry the queried relation.
    if subject_anchor or predicate_hint:
        subs=[x.lower() for x in re.findall(r"[A-Za-z][A-Za-z0-9+./-]{1,}", subject_anchor or '')]
        zh_sub=[x for x in re.findall(r"[\u4e00-\u9fff]{2,6}", subject_anchor or '')]
        pterms=PRED_TERM_HINTS.get(predicate_hint or "", [])
        def anchor_score(h):
            s=h["score"]; t=h["text"].lower()
            if subs and any(x in t for x in subs): s*=mult_subject
            if zh_sub and any(x in t for x in zh_sub): s*=mult_subject
            if pterms and any(p in t for p in pterms): s*=mult_predicate
            return s
        for h in selected: h["_final"]=anchor_score(h)
        selected.sort(key=lambda h:h["_final"],reverse=True)
    else:
        for h in selected: h["_final"]=h["score"]
    # Panel-status soft re-weight (unified v2 indexes carry per-row panel_status;
    # legacy indexes have none and are unaffected). Modes: off / trust / refute.
    if panel_mode in PANEL_MULT and any(h.get("panel_status") for h in selected):
        mult=PANEL_MULT[panel_mode]
        for h in selected:
            if h.get("panel_status"): h["_final"]*=mult.get(h["panel_status"],1.0)
        selected.sort(key=lambda h:h["_final"],reverse=True)
    selected=selected[:topk]
    for h in selected:
        h["final_score"]=round(h.pop("_final",h["score"]),6)
    # Add adjacent evidence lines from the same document when available; do not score them as independent hits.
    for r in selected:
        neighbors=[]
        for ni in index.get("doc_rows", {}).get(r["doc_id"], []):
            x=rows[ni]
            if abs(x["line_no"]-r["line_no"])<=window and x["evidence_id"]!=r["evidence_id"]: neighbors.append(x)
        r["neighbors"]=[{"evidence_id":x["evidence_id"],"line_no":x["line_no"],"text":x["text"]} for x in sorted(neighbors,key=lambda z:z["line_no"])]
    if graph_expand_enabled and selected:
        selected=graph_expand(rows, selected, question, limit=max(topk*3, topk))[:topk]
    return selected


def extractive_answer(question, hits):
    if not hits or hits[0].get("score", 0) < 1.0: return "当前知识库没有检索到足够的证据，暂不作答。"
    lines=["基于当前知识库检索到的证据，相关信息如下："]
    for i,h in enumerate(hits,1):
        lines.append(f"{i}. {h['text']}（{h['title']}，evidence_id={h['evidence_id']}）")
    lines.append("\n说明：以上为证据摘录；候选事实尚未自动等同于已验证科学结论，请结合实验条件和原文核对。")
    return "\n".join(lines)


def llm_answer(question,hits):
    # Optional OpenAI-compatible endpoint. Keep retrieval usable without credentials.
    key=os.environ.get("OPENAI_API_KEY")
    base=os.environ.get("OPENAI_BASE_URL")
    model=os.environ.get("RAG_LLM_MODEL")
    if not (key and base and model): return extractive_answer(question,hits)
    try:
        import urllib.request
        context="\n".join(f"[{h['evidence_id']}] {h['text']} ({h['title']})" for h in hits)
        body=json.dumps({"model":model,"temperature":0,"messages":[{"role":"system","content":"你是电镀科研文献助手。只根据给定证据回答；不能由证据推出的内容明确说证据不足；保留温度、电流密度、浓度等条件；每个主要结论引用 evidence_id。"},{"role":"user","content":f"问题：{question}\n证据：\n{context}"}],"max_tokens":1200},ensure_ascii=False).encode()
        req=urllib.request.Request(base.rstrip("/")+"/chat/completions",data=body,headers={"Content-Type":"application/json","Authorization":"Bearer "+key})
        with urllib.request.urlopen(req,timeout=120) as resp: data=json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return extractive_answer(question,hits)+f"\n\n[LLM fallback: {type(e).__name__}]"


def ask(args):
    index=load_index(Path(args.index)); hits=retrieve(index,args.question,args.topk,args.window)
    answer=llm_answer(args.question,hits)
    result={"question":args.question,"answer":answer,"evidence":hits}
    print(json.dumps(result,ensure_ascii=False,indent=2) if args.json else answer)


def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    b=sub.add_parser("build"); b.add_argument("--kg",default="kg_data"); b.add_argument("--docs",default="文献提取"); b.add_argument("--out",default="rag_index"); b.set_defaults(func=build)
    a=sub.add_parser("ask"); a.add_argument("--index",default="rag_index"); a.add_argument("--question",required=True); a.add_argument("--topk",type=int,default=8); a.add_argument("--window",type=int,default=1); a.add_argument("--json",action="store_true"); a.set_defaults(func=ask)
    args=ap.parse_args(); args.func(args)
if __name__=="__main__": main()
