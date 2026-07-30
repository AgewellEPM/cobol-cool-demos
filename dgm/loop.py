"""cobol-dgm main loop — the Darwin Godel Machine, closed.

    seed the archive with genome-zero (proven baseline scaffold)
    repeat N times:
        parent  = archive.select_parent()          # open-ended, novelty-aware
        child   = mutate.propose(parent, failures)  # self-modify the scaffold
        fitness = evaluate(child)                    # REAL COBOLEval execution
        archive.add(child, fitness)                  # keep it, win or lose

Design commitments (all serve the core goal — a better OFFLINE COBOL model):
  * frozen local model + evolving scaffold (never touches weights)
  * every genome kept (stepping stones), champion tracked separately
  * resumable: archive is a sqlite file; re-running continues the search
  * honest: regressions are logged as regressions, not hidden

PROTOTYPE. Run: python -m dgm.loop --iterations 8 --tasks 12
"""
from __future__ import annotations

import argparse
import random
import sys
import time
import urllib.request
from pathlib import Path

from .archive import Archive
from .evaluate import COBOLEVAL, evaluate
from .genome import seed_genome
from . import mutate

DEFAULT_DB = Path(__file__).resolve().parent / "runs" / "archive.db"


def _preflight(model: str) -> None:
    """Fail fast, loudly, before burning time on a broken environment."""
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5).read()
    except Exception as e:
        sys.exit(f"FATAL: Ollama unreachable at localhost:11434 ({e}). Run: ollama serve")
    if not (COBOLEVAL / "data" / "CobolEval.jsonl").exists():
        sys.exit(f"FATAL: COBOLEval missing at {COBOLEVAL}")
    import shutil
    if shutil.which("cobc") is None:
        sys.exit("FATAL: cobc (GnuCOBOL) not on PATH — the repair gate needs it")


def _failures(fit) -> list[str]:
    """Task ids the genome could not compile — the mutation operator's signal."""
    return [tid for tid, v in fit.per_task.items() if not v["compiled"]]


def main() -> None:
    ap = argparse.ArgumentParser(description="Darwin Godel Machine for offline COBOL")
    ap.add_argument("--iterations", type=int, default=8)
    ap.add_argument("--tasks", type=int, default=12,
                    help="COBOLEval subset size per genome evaluation")
    ap.add_argument("--offset", type=int, default=0, help="task window start")
    ap.add_argument("--proposer", default="heuristic",
                    choices=["heuristic", "claude", "codex", "kist", "local"])
    ap.add_argument("--model", default="cobol-jeeves-ft")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--seed", type=int, default=1234, help="RNG seed (reproducible)")
    ap.add_argument("--gen-timeout", type=int, default=300)
    args = ap.parse_args()

    _preflight(args.model)
    rng = random.Random(args.seed)
    arc = Archive(args.db, rng=random.Random(args.seed + 1))

    # ---- seed genome-zero (only if this is a fresh archive) ----
    if arc.size() == 0:
        g0 = seed_genome()
        g0.model = args.model
        g0 = g0.with_id()
        print(f"[seed] evaluating genome-zero {g0.genome_id} on {args.tasks} tasks ...", flush=True)
        t0 = time.time()
        fit0 = evaluate(g0, args.tasks, offset=args.offset,
                        gen_timeout=args.gen_timeout, verbose=True)
        arc.add(g0, fit0)
        print(f"[seed] CSR={fit0.csr} pass@1={fit0.pass_at_1} "
              f"no-code={fit0.no_code} ({time.time()-t0:.0f}s)", flush=True)
    else:
        print(f"[resume] archive has {arc.size()} genome(s); continuing search", flush=True)

    # ---- evolve ----
    for it in range(1, args.iterations + 1):
        parent = arc.select_parent()
        parent_csr = arc.con.execute(
            "SELECT csr FROM agents WHERE genome_id=?", (parent.genome_id,)
        ).fetchone()["csr"]
        # The offline heuristic proposer ignores per-task failures; brain
        # proposers receive them via the parent scaffold. Keeping the signal
        # empty here keeps the default path zero-cost and fully offline.
        child = mutate.propose(parent, failures=[], proposer=args.proposer, rng=rng)

        if arc.has_fingerprint(child.fingerprint()):
            print(f"[iter {it}] {child.origin} produced a duplicate scaffold — skipping", flush=True)
            continue

        print(f"[iter {it}] parent {parent.genome_id} (CSR {parent_csr}) "
              f"--{child.origin}--> {child.genome_id}", flush=True)
        print(f"          {child.notes}", flush=True)
        t0 = time.time()
        try:
            fit = evaluate(child, args.tasks, offset=args.offset,
                           gen_timeout=args.gen_timeout)
        except Exception as e:
            print(f"[iter {it}] evaluation crashed ({e}) — child discarded", flush=True)
            continue
        arc.add(child, fit)

        delta = fit.csr - parent_csr
        verdict = "IMPROVED" if delta > 0 else ("regressed" if delta < 0 else "flat")
        print(f"[iter {it}] CSR={fit.csr} pass@1={fit.pass_at_1} "
              f"no-code={fit.no_code} ({verdict} {delta:+.3f}, {time.time()-t0:.0f}s)", flush=True)

    # ---- report ----
    best = arc.best()
    print("\n" + "=" * 64)
    print(f"archive: {arc.size()} genomes | champion: {best['genome_id']}")
    print(f"  CSR {best['csr']}  pass@1 {best['pass_at_1']}  "
          f"(gen {best['generation']}, origin {best['origin']})")
    print(f"  notes: {best['notes']}")
    print(f"  db: {args.db}")
    print("=" * 64)
    arc.close()


if __name__ == "__main__":
    main()
