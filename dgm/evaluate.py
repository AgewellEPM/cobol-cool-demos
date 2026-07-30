"""DGM fitness — score a Genome on a COBOLEval subset via real execution.

This is the objective the whole machine optimizes. No proxy: completions are
compiled and their tests are run by the COBOLEval harness (the same path
eval/run_local.py uses). Fitness = compile_all_tests_rate (primary) and
pass_at_1 (tiebreak). Sandboxed by the harness (temp dirs, per-task cobc).

Kept deliberately small — one job: genome in, measured score out.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .genome import Genome
from .solver import solve_task

HERE = Path(__file__).resolve().parent
COBOLEVAL = HERE.parent / "eval" / "COBOLEval"
TASKS_FILE = COBOLEVAL / "data" / "CobolEval.jsonl"


@dataclass
class Fitness:
    genome_id: str
    n_tasks: int
    csr: float          # compile_all_tests_rate — primary objective
    pass_at_1: float    # tiebreak
    per_task: dict      # task_id -> {"compiled": bool, "all_passed": bool}
    no_code: int        # tasks where the genome emitted nothing compilable

    def key(self) -> tuple:
        """Sort key: higher CSR, then higher pass@1, then fewer no-code."""
        return (self.csr, self.pass_at_1, -self.no_code)


def _load_tasks(n: int, offset: int = 0):
    lines = TASKS_FILE.read_text().splitlines()
    return [json.loads(l) for l in lines[offset:offset + n]]


def evaluate(g: Genome, n_tasks: int, *, offset: int = 0,
             gen_timeout: int = 300, verbose: bool = False) -> Fitness:
    """Generate + score `n_tasks` COBOLEval problems for genome `g`."""
    if not TASKS_FILE.exists():
        sys.exit(f"FATAL: COBOLEval tasks missing at {TASKS_FILE}")

    tasks = _load_tasks(n_tasks, offset)
    pred_dir = COBOLEVAL / "preds" / f"dgm_{g.genome_id}"
    pred_dir.mkdir(parents=True, exist_ok=True)
    samples = pred_dir / "samples.jsonl"

    with samples.open("w") as out:
        for i, t in enumerate(tasks):
            try:
                completion = solve_task(g, t["prompt"], gen_timeout)
            except Exception as e:  # fail the task, not the whole evaluation
                completion = ""
                if verbose:
                    print(f"  [{i+1}/{len(tasks)}] {t['task_id']} GEN-ERROR: {e}", flush=True)
            out.write(json.dumps({
                "sample_id": 0, "task_id": t["task_id"], "completion": completion,
            }) + "\n")
            if verbose:
                print(f"  [{i+1}/{len(tasks)}] {t['task_id']} "
                      f"{'ok' if completion else 'NO-CODE'}", flush=True)

    return _score(g.genome_id, pred_dir)


def _score(genome_id: str, pred_dir: Path) -> Fitness:
    """Run the COBOLEval execution harness and read back per-task verdicts."""
    sys.path.insert(0, str(COBOLEVAL / "scripts"))
    cwd = os.getcwd()
    os.chdir(COBOLEVAL)  # harness writes result files relative to cwd
    try:
        from evaluation import evaluate_functional_correctness
        evaluate_functional_correctness(
            str(pred_dir), k=[1], problem_file=str(TASKS_FILE)
        )
    finally:
        os.chdir(cwd)

    per_task, compiled, passed, no_code = {}, 0, 0, 0
    results_file = pred_dir / "samples.jsonl_results.jsonl"
    for line in results_file.read_text().splitlines():
        r = json.loads(line)
        ok_compile = bool(r["compiled"]) and all(r["compiled"])
        per_task[r["task_id"]] = {"compiled": ok_compile, "all_passed": r["all_passed"]}
        compiled += ok_compile
        passed += bool(r["all_passed"])
    for line in (pred_dir / "samples.jsonl").read_text().splitlines():
        if not json.loads(line)["completion"].strip():
            no_code += 1

    n = len(per_task)
    return Fitness(
        genome_id=genome_id, n_tasks=n,
        csr=round(compiled / n, 4) if n else 0.0,
        pass_at_1=round(passed / n, 4) if n else 0.0,
        per_task=per_task, no_code=no_code,
    )
