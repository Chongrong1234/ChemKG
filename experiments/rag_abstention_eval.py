#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from rag_system import load_index,retrieve

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--index',default='rag_index');ap.add_argument('--gold',default='evaluation/auto_entity_silver.jsonl');ap.add_argument('--k',type=int,default=5);a=ap.parse_args();idx=load_index(Path(a.index));items=[json.loads(x) for x in Path(a.gold).read_text(encoding='utf-8').splitlines() if x.strip()];neg=[x for x in items if x.get('answerable') is False];tp=fp=0
 for x in neg:
  hits=retrieve(idx,x['question'],a.k,1); fp+=bool(hits)
 print(json.dumps({'negative_items':len(neg),'false_retrieval_rate':fp/len(neg) if neg else None,'note':'retrieval presence is not equivalent to answerability; final abstention needs evidence sufficiency and human gold'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
