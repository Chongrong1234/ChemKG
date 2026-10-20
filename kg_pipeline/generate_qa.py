#!/usr/bin/env python3
import argparse,json,os,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import requests
SYSTEM='''你是化学与电化学问答数据构建专家。根据给出的证据片段生成可由证据直接回答的问答，不要补充外部知识。优先生成基础化学/电化学/材料背景问题，也可生成电镀条件问题。每个问题必须带唯一evidence_id、答案、证据引用、难度。若证据不足不要生成。只输出JSON数组，每条含 question, answer, evidence_id, evidence_quote, category, difficulty。'''
def call(batch,base,key,model):
 prompt='证据片段：\n'+ '\n'.join(f"[{x['evidence_id']}] {x['text']}" for x in batch)
 body={'model':model,'temperature':0.2,'response_format':{'type':'json_object'},'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':prompt+'\n每个证据最多生成1个高质量问题。'}]}
 for i in range(3):
  try:
   r=requests.post(base.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=body,timeout=120);r.raise_for_status(); data=json.loads(r.json()['choices'][0]['message']['content']);
   if isinstance(data,dict): data=data.get('questions',data.get('items',[]))
   return data if isinstance(data,list) else []
  except Exception:
   if i==2:return []
   time.sleep(2**i)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--evidence',default='strict_extraction/evidence.jsonl');ap.add_argument('--out',default='qa_layer/qa.jsonl');ap.add_argument('--max-evidence',type=int,default=300);ap.add_argument('--batch',type=int,default=5);ap.add_argument('--workers',type=int,default=4);a=ap.parse_args()
 ev=[json.loads(x) for x in Path(a.evidence).read_text(encoding='utf-8').splitlines() if x.strip()]
 # prioritize chemistry/electrochemistry/process evidence, deterministic sample
 keys=('copper','cobalt','electropl','electrodepos','electrolyte','additive','inhibit','accelerat','filling','via','sulfate','chloride','concentration','current density','temperature','pH','CV','EIS')
 ev=[x for x in ev if any(k.lower() in x['text'].lower() for k in keys)][:a.max_evidence]
 batches=[ev[i:i+a.batch] for i in range(0,len(ev),a.batch)]; out=[]
 with ThreadPoolExecutor(max_workers=a.workers) as ex:
  fs=[ex.submit(call,b,os.environ['KG_LLM_BASE_URL'],os.environ['KG_LLM_API_KEY'],os.getenv('KG_LLM_MODEL','gpt-5.6-terra')) for b in batches]
  for f in as_completed(fs): out.extend(f.result())
 # validate and dedup
 seen=set(); clean=[]
 for q in out:
  if not all(q.get(k) for k in ['question','answer','evidence_id','evidence_quote']):continue
  if q['evidence_id'] not in {x['evidence_id'] for x in ev}:continue
  h=q['question'].strip().lower()
  if h in seen:continue
  seen.add(h);clean.append({**q,'qa_id':'qa_'+str(len(clean)+1).zfill(5),'source_dataset':'evidence_grounded_generated','status':'candidate','gold_status':'model_generated_needs_review'})
 p=Path(a.out);p.parent.mkdir(parents=True,exist_ok=True);p.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in clean)+'\n',encoding='utf-8')
 print(json.dumps({'evidence_used':len(ev),'batches':len(batches),'qa':len(clean)},ensure_ascii=False))
if __name__=='__main__':main()
