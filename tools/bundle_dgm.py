#!/usr/bin/env python3
"""Deterministically flatten the DGM core (7 modules) into ONE self-contained file.
Kept faithful: strips only intra-package imports, hoists+dedupes stdlib imports,
namespaces the one colliding helper (solver._score), rewires diag.classify, and
makes the COBOLEval dataset path location-independent."""
import re
from pathlib import Path

SRC = Path.home() / "cobol-cool-demos" / "dgm"
OUT = Path.home() / "cobol-cool-demos" / "cobol_dgm_demo.py"
ORDER = ["genome", "diagnostics", "solver", "evaluate", "archive", "mutate", "loop"]

RELATIVE = re.compile(r"^\s*from\s+(\.|dgm[\s.])")         # from .x / from . import x / from dgm.x
FUTURE = re.compile(r"^\s*from\s+__future__\s+import\b")
TOPLEVEL_IMPORT = re.compile(r"^(import\s+\S|from\s+[A-Za-z_]\S*\s+import\b)")  # no leading space, not relative

futures, imports, body = set(), [], []

for name in ORDER:
    text = (SRC / f"{name}.py").read_text()
    # per-module fixes BEFORE line processing
    if name == "solver":
        text = re.sub(r"\b_score\b", "_solver_score", text)          # collides with evaluate._score
    if name == "loop":
        text = re.sub(r"\bmutate\.", "", text)                       # `from . import mutate` → funcs now top-level
    if name == "evaluate":
        text = text.replace("diag.classify", "classify")             # diagnostics was `import . as diag`
        text = text.replace(
            'COBOLEVAL = HERE.parent / "eval" / "COBOLEval"',
            '# location-independent: find the COBOLEval dataset wherever this file lives\n'
            'def _find_cobol_eval():\n'
            '    _h = Path(__file__).resolve().parent\n'
            '    for _b in (_h, _h.parent, Path.home() / "cobol-cool-demos"):\n'
            '        if (_b / "eval" / "COBOLEval" / "data" / "CobolEval.jsonl").exists():\n'
            '            return _b / "eval" / "COBOLEval"\n'
            '    return _h / "eval" / "COBOLEval"\n'
            'COBOLEVAL = _find_cobol_eval()')

    body.append(f"\n# {'='*70}\n# ── module: dgm/{name}.py (flattened) ──\n# {'='*70}")
    for line in text.splitlines():
        if FUTURE.match(line):
            futures.add(line.strip()); continue
        if RELATIVE.match(line):
            continue                                                  # drop intra-package imports
        if TOPLEVEL_IMPORT.match(line) and not line.startswith((" ", "\t")):
            if line.strip() not in imports:
                imports.append(line.strip())
            continue
        body.append(line)

HEADER = '''"""cobol_dgm_demo.py — the COBOL Darwin Godel Machine, in ONE self-contained file.

A drop-in, single-file build of the DGM CORE (genome + diagnostics + solver +
evaluate + archive + mutate + loop) — the offline-COBOL evolutionary search:

    seed the archive with genome-zero (proven baseline scaffold)
    repeat N times:
        parent  = archive.select_parent()          # open-ended, novelty-aware
        child   = mutate.propose(parent, failures)  # self-modify the scaffold
        fitness = evaluate(child)                    # REAL COBOLEval execution
        archive.add(child, fitness)                  # keep it, win or lose

This is a FLATTENED copy of the modular package in ./dgm/ (kept as the source of
truth). It is generated, not hand-edited — regenerate with tools/bundle_dgm.py.
No cross-module imports; frozen local model + evolving scaffold (never weights).

Needs (all present on Luke's box): Ollama serving `cobol-jeeves-ft`, `cobc`
(GnuCOBOL), and the COBOLEval dataset under ./eval/COBOLEval/.

Run:  python cobol_dgm_demo.py --iterations 8 --tasks 12
PROTOTYPE.
"""'''

# loop.py already ends with its own `if __name__ == "__main__": main()` — don't add a second
# (two guards would run the whole DGM search twice).
parts = [HEADER, "", "\n".join(sorted(futures)) if futures else "", "",
         "\n".join(imports), "\n".join(body)]
OUT.write_text("\n".join(p for p in parts if p is not None) + "\n")
print(f"wrote {OUT} — {len(OUT.read_text().splitlines())} lines")
print(f"  futures={len(futures)} hoisted-imports={len(imports)}")
