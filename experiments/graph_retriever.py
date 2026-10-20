#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline KG-aware candidate expansion from CSV edges.

The current KG CSV facts are conservative relation-bearing evidence records, not
fully normalized subject/object edges. This module therefore expands matching
Evidence by predicate and shared document/entity signals without pretending to
infer unsupported graph paths. It is safe to use before Neo4j path integration.
"""
from __future__ import annotations
from collections import defaultdict

def build_graph(rows):
    by_doc=defaultdict(list); by_pred=defaultdict(list); by_entity=defaultdict(list)
    for r in rows:
        by_doc[r.get('doc_id')].append(r)
        for p in r.get('predicates',[]): by_pred[p].append(r)
        for e in r.get('entities',[]): by_entity[e.lower()].append(r)
    return {'by_doc':by_doc,'by_pred':by_pred,'by_entity':by_entity}

def expand(rows, hits, question, limit=20):
    g=build_graph(rows); out=list(hits); seen={x.get('evidence_id') for x in out}; q=question.lower()
    for p, items in g['by_pred'].items():
        if p.replace('_',' ') in q or any(a in q for a in p.split('_')):
            for x in items:
                if x.get('evidence_id') not in seen: out.append({**x,'graph_expansion':True}); seen.add(x.get('evidence_id'))
                if len(out)>=limit:return out
    for h in hits:
        for ent in h.get('entities',[]):
            for x in g['by_entity'].get(ent.lower(),[]):
                if x.get('evidence_id') not in seen: out.append({**x,'graph_expansion':True});seen.add(x.get('evidence_id'))
                if len(out)>=limit:return out
    return out
