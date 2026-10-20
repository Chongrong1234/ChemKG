#!/usr/bin/env python3
"""Strict evidence-first electroplating extraction baseline; optional LLM hook metadata."""
from __future__ import annotations
import argparse,json,re,hashlib,os
from pathlib import Path
from collections import Counter
DOMAIN=re.compile(r"electroplating|electrodeposition|electro-deposition|plating bath|copper plating|cobalt plating|micro.?via|blind.?via|through.?hole|via fill|via filling|填充|电镀|电沉积|通孔|盲孔|镀铜|镀钴",re.I)
NON_DOMAIN=re.compile(r"catalys|cross.?coupling|nanocatal|photocatal|cvd|chemical vapor deposition|cmp|chemical mechanical polishing|microwave absorption|organic transformation|腐蚀|催化",re.I)
REF=re.compile(r"doi\s*:|doi\.org|https?://|references?$|^\s*\[?\d{1,3}\]?\s+[^ ]+\s+et al\.?",re.I)
PATTERNS=[('Additive',r"\b(?:CMHT|PEP|SPS|JGB|PVP|PEG|DMG|ZPS|ADO|MPS|MG|DB)\b"),('Chemical',r"\b(?:CuSO4(?:·5H2O)?|H2SO4|CoSO4|Cu\(II\)|Co\(II\)|Cl[-−]|chloride|sulfuric acid|copper sulfate|硫酸铜|硫酸|氯离子)\b"),('Method',r"\b(?:CV|EIS|GM|chronoamperometry|cyclic voltammetry|electrochemical impedance spectroscopy)\b|循环伏安|电化学阻抗|计时安培"),('Process',r"\b(?:copper|cobalt)\s+(?:electroplating|electrodeposition)|electroplating|electrodeposition|micro.?via|blind.?via|through.?hole|via filling|电镀|电沉积|盲孔|通孔|填充"),('Property',r"\b(?:filling performance|surface copper|overpotential|polarization|deposition rate|void(?:s)?|seam|throwing power|hardness|conductivity)\b|填充性能|表面铜|过电位|极化|沉积速率|空洞|接缝|硬度|导电性")]
NUM=re.compile(r"(?P<value>[−-]?\d+(?:\.\d+)?)\s*(?P<unit>mg\s*/\s*[Ll]|g\s*/\s*[Ll]|A\s*/\s*dm(?:\^?2|²)|A\s*/\s*cm(?:\^?2|²)|mV|V|K|°\s*C|°C|μm|µm|um|nm|rpm|min(?:ute)?s?|h(?:ours?)?|%|Ω\s*cm(?:\^?2|²))",re.I)
def hid(x): return hashlib.sha1(x.encode('utf-8','ignore')).hexdigest()[:16]
def unit(u):
 u=re.sub(r'\s+','',u).replace('µ','μ').replace('²','2').lower(); return {'mg/l':'mg/L','g/l':'g/L','a/dm2':'A/dm²','a/cm2':'A/cm²','mv':'mV','v':'V','k':'K','°c':'°C','c':'°C','μm':'μm','um':'μm','nm':'nm','rpm':'rpm','min':'min','minutes':'min','h':'h','hours':'h','%':'%','ωcm2':'Ω·cm²'}.get(u,u)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--input',default='文献提取'); ap.add_argument('--out',default='strict_extraction'); a=ap.parse_args(); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
 docs=[]; evs=[]; ents=[]; mentions=[]; vals=[]; rels=[]
 for p in sorted(Path(a.input).rglob('full.md')):
  text=p.read_text(encoding='utf-8',errors='ignore'); did='doc_'+hid(str(p.resolve())); docs.append({'doc_id':did,'path':str(p),'title':next((x[2:].strip() for x in text.splitlines() if x.startswith('# ')),p.parent.name)})
  ref=False
  for ln,line in enumerate(text.splitlines(),1):
   if re.match(r'^#{1,3}\s*(references|参考文献)',line,re.I): ref=True
   if ref or len(line.strip())<20 or not DOMAIN.search(line) or (NON_DOMAIN.search(line) and not re.search(r'electropl|electrodepos|via|电镀|电沉积|填充',line,re.I)) or REF.search(line): continue
   eid='ev_'+hid(f'{did}:{ln}:{line}'); evs.append({'evidence_id':eid,'doc_id':did,'line_no':ln,'text':line[:4000],'review_status':'unreviewed'})
   local=[]
   for typ,pat in PATTERNS:
    for m in re.finditer(pat,line,re.I):
     n=m.group(0).strip(); x={'entity_id':'ent_'+hid(typ+':'+n.casefold()),'name':n,'type':typ,'normalized_name':re.sub(r'\s+',' ',n.casefold()).strip(),'status':'candidate'}; local.append(x)
   local=list({x['entity_id']:x for x in local}.values()); ents.extend(local)
   for x in local: mentions.append({'mention_id':'men_'+hid(eid+x['entity_id']),'entity_id':x['entity_id'],'evidence_id':eid,'doc_id':did,'text':x['name'],'line_no':ln})
   for m in NUM.finditer(line): vals.append({'value_id':'val_'+hid(eid+m.group(0)),'evidence_id':eid,'doc_id':did,'value':m.group('value').replace('−','-'),'unit':unit(m.group('unit')),'raw_text':m.group(0),'status':'candidate'})
   clauses=re.split(r'(?<=[.!?。！？;；])\s+',line)
   for c in clauses:
    if not DOMAIN.search(c) or NON_DOMAIN.search(c): continue
    aents=[x for x in local if x['type'] in ('Additive','Chemical') and re.search(r'\b'+re.escape(x['name'])+r'\b',c,re.I)]; oents=[x for x in local if x not in aents and x['type'] in ('Process','Property','Chemical','Additive')]
    pred=None
    if re.search(r'\b(?:synergizes?|synergistic(?:ally)?|work(?:s)? synergistically)\b|协同',c,re.I) and len(aents)>=2: pred='synergizes_with'; pairs=[(aents[0],aents[1])]
    elif re.search(r'\b(?:inhibits?|inhibited|inhibiting|suppresses?|suppressed|suppressing)\b|抑制',c,re.I) and re.search(r'deposit|plating|electroplat|电沉积|镀',c,re.I): pred='inhibits_deposition'; pairs=[(aents[0],oents[0])] if aents and oents else []
    elif re.search(r'\b(?:accelerates?|accelerated|accelerating|enhances?|enhanced|enhancing)\b|加速',c,re.I) and re.search(r'deposit|plating|electroplat|电沉积|镀',c,re.I): pred='accelerates_deposition'; pairs=[(aents[0],oents[0])] if aents and oents else []
    elif re.search(r'\b(?:improves?|improved|improving|enhances?|enhanced)\b|excellent filling|void.?free|填充|改善',c,re.I) and re.search(r'fill|via|hole|孔',c,re.I): pred='improves_filling'; pairs=[(aents[0],oents[0])] if aents and oents else []
    else: pairs=[]
    for s,o in pairs: rels.append({'fact_id':'fact_'+hid(eid+pred+s['entity_id']+o['entity_id']),'subject_id':s['entity_id'],'predicate':pred,'object_id':o['entity_id'],'evidence_id':eid,'doc_id':did,'surface_text':c[:4000],'status':'candidate','needs_review':True})
 docs=docs; ents=list({x['entity_id']:x for x in ents}.values()); vals=list({x['value_id']:x for x in vals}.values()); rels=list({x['fact_id']:x for x in rels}.values())
 for n,data in [('documents',docs),('evidence',evs),('entities',ents),('mentions',mentions),('values',vals),('relations',rels)]:
  with (out/(n+'.jsonl')).open('w',encoding='utf-8') as f:
   for x in data:f.write(json.dumps(x,ensure_ascii=False)+'\n')
 summary={'documents':len(docs),'evidence':len(evs),'entities':len(ents),'mentions':len(mentions),'values':len(vals),'relations':len(rels),'relation_types':dict(Counter(x['predicate'] for x in rels)),'llm_enabled':bool(os.getenv('KG_LLM_BASE_URL')),'filter':'strict domain + contamination/reference exclusion + clause-local subject/object'}; (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)); print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
