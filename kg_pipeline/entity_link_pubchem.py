#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""entity_link_pubchem.py — 把 v2 实体表链接到 PubChem（CID/SMILES/InChIKey/同义词）。

优先级：领域标准名 > 中文全名 > 英文全名。每次查询带缓存与重试；
未命中（如领域内部缩写 CMHT/PEP/ZPS 等）诚实记为 unresolved，不编造。
输出：strict_extraction_v2/pubchem_links.jsonl
"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
from urllib.parse import quote
import requests

# 实体规范名 → 已知领域全称（查询顺序）
KNOWN = {
    'MG': ['malachite green', '孔雀石绿'],
    'NBT': ['nitro blue tetrazolium', 'chloride nitro tetrazolium blue'],
    'PVP': ['polyvinylpyrrolidone', 'povidone'],
    'saccharin': ['saccharin', 'benzoic sulfimide'],
    'CuSO4': ['copper(II) sulfate', 'copper sulfate'],
    'H2SO4': ['sulfuric acid'],
    'H3BO3': ['boric acid'],
    'NaCl': ['sodium chloride'],
    'Cl-': ['chloride ion', 'chloride'],
    'I-': ['iodide ion', 'iodide'],
    'Br-': ['bromide ion', 'bromide'],
    'PEG': ['polyethylene glycol', 'ethylene glycol homopolymer'],
    'SPS': ['bis(3-sulfopropyl) disulfide', '3,3\'-dithiodipropane-1-sulfonate'],
    'MPS': ['3-mercapto-1-propanesulfonic acid', 'sodium 3-mercapto-1-propanesulfonate'],
    'JGB': ['Janus green B', 'janus green'],
    'DMG': ['dimethylglyoxime'],
    'SA': ['sulfanilic acid', '4-aminobenzenesulfonic acid'],
    'DB': ['diamine black?'],
}
# 域内缩写，PubChem 大概率无条目，跳过以省调用
SKIP = {'CMHT', 'PEP', 'ZPS', 'VMS', 'CDT', 'AB1', 'ADO', 'PUB2', 'TPM', 'Cz-BPDB', 'AN-S1', 'DB'}


def lookup(term, cache):
    if term in cache:
        return cache[term]
    url = f'https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{quote(term)}/property/CanonicalSMILES,InChIKey,MolecularFormula/JSON'
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                props = r.json()['PropertyTable']['Properties'][0]
                res = {'cid': props.get('CID'), 'smiles': props.get('CanonicalSMILES'),
                       'inchikey': props.get('InChIKey'), 'formula': props.get('MolecularFormula')}
                cache[term] = res
                return res
            if r.status_code == 404:
                cache[term] = None
                return None
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    cache[term] = None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entities', default='strict_extraction_v2/entities.jsonl')
    ap.add_argument('--out', default='strict_extraction_v2/pubchem_links.jsonl')
    a = ap.parse_args()
    ents = [json.loads(x) for x in Path(a.entities).read_text(encoding='utf-8').splitlines() if x.strip()]
    chem = [e for e in ents if e['type'] in ('Additive', 'Chemical')]
    cache = {}
    out = []
    for e in chem:
        name = e['name']
        rec = {'entity_id': e['entity_id'], 'entity_name': name, 'entity_type': e['type'],
               'query_terms': [], 'pubchem': None, 'status': 'unresolved'}
        if name in SKIP:
            rec['status'] = 'domain_abbreviation_no_pubchem_entry'
            out.append(rec)
            continue
        for term in KNOWN.get(name, [name]):
            rec['query_terms'].append(term)
            hit = lookup(term, cache)
            if hit:
                rec['pubchem'] = hit
                rec['status'] = 'linked'
                rec['matched_term'] = term
                break
        out.append(rec)
        print(f"{name}: {rec['status']}" + (f" cid={rec['pubchem']['cid']}" if rec['pubchem'] else ''), flush=True)
    Path(a.out).write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in out) + '\n', encoding='utf-8')
    linked = sum(1 for x in out if x['status'] == 'linked')
    print(f'\nlinked {linked}/{len(out)} chemical/additive entities')


if __name__ == '__main__':
    main()
