#!/usr/bin/env python3
"""Build a provenance-first electroplating KG from extracted full.md files.

Usage:
  python kg_pipeline/build_kg.py --input 文献提取 --out kg_data
  python kg_pipeline/build_kg.py --input 文献提取 --neo4j-uri bolt://localhost:7687 --neo4j-user neo4j --neo4j-password password

The extractor is deliberately conservative: it creates CandidateFact records and
never presents regex/LLM-like matches as verified scientific facts.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re
from pathlib import Path
from typing import Iterable

KEYWORDS = {
    "copper", "铜", "cobalt", "钴", "electroplating", "electrodeposition", "电镀",
    "microvia", "blind via", "through-hole", "通孔", "盲孔", "additive", "添加剂",
    "inhibitor", "抑制剂", "suppressor", "accelerator", "leveler", "整平剂",
    "filling", "填充", "CV", "EIS", "chronoamperometry", "current density", "电流密度",
}
ENTITY_PATTERNS = {
    "Chemical": re.compile(r"\b(?:CMHT|PEP|SPS|JGB|PVP|PEG|CuSO4(?:·5H2O)?|H2SO4|Cl[-−]|DMG)\b|铜|钴|氯离子|硫酸铜", re.I),
    "Process": re.compile(r"electroplating|electrodeposition|电镀|填充|filling|deposition", re.I),
    "Method": re.compile(r"CV|EIS|GM|chronoamperometry|cyclic voltammetry|阻抗|伏安", re.I),
    "Property": re.compile(r"filling performance|surface copper|overpotential|polarization|hardness|conductivity|填充性能|表面铜|过电位|极化", re.I),
}
NUMBER_UNIT = re.compile(r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>mg/L|g/L|A/dm\s*2|A/cm\s*2|mV|V|K|°C|μm|um|nm|rpm|min|h|%|Ω\s*cm2)", re.I)


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def iter_docs(root: Path) -> Iterable[Path]:
    yield from sorted(root.rglob("full.md"))


def title(text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else fallback


def relevant(text: str) -> bool:
    low = text.lower()
    return sum(1 for x in KEYWORDS if x.lower() in low) >= 2


def add_row(rows, row):
    rows.append(row)


def extract(root: Path):
    docs, entities, mentions, evidence, facts, values = [], [], [], [], [], []
    ent_seen, val_seen = set(), set()
    for path in iter_docs(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not relevant(text):
            continue
        doc_id = "doc_" + sha1(str(path.resolve()))[:16]
        docs.append({"doc_id": doc_id, "path": str(path), "title": title(text, path.parent.name), "sha1": sha1(text), "char_count": len(text)})
        for line_no, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            ev_id = "ev_" + sha1(f"{doc_id}:{line_no}:{line}")[:16]
            # Evidence must exist before mentions/values/facts reference it. Keep
            # only lines likely to contain domain evidence, but include lines
            # matched by entity/value/relation patterns even without a keyword.
            evidence_candidate = (
                any(k.lower() in line.lower() for k in KEYWORDS)
                or any(p.search(line) for p in ENTITY_PATTERNS.values())
                or bool(NUMBER_UNIT.search(line))
                or any(x in line.lower() for x in ["synerg", "inhibit", "抑制", "accelerat", "加速", "improv", "改善"])
            )
            if evidence_candidate:
                evidence.append({"evidence_id": ev_id, "doc_id": doc_id, "line_no": line_no, "text": line[:4000], "review_status": "unreviewed"})
            for typ, pat in ENTITY_PATTERNS.items():
                for match in pat.finditer(line):
                    name = match.group(0).strip()
                    eid = "ent_" + sha1(f"{typ}:{name.lower()}")[:16]
                    if eid not in ent_seen:
                        entities.append({"entity_id": eid, "name": name, "entity_type": typ, "normalized_name": name.lower(), "review_status": "candidate"})
                        ent_seen.add(eid)
                    mentions.append({"mention_id": "men_" + sha1(f"{ev_id}:{match.start()}:{name}")[:16], "entity_id": eid, "doc_id": doc_id, "evidence_id": ev_id, "text": name, "line_no": line_no})
            for m in NUMBER_UNIT.finditer(line):
                value, unit = m.group("value"), re.sub(r"\s+", "", m.group("unit"))
                vid = "val_" + sha1(f"{doc_id}:{line_no}:{value}:{unit}")[:16]
                if vid not in val_seen:
                    values.append({"value_id": vid, "doc_id": doc_id, "evidence_id": ev_id, "value": value, "unit": unit, "raw_text": m.group(0), "review_status": "candidate"})
                    val_seen.add(vid)
            # Conservative candidate facts: only relation-like lines, with source evidence.
            relation = None
            low = line.lower()
            if any(x in low for x in ["synerg", "协同"]): relation = "synergizes_with"
            elif any(x in low for x in ["inhibit", "抑制"]): relation = "inhibits_deposition"
            elif any(x in low for x in ["accelerat", "加速"]): relation = "accelerates_deposition"
            elif any(x in low for x in ["improv", "excellent filling", "改善", "优异"]): relation = "improves_filling"
            if relation:
                facts.append({"fact_id": "fact_" + sha1(f"{doc_id}:{line_no}:{line}")[:16], "doc_id": doc_id, "evidence_id": ev_id, "predicate": relation, "surface_text": line[:4000], "status": "candidate", "needs_review": "true"})
    return docs, entities, mentions, evidence, facts, values


def write_tsv(out: Path, name: str, rows):
    out.mkdir(parents=True, exist_ok=True)
    if not rows: return
    with (out / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def cypher_import(uri, user, password, data_dir):
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as s:
        for q in [
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.doc_id IS UNIQUE",
            "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.entity_id IS UNIQUE",
            "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.evidence_id IS UNIQUE",
            "CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (n:CandidateFact) REQUIRE n.fact_id IS UNIQUE",
        ]: s.run(q)
        for name, label, key in [("documents","Document","doc_id"),("entities","Entity","entity_id"),("evidence","Evidence","evidence_id"),("facts","CandidateFact","fact_id")]:
            file_url = (data_dir / f"{name}.csv").resolve().as_uri()
            s.run(f"LOAD CSV WITH HEADERS FROM $url AS row MERGE (n:{label} {{{key}: row.{key}}}) SET n += row", url=file_url)
        s.run("LOAD CSV WITH HEADERS FROM $url AS row MATCH (m:Entity {entity_id: row.entity_id}), (e:Evidence {evidence_id: row.evidence_id}) MERGE (e)-[:MENTIONS]->(m)", url=(data_dir / "mentions.csv").resolve().as_uri())
        s.run("LOAD CSV WITH HEADERS FROM $url AS row MATCH (v:Value {value_id: row.value_id}), (e:Evidence {evidence_id: row.evidence_id}) MERGE (e)-[:REPORTS_VALUE]->(v)", url=(data_dir / "values.csv").resolve().as_uri())
        s.run("MATCH (f:CandidateFact),(d:Document) WHERE f.doc_id=d.doc_id MERGE (f)-[:EXTRACTED_FROM]->(d)")
        s.run("MATCH (f:CandidateFact),(e:Evidence) WHERE f.evidence_id=e.evidence_id MERGE (f)-[:SUPPORTED_BY]->(e)")
        s.run("MATCH (e:Evidence),(d:Document) WHERE e.doc_id=d.doc_id MERGE (e)-[:IN_DOCUMENT]->(d)")
    driver.close()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--input", default="文献提取"); ap.add_argument("--out", default="kg_data"); ap.add_argument("--neo4j-uri"); ap.add_argument("--neo4j-user", default="neo4j"); ap.add_argument("--neo4j-password")
    args = ap.parse_args(); rows = extract(Path(args.input)); names = ["documents","entities","mentions","evidence","facts","values"]
    for name, data in zip(names, rows): write_tsv(Path(args.out), name, data)
    print(json.dumps({n: len(d) for n,d in zip(names, rows)}, ensure_ascii=False, indent=2))
    if args.neo4j_uri:
        if not args.neo4j_password: raise SystemExit("--neo4j-password is required with --neo4j-uri")
        cypher_import(args.neo4j_uri, args.neo4j_user, args.neo4j_password, Path(args.out))

if __name__ == "__main__": main()
