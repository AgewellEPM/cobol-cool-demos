"""DGM re-validation — re-score archived genomes on a held-out / larger window.

The evolution loop optimizes on a small task window, so a champion's headline
CSR can be window-overfit. This tool re-scores any archived genome(s) on a
DIFFERENT task range (held-out) or the full 146, head-to-head, so an
improvement claim is only made when it survives unseen tasks.

    python -m dgm.revalidate --ids g000-... g003-... --offset 15 --tasks 25
    python -m dgm.revalidate --champion --seed --offset 15 --tasks 25
    python -m dgm.revalidate --champion --seed --full          # all 146

Honest by construction: prints per-genome CSR/pass@1 on the chosen window and
the delta, and names the window so a subset score is never mistaken for truth.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .archive import Archive
from .evaluate import TASKS_FILE, evaluate
from .loop import DEFAULT_DB, _preflight


def _total_tasks() -> int:
    return len(TASKS_FILE.read_text().splitlines())


def main() -> None:
    ap = argparse.ArgumentParser(description="re-score archived genomes on a held-out window")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--ids", nargs="*", default=[], help="explicit genome ids")
    ap.add_argument("--champion", action="store_true", help="include the archive champion")
    ap.add_argument("--seed", action="store_true", help="include genome-zero (generation 0)")
    ap.add_argument("--offset", type=int, default=15, help="held-out window start (default 15)")
    ap.add_argument("--tasks", type=int, default=25)
    ap.add_argument("--full", action="store_true", help="score all 146 tasks (overrides offset/tasks)")
    ap.add_argument("--gen-timeout", type=int, default=300)
    args = ap.parse_args()

    arc = Archive(args.db)
    ids = list(args.ids)
    if args.seed:
        row = arc.con.execute("SELECT genome_id FROM agents WHERE generation=0 ORDER BY seq LIMIT 1").fetchone()
        if row:
            ids.insert(0, row["genome_id"])
    if args.champion:
        ids.append(arc.best()["genome_id"])
    # de-dup, preserve order
    seen, ordered = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i); ordered.append(i)
    if not ordered:
        raise SystemExit("nothing to re-validate — pass --ids / --seed / --champion")

    offset, n = (0, _total_tasks()) if args.full else (args.offset, args.tasks)
    window = f"tasks[{offset}:{offset + n}]" + (" (FULL 146)" if args.full else " (held-out)")
    _preflight("")
    print(f"re-validating {len(ordered)} genome(s) on {window}\n")

    results = []
    for gid in ordered:
        g = arc.get_genome(gid)
        print(f"[{gid}] gen={g.generation} origin={g.origin} — evaluating {n} tasks ...", flush=True)
        fit = evaluate(g, n, offset=offset, gen_timeout=args.gen_timeout)
        results.append((gid, g.generation, fit))
        print(f"[{gid}] CSR={fit.csr}  pass@1={fit.pass_at_1}  no-code={fit.no_code}\n", flush=True)

    print("=" * 64)
    print(f"HELD-OUT RE-VALIDATION — {window}")
    base = results[0][2].csr
    for gid, gen, fit in results:
        d = fit.csr - base
        tag = "  (baseline)" if fit is results[0][2] else f"  ({d:+.3f} vs first)"
        print(f"  gen{gen} {gid[:22]}  CSR {fit.csr:<7} pass@1 {fit.pass_at_1:<7}{tag}")
    print("=" * 64)
    arc.close()


if __name__ == "__main__":
    main()
