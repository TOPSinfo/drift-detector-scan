"""drift-eval CLI: `run <category>`. Exit code comes from the recall gate."""
from __future__ import annotations

import argparse
import os
import sys

from agent.eval import runner
from agent.eval.render import render_scorecard


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="drift-eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run")
    pr.add_argument("category")
    pr.add_argument("--now", default=None)
    pr.add_argument("--sandbox", default=os.path.expanduser("~/Projects/sandbox"))
    pr.add_argument("--corpus", default="eval/corpus.yaml")
    pr.add_argument("--no-clone", action="store_true")
    args = ap.parse_args(argv)

    now = args.now or "1970-01-01"       # caller should pass --now; fixed default keeps it deterministic
    sc = runner.run_category(args.category, now=now, sandbox_root=args.sandbox,
                             corpus_path=args.corpus, no_clone=args.no_clone)
    sys.stdout.write(render_scorecard(sc))
    return 0 if sc["gate"]["passed"] else 1


if __name__ == "__main__":                # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
