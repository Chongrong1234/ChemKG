"""命令行入口：索引构建与命令行问答.

用法::

    python -m kgrag.cli build --kg ../kg_data --out ../rag_index
    python -m kgrag.cli ask --question "PVP 在钴电沉积中起什么作用？"
    python -m kgrag.cli ask --question "..." --strategy anchored --subject PVP --topk 5
    python -m kgrag.cli serve --port 8600
"""

from __future__ import annotations

import argparse
import json

from kgrag.config import get_settings


def cmd_build(args: argparse.Namespace) -> None:
    from kgrag.index.builder import build_index

    stats = build_index(args.kg, args.out)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def cmd_ask(args: argparse.Namespace) -> None:
    from kgrag.service import QAService

    svc = QAService.from_settings()
    result = svc.ask(args.question, strategy=args.strategy, topk=args.topk,
                     window=args.window, subject=args.subject,
                     predicate_hint=args.predicate_hint)
    if args.json:
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, default=str))
    else:
        print(result.answer)
        print(f"\n[策略={result.strategy} 检索={result.retrieval_ms:.0f}ms "
              f"生成={result.generation_ms:.0f}ms 命中={len(result.evidence)}条 "
              f"弃答={result.abstained}]")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from kgrag.api.app import app

    settings = get_settings()
    uvicorn.run(app, host=args.host or settings.host, port=args.port or settings.port,
                log_level=settings.log_level.lower())


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="kgrag", description="KG+RAG 问答系统")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="构建 BM25 索引")
    b.add_argument("--kg", default="../kg_data")
    b.add_argument("--out", default=str(settings.index_dir))
    b.set_defaults(func=cmd_build)

    a = sub.add_parser("ask", help="命令行问答")
    a.add_argument("--question", required=True)
    a.add_argument("--strategy", default="kg", choices=["lexical", "kg", "anchored", "graph"])
    a.add_argument("--topk", type=int, default=settings.topk)
    a.add_argument("--window", type=int, default=settings.window)
    a.add_argument("--subject", default=None)
    a.add_argument("--predicate-hint", default=None)
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_ask)

    s = sub.add_parser("serve", help="启动 Web 服务")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    s.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
