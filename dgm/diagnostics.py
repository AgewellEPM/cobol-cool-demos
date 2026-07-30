"""DGM failure diagnostics — turn a genome's compile failures into a targetable
error-class histogram, so the mutation operator can aim at the dominant failure
mode instead of mutating blind.

Fully offline: re-runs `cobc -fsyntax-only` on the solution files the COBOLEval
harness already wrote (preds/<tag>/solutions/*.cbl). Compile-only, no model, no
network — cheap enough to run at the end of every evaluation.

The classes map 1:1 onto the scaffold levers in mutate._targeted():
    reserved_word    — SUM/COUNT/DATA/... used as a data name
    column_overflow  — fixed-format column-72 / area-A violations
    user_function    — model invented a user-defined FUNCTION or undefined name
    subscript_misuse — scalar used with a subscript (e.g. RESULT(...))
    flow_mismatch    — dangling END-PERFORM/END-IF/scope terminators
    no_code          — genome emitted nothing compilable
    syntax_other     — a real error none of the above matched
"""
from __future__ import annotations

import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

# Ordered: first match wins, most-specific first.
_CLASSES: list[tuple[str, re.Pattern]] = [
    ("reserved_word",    re.compile(r"reserved word|reserved-word", re.I)),
    ("subscript_misuse", re.compile(r"requires (one|a) subscript|subscript", re.I)),
    ("user_function",    re.compile(r"intrinsic function name|\bFUNCTION\b|is not defined", re.I)),
    ("column_overflow",  re.compile(r"column|area [ab]\b|beyond|exceeds", re.I)),
    ("flow_mismatch",    re.compile(r"unexpected (END-PERFORM|END-IF|GOBACK|SECTION)|scope", re.I)),
]


def _syntax_error(cbl: Path) -> str | None:
    """Return cobc's stderr if `cbl` fails to compile (fixed then free), else None."""
    for extra in ([], ["-free"]):
        r = subprocess.run(
            ["cobc", "-fsyntax-only", *extra, str(cbl)],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return None
        err = r.stderr
    return err  # last (free-format) stderr — both formats failed


def classify(pred_dir: Path, empty_task_ids: set[str] | None = None) -> dict:
    """Histogram the compile failures for one genome's predictions.

    `empty_task_ids` (optional) are tasks whose completion was empty — counted
    as `no_code` without a compile attempt. Returns
    {"counts": {class: n}, "samples": {class: stderr_excerpt}, "n_failed": int}.
    """
    pred_dir = Path(pred_dir)
    sols = pred_dir / "solutions"
    counts: Counter = Counter()
    samples: dict[str, str] = {}

    if shutil.which("cobc") is None:
        return {"counts": {}, "samples": {}, "n_failed": 0, "error": "cobc missing"}

    for tid in empty_task_ids or set():
        counts["no_code"] += 1
    samples_needed = True

    for cbl in sorted(sols.glob("*.cbl")) if sols.is_dir() else []:
        err = _syntax_error(cbl)
        if err is None:
            continue
        for name, pat in _CLASSES:
            if pat.search(err):
                counts[name] += 1
                samples.setdefault(name, err.strip()[:240])
                break
        else:
            counts["syntax_other"] += 1
            samples.setdefault("syntax_other", err.strip()[:240])

    return {
        "counts": dict(counts),
        "samples": samples,
        "n_failed": sum(counts.values()),
    }


def dominant(diagnostics: dict) -> str | None:
    """The single most common failure class, or None if there are no failures."""
    counts = (diagnostics or {}).get("counts") or {}
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]
