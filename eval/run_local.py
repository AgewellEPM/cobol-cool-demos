#!/usr/bin/env python3
"""COBOLEval runner for local Ollama models (R1 baseline).

Generates completions for the first N COBOLEval tasks with a local model,
then scores them with the (execution-enabled) COBOLEval harness:
compile success rate + Pass@1, per model, written to a summary JSON.

Usage:
    ../venv/bin/python run_local.py --model qwen2.5-coder:7b --tasks 25
    ../venv/bin/python run_local.py --model cobol-jeeves --tasks 25
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
COBOLEVAL = HERE / "COBOLEval"
sys.path.insert(0, str(COBOLEVAL / "scripts"))

OLLAMA = "http://localhost:11434/api/chat"

INSTRUCTIONS = """
Complete this GnuCOBOL 3.2 subprogram. Reply with the COMPLETE program
(IDENTIFICATION DIVISION through END PROGRAM) in ONE ```cobol code block.

Requirements:
- DATA DIVISION section order: WORKING-STORAGE SECTION first, then
  LINKAGE SECTION (copy the LINKAGE SECTION from the skeleton verbatim).
- PROCEDURE DIVISION USING LINKED-ITEMS.
- Store the answer in the RESULT field of LINKED-ITEMS, then GOBACK.
- End with: END PROGRAM <program-id>.
- Fixed-format: statements start at column 12 or later; nothing before
  column 8 except division/section headers and paragraph names.
"""


def ask(model, prompt, timeout=300):
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0.0},
                "stream": False,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["message"]["content"]


def extract(reply):
    m = re.search(r"```(?:cobol)?\s*\n(.*?)```", reply, re.S | re.I)
    src = m.group(1) if m else reply
    if "IDENTIFICATION DIVISION" not in src.upper():
        return ""
    # drop any prose before the first division header
    idx = src.upper().index("IDENTIFICATION DIVISION")
    line_start = src.rfind("\n", 0, idx) + 1
    return fix_section_order(src[line_start:])


def fix_section_order(src):
    """The upstream skeleton puts WORKING-STORAGE after LINKAGE (invalid in
    GnuCOBOL) and models echo it verbatim. Deterministically reorder:
    WORKING-STORAGE block moves to just before LINKAGE SECTION.
    Model-agnostic normalization — applied to every model equally.
    Line-based and comment-aware: the skeleton's own comment mentions both
    section names, so substring search alone matches the wrong line."""
    lines = src.split("\n")

    def is_comment(l):
        return (len(l) > 6 and l[6] == "*") or l.lstrip().startswith("*>")

    def find_line(needle):
        for i, l in enumerate(lines):
            if needle in l.upper() and not is_comment(l):
                return i
        return -1

    ls = find_line("LINKAGE SECTION")
    ws = find_line("WORKING-STORAGE SECTION")
    pd = find_line("PROCEDURE DIVISION")
    if ls == -1 or ws == -1 or pd == -1 or ws < ls or not (ls < ws < pd):
        return src  # already fine (or shape too odd to touch)
    reordered = lines[:ls] + lines[ws:pd] + lines[ls:ws] + lines[pd:]
    return "\n".join(reordered)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--tasks", type=int, default=25)
    args = ap.parse_args()

    tasks = [
        json.loads(l)
        for l in (COBOLEVAL / "data" / "CobolEval.jsonl").read_text().splitlines()
    ][: args.tasks]

    tag = args.model.replace(":", "_").replace("/", "_")
    pred_dir = COBOLEVAL / "preds" / tag
    pred_dir.mkdir(parents=True, exist_ok=True)
    samples_path = pred_dir / "samples.jsonl"

    t0 = time.time()
    with samples_path.open("w") as out:
        for i, t in enumerate(tasks):
            prompt = INSTRUCTIONS + "\n```cobol\n" + t["prompt"] + "\n```\n"
            try:
                reply = ask(args.model, prompt)
                completion = extract(reply)
            except Exception as e:  # fail the task, not the run
                print(f"[{i+1}/{len(tasks)}] {t['task_id']} GEN-ERROR: {e}",
                      flush=True)
                completion = ""
            out.write(json.dumps({
                "sample_id": 0,
                "task_id": t["task_id"],
                "completion": completion,
            }) + "\n")
            out.flush()
            print(f"[{i+1}/{len(tasks)}] {t['task_id']} "
                  f"({'ok' if completion else 'NO-CODE'}, "
                  f"{time.time()-t0:.0f}s elapsed)", flush=True)

    # score with the COBOLEval harness (execution enabled in our copy)
    import os
    os.chdir(COBOLEVAL)  # harness uses cwd-relative result files
    from evaluation import evaluate_functional_correctness
    from collections import defaultdict

    results = evaluate_functional_correctness(
        str(pred_dir), k=[1], problem_file=str(COBOLEVAL / "data" / "CobolEval.jsonl")
    )

    # recompute headline numbers from the results file (harness prints, we persist)
    per_task = defaultdict(dict)
    compiled_tasks = passed_tasks = 0
    for line in (pred_dir / "samples.jsonl_results.jsonl").read_text().splitlines():
        r = json.loads(line)
        per_task[r["task_id"]] = {
            "compiled": all(r["compiled"]) and bool(r["compiled"]),
            "all_passed": r["all_passed"],
        }
        compiled_tasks += 1 if (r["compiled"] and all(r["compiled"])) else 0
        passed_tasks += 1 if r["all_passed"] else 0

    n = len(per_task)
    summary = {
        "model": args.model,
        "tasks": n,
        "compile_all_tests_rate": round(compiled_tasks / n, 4) if n else 0,
        "pass_at_1": round(passed_tasks / n, 4) if n else 0,
        "harness_pass_at_k": {k: float(v) for k, v in (results or {}).items()}
        if isinstance(results, dict) else None,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (pred_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
