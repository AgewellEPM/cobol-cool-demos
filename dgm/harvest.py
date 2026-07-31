"""DGM Tier-B harvest — turn execution-verified wins into training data.

The DGM's fitness gate is a factory for verified data: any completion that PASSES
the COBOLEval tests is an execution-verified (prompt -> correct COBOL) pair. Fine-
tuning on the model's own verified outputs (STaR / rejection-sampling FT) is the
weight-axis of self-improvement — the frozen model of one generation becomes the
better model of the next.

⚠️ CONTAMINATION SAFETY IS THE WHOLE GAME. Training on a benchmark task and then
scoring on it is memorization, not improvement. So COBOLEval is split ONCE, here,
into a TRAIN_POOL the harvester may mine and a HELD_OUT_TEST it must never touch.
Any harvest of a held-out task id is refused, loudly. Final Tier-B evaluation must
run ONLY on HELD_OUT_TEST (use `revalidate --offset <TEST start>`), never the pool.

Output is drop-in for the existing MLX LoRA pipeline: dataset/tierb_harvested.jsonl
in the same {"messages": [...]} chat shape as dataset/train.jsonl, plus a
provenance record naming the source genome + task + verification for every pair.

GPU-free: reads pred dirs written by evaluate.py and re-checks each kept program
with cobc. The LoRA run itself (train/run_lora.sh) is the separate, gated step.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from .evaluate import COBOLEVAL, TASKS_FILE

# ---- the ONE split. 0..TRAIN_POOL_END inclusive may be harvested; the rest is
# ---- the untouchable benchmark. Change it here and nowhere else.
TRAIN_POOL_END = 99          # tasks 0..99 harvestable
HELD_OUT_TEST_START = 100    # tasks 100..145 are eval-only, never trained on

INSTRUCTIONS = (
    "Complete this GnuCOBOL 3.2 subprogram. Reply with the COMPLETE program "
    "(IDENTIFICATION DIVISION through END PROGRAM) in ONE ```cobol code block."
)


def _task_index(task_id: str) -> int:
    """'HumanEval/<n>' -> n. Fails LOUD on any other shape — a mis-parsed id must
    never silently land on the wrong side of the train/test split."""
    prefix, _, num = task_id.partition("/")
    if prefix != "HumanEval" or not num.isdigit():
        raise ValueError(f"unexpected task_id shape {task_id!r} — refusing to "
                         "split it (contamination guard)")
    return int(num)


def _load_prompts() -> dict[str, str]:
    return {
        json.loads(l)["task_id"]: json.loads(l)["prompt"]
        for l in TASKS_FILE.read_text().splitlines()
    }


def _compiles(src: str) -> bool:
    """Cheap re-check that a harvested program still builds (grader's mode)."""
    if not src.strip():
        return False
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "h.cob"
        f.write_text(src)
        r = subprocess.run(
            ["cobc", "-w", "-fsyntax-only", "-fformat=variable", str(f)],
            capture_output=True, text=True,
        )
        return r.returncode == 0


def harvest(pred_root: Path, prompts: dict[str, str]) -> tuple[list[dict], list[dict], dict]:
    """Scan every genome's predictions; collect verified TRAIN_POOL wins.

    Returns (pairs, provenance, stats). Dedups by task_id keeping the shortest
    verified completion (cleaner, less likely to carry dead code)."""
    best: dict[str, tuple[int, str, str]] = {}   # task_id -> (len, completion, genome_tag)
    stats = {"genomes": 0, "passing_seen": 0, "held_out_refused": 0,
             "out_of_pool": 0, "recheck_dropped": 0}

    for pred_dir in sorted(pred_root.glob("dgm_*")):
        results = pred_dir / "samples.jsonl_results.jsonl"
        samples = pred_dir / "samples.jsonl"
        if not (results.exists() and samples.exists()):
            continue
        stats["genomes"] += 1
        # Build the completion map with an explicit duplicate check: silently
        # collapsing two rows for the same task_id could pair an all_passed
        # verdict with the WRONG completion. One sample per task is expected;
        # anything else is a corrupt pred file and must fail loud.
        completions: dict[str, str] = {}
        for l in samples.read_text().splitlines():
            row = json.loads(l)
            tid = row["task_id"]
            if tid in completions:
                raise ValueError(f"duplicate task_id {tid!r} in {samples} — "
                                 "cannot trust all_passed<->completion pairing")
            completions[tid] = row["completion"]

        for line in results.read_text().splitlines():
            r = json.loads(line)
            if not r["all_passed"]:
                continue
            tid = r["task_id"]
            stats["passing_seen"] += 1
            idx = _task_index(tid)
            if idx >= HELD_OUT_TEST_START:                # never train on test
                stats["held_out_refused"] += 1
                continue
            if not (0 <= idx <= TRAIN_POOL_END):           # TRAIN_POOL_END is authoritative
                stats["out_of_pool"] += 1
                continue
            if tid not in completions:                     # passing result, no completion = corrupt
                raise ValueError(f"result {tid!r} all_passed but absent from "
                                 f"{samples} — corrupt pred pair")
            comp = completions[tid]
            if not _compiles(comp):                        # corruption filter (all_passed already earned)
                stats["recheck_dropped"] += 1
                continue
            cur = best.get(tid)
            if cur is None or len(comp) < cur[0]:          # all candidates already passed; prefer least dead code
                best[tid] = (len(comp), comp, pred_dir.name)

    pairs, prov = [], []
    for tid, (_, comp, tag) in sorted(best.items()):
        if tid not in prompts:
            raise ValueError(f"no prompt for harvested task {tid!r} in the task "
                             "file — refusing to emit an unanchored pair")
        user = f"{INSTRUCTIONS}\n\n```cobol\n{prompts[tid]}\n```"
        pairs.append({"messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": f"```cobol\n{comp}\n```"},
        ]})
        prov.append({"task_id": tid, "source_genome": tag, "split": "train_pool",
                     "verification": "COBOLEval all_passed + cobc re-check"})
    stats["unique_pairs"] = len(pairs)
    return pairs, prov, stats


def main() -> None:
    ap = argparse.ArgumentParser(description="harvest execution-verified COBOL training pairs")
    ap.add_argument("--pred-root", type=Path, default=COBOLEVAL / "preds")
    ap.add_argument("--out", type=Path, default=COBOLEVAL.parent.parent / "dataset" / "tierb_harvested.jsonl")
    args = ap.parse_args()

    pairs, prov, stats = harvest(args.pred_root, _load_prompts())
    args.out.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pairs))
    args.out.with_suffix(".provenance.jsonl").write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in prov))

    print(f"harvested {stats['unique_pairs']} verified pairs "
          f"from {stats['genomes']} genomes")
    print(f"  passing completions seen: {stats['passing_seen']}")
    print(f"  held-out (>= task {HELD_OUT_TEST_START}) REFUSED: {stats['held_out_refused']}")
    print(f"  dropped on cobc re-check: {stats['recheck_dropped']}")
    print(f"  -> {args.out}")
    print(f"  train pool = tasks 0..{TRAIN_POOL_END}; eval Tier-B ONLY on "
          f"tasks {HELD_OUT_TEST_START}..145 (never harvested)")


if __name__ == "__main__":
    main()
