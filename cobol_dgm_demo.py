"""cobol_dgm_demo.py — the COBOL Darwin Godel Machine, in ONE self-contained file.

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
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
import sqlite3
import tempfile
import urllib.request
import os
import sys
from dataclasses import dataclass, field
import math
import random
from dataclasses import asdict
import argparse
import time

# ======================================================================
# ── module: dgm/genome.py (flattened) ──
# ======================================================================
"""DGM genome — the evolvable COBOL agent scaffold.

A Genome is the complete, serializable description of ONE coding agent: every
part of the cobol-jeeves scaffold the Darwin Godel Machine is allowed to
mutate. The foundation model (weights) is FROZEN — only the scaffold around it
evolves, exactly as in the Sakana DGM. Improving the genome means improving how
the frozen model is grounded, prompted, decoded, and repaired — never the
weights, and never the offline guarantee.

The `evolvable()` subset is the search space the mutation operator may touch.
Provenance fields (id/parent/generation) are set by the loop, not mutated.
"""


# Seed scaffold: mirrors the proven run_local.py + cobol-jeeves setup that
# scored CSR 0.24 / Pass@1 0.08 (n=25). This is genome-zero — the number the
# DGM must beat.
SEED_INSTRUCTIONS = """\
Complete this GnuCOBOL 3.2 subprogram. Reply with the COMPLETE program
(IDENTIFICATION DIVISION through END PROGRAM) in ONE ```cobol code block.

Requirements:
- DATA DIVISION section order: WORKING-STORAGE SECTION first, then
  LINKAGE SECTION (copy the LINKAGE SECTION from the skeleton verbatim).
- PROCEDURE DIVISION USING LINKED-ITEMS.
- Store the answer in the RESULT field of LINKED-ITEMS, then GOBACK.
- End with: END PROGRAM <program-id>.
- Fixed-format: statements start at column 12 or later; nothing before
  column 8 except division/section headers and paragraph names."""

SEED_REPAIR = """\
Your program does NOT compile. cobc says:

{diagnostics}

Fix every error and reply with the complete corrected program in one ```cobol
block. Remember: fixed-format code must not pass column 72; avoid reserved
words (SUM, COUNT, DATA, ...) as data names."""


@dataclass
class Genome:
    # ---- evolvable scaffold (the DGM search space) ----
    instructions: str = SEED_INSTRUCTIONS
    repair_prompt: str = SEED_REPAIR
    temperature: float = 0.0
    use_peels: bool = True          # RAG: inject compiler-verified peels
    use_atoms: bool = True          # RAG: inject typed legacy-floor atoms
    top_k_peels: int = 4
    top_k_atoms: int = 6
    repair_attempts: int = 2        # compiler-feedback repair rounds
    fix_section_order: bool = True  # deterministic WS/LINKAGE reorder
    format_mode: str = "fixed"      # fixed | free | auto (repair-gate probe)

    # ---- frozen (never mutated: the offline model itself) ----
    model: str = "cobol-jeeves-ft"

    # ---- provenance (set by the loop, not the mutation operator) ----
    genome_id: str = ""
    parent_id: str = ""
    generation: int = 0
    origin: str = "seed"   # "seed" | proposer name that produced it
    notes: str = ""        # mutation rationale / hypothesis

    # Fields the mutation operator is permitted to change.
    EVOLVABLE = (
        "instructions", "repair_prompt", "temperature", "use_peels",
        "use_atoms", "top_k_peels", "top_k_atoms", "repair_attempts",
        "fix_section_order", "format_mode",
    )

    def evolvable(self) -> dict:
        """The mutable scaffold only — what a child may differ by."""
        return {k: getattr(self, k) for k in self.EVOLVABLE}

    def fingerprint(self) -> str:
        """Stable hash of (model + evolvable scaffold). Two genomes with the
        same fingerprint are behaviourally identical — used to skip re-evaluating
        duplicates the mutation operator happens to re-propose."""
        blob = json.dumps(
            {"model": self.model, **self.evolvable()},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def child(self, changes: dict, *, origin: str, notes: str) -> "Genome":
        """Derive a child genome by applying `changes` to the evolvable scaffold.
        Fails fast if a change targets a non-evolvable field — the mutation
        operator must never touch weights or provenance."""
        bad = set(changes) - set(self.EVOLVABLE)
        if bad:
            raise ValueError(f"mutation touched non-evolvable field(s): {sorted(bad)}")
        data = asdict(self)
        data.update(changes)
        data.update(
            genome_id="", parent_id=self.genome_id,
            generation=self.generation + 1, origin=origin, notes=notes,
        )
        return Genome(**data)

    def with_id(self) -> "Genome":
        """Assign a content-addressed id (fingerprint + generation)."""
        self.genome_id = f"g{self.generation:03d}-{self.fingerprint()}"
        return self

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "Genome":
        return cls(**json.loads(s))


def seed_genome() -> Genome:
    """Genome-zero: the proven baseline scaffold, id-stamped."""
    return Genome(origin="seed", notes="baseline scaffold (run_local.py)").with_id()

# ======================================================================
# ── module: dgm/diagnostics.py (flattened) ──
# ======================================================================
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


# Ordered: FIRST MATCH WINS, so specific/structural classes must precede the
# broad `user_function` (which includes `is not defined`) — otherwise a column
# or scope error that merely mentions an undefined name gets the wrong bucket
# and, worse, the wrong targeted directive.
_CLASSES: list[tuple[str, re.Pattern]] = [
    ("reserved_word",    re.compile(r"reserved word|reserved-word", re.I)),
    ("subscript_misuse", re.compile(r"requires (one|a) subscript|subscript", re.I)),
    ("column_overflow",  re.compile(r"column|area [ab]\b|beyond|exceeds", re.I)),
    ("flow_mismatch",    re.compile(r"unexpected (END-PERFORM|END-IF|GOBACK|SECTION)|scope", re.I)),
    # C-style inline arithmetic/expressions COBOL rejects (the #1 real failure on
    # this benchmark): FROM WS-I + 1, ABS(x), nested parens in conditions.
    ("expr_syntax",      re.compile(r"unexpected \(|unexpected -, expecting|invalid expression|unfinished expression", re.I)),
    # broadest last: user-defined FUNCTION / undefined name / undeclared data item
    ("user_function",    re.compile(r"intrinsic function name|\bFUNCTION\b|is not defined|not a file name", re.I)),
]


def classify_error(stderr: str) -> str:
    """Bucket one cobc stderr blob into an error class (first match wins,
    specific-before-broad). Pure + version-independent — the unit-testable core
    of classify()."""
    for name, pat in _CLASSES:
        if pat.search(stderr):
            return name
    return "syntax_other"


def _syntax_error(cbl: Path) -> str | None:
    """Return cobc's stderr if `cbl` fails to compile, else None.

    Mirrors the COBOLEval grader's compile mode (`cobc -w -fformat=variable`,
    evaluation.py:100) so the classifier's failure set matches the graded one —
    compiling fixed-then-free would false-negative programs the grader rejects
    (and vice-versa). `-fsyntax-only` skips the call-driver link the grader adds;
    we only need the syntax/semantic errors, which this surfaces identically."""
    r = subprocess.run(
        ["cobc", "-w", "-fsyntax-only", "-fformat=variable", str(cbl)],
        capture_output=True, text=True,
    )
    return None if r.returncode == 0 else r.stderr


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
        name = classify_error(err)
        counts[name] += 1
        samples.setdefault(name, err.strip()[:240])

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

# ======================================================================
# ── module: dgm/solver.py (flattened) ──
# ======================================================================
"""DGM solver — execute one Genome against one COBOLEval task.

Pipeline (all offline, localhost only):
    RAG grounding (peels + floor atoms, per genome toggles)
      -> Ollama chat (frozen model, genome temperature)
      -> extract + normalize COBOL (per genome toggles)
      -> local cobc gate -> compiler-feedback repair (genome.repair_attempts)
      -> final completion string (scored later by the COBOLEval harness).

The local cobc gate here only *drives repair*; the authoritative grade is the
COBOLEval execution harness in evaluate.py. Factored out of ~/bin/cobol-jeeves
and eval/run_local.py so there is one parameterized code path, not two copies.
"""



OLLAMA = "http://localhost:11434/api/chat"
PEELS = Path.home() / ".perslis" / "peels.jsonl"
FLOOR = Path.home() / ".perslis" / "legacy_floor.db"

_STOP = frozenset(
    "a an and are as at be by for from how in is it of on or that the to "
    "what when with write me i you can please program cobol".split()
)


# ---------------------------------------------------------------- RAG grounding
def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9-]+", text.lower()) if t not in _STOP]


def _solver_score(query_toks, text: str) -> int:
    body = text.lower()
    return sum(body.count(t) for t in set(query_toks))


def _load_peels(query_toks, k: int, path: Path = PEELS):
    path = Path(path)
    if not path.exists():
        return []
    scored = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        if "cobol" not in json.dumps(p)[:2000].lower():
            continue
        rule = p.get("title") or p.get("rule") or ""
        s = _solver_score(query_toks, rule)
        if s > 0:
            scored.append((s, p.get("id", "?"), rule))
    scored.sort(reverse=True)
    return scored[:k]


def _load_atoms(query_toks, k: int, path: Path = FLOOR):
    path = Path(path)
    if not path.exists():
        return []
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT subject, relation_type, object FROM typed_relations "
            "WHERE subject LIKE '%cobol%' OR object LIKE '%cobol%'"
        ).fetchall()
    finally:
        con.close()
    scored = []
    for s, r, o in rows:
        sc = _solver_score(query_toks, f"{s} {r} {o}")
        if sc > 0:
            scored.append((sc, f"{s} {r.replace('_', ' ')} {o}"))
    scored.sort(reverse=True)
    return scored[:k]


def build_prompt(
    g: Genome,
    task_prompt: str,
    *,
    peels_path: Path = PEELS,
    floor_path: Path = FLOOR,
) -> str:
    """Genome instructions + (optional) RAG grounding + the COBOL skeleton."""
    parts = [g.instructions.strip(), ""]
    if g.use_peels or g.use_atoms:
        q = _tokens(task_prompt)
        if g.use_peels:
            for _, pid, rule in _load_peels(q, g.top_k_peels, peels_path):
                parts.append(f"- GROUNDING [{pid}] {rule}")
        if g.use_atoms:
            for _, fact in _load_atoms(q, g.top_k_atoms, floor_path):
                parts.append(f"- GROUNDING {fact}")
        parts.append("")
    parts.append("```cobol\n" + task_prompt + "\n```")
    return "\n".join(parts)


# ------------------------------------------------------------------- generation
def ask(model: str, messages, temperature: float, timeout: int = 300,
        seed: int | None = None) -> str:
    options = {"temperature": temperature}
    if seed is not None:
        options["seed"] = int(seed)
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps({
            "model": model, "messages": messages,
            "options": options, "stream": False,
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["message"]["content"]


# --------------------------------------------------------- extract + normalize
def extract(reply: str, g: Genome) -> str:
    m = re.search(r"```(?:cobol)?\s*\n(.*?)```", reply, re.S | re.I)
    src = m.group(1) if m else reply
    if "IDENTIFICATION DIVISION" not in src.upper():
        return ""
    idx = src.upper().index("IDENTIFICATION DIVISION")
    src = src[src.rfind("\n", 0, idx) + 1:]
    return _fix_section_order(src) if g.fix_section_order else src


def _fix_section_order(src: str) -> str:
    """Move WORKING-STORAGE before LINKAGE when the skeleton echoed them
    backwards (invalid in GnuCOBOL). Comment-aware, line-based."""
    lines = src.split("\n")

    def is_comment(l):
        return (len(l) > 6 and l[6] == "*") or l.lstrip().startswith("*>")

    def find(needle):
        for i, l in enumerate(lines):
            if needle in l.upper() and not is_comment(l):
                return i
        return -1

    ls, ws, pd = find("LINKAGE SECTION"), find("WORKING-STORAGE SECTION"), find("PROCEDURE DIVISION")
    if -1 in (ls, ws, pd) or not (ls < ws < pd):
        return src
    return "\n".join(lines[:ls] + lines[ws:pd] + lines[ls:ws] + lines[pd:])


# ---------------------------------------------------------------- local cobc gate
def cobc_gate(src: str, format_mode: str) -> tuple[bool, str]:
    """Compile the program locally to drive repair. Tries the genome's preferred
    format first; `auto` tries fixed then free. Returns (ok, diagnostics)."""
    if not src.strip():
        return False, "NO-CODE: empty completion"
    modes = {"fixed": [("fixed", [])], "free": [("free", ["-free"])],
             "auto": [("fixed", []), ("free", ["-free"])]}[format_mode]
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "gen.cob"
        f.write_text(src)
        fails = []
        for label, extra in modes:
            r = subprocess.run(
                ["cobc", "-x", *extra, "-o", str(Path(td) / "gen"), str(f)],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                return True, f"COMPILE-PASS ({label})"
            fails.append(f"--- {label} ---\n{r.stderr.strip()[:800]}")
        return False, "\n".join(fails)


# --------------------------------------------------------------------- solve
def solve_task(
    g: Genome,
    task_prompt: str,
    gen_timeout: int = 300,
    generation_seed: int | None = None,
    *,
    peels_path: Path = PEELS,
    floor_path: Path = FLOOR,
) -> str:
    """Run the full genome pipeline; return the final (repaired) completion.

    Raises on transport failure so the evaluator can score the task as failed
    rather than silently swallowing a broken run."""
    messages = [{
        "role": "user",
        "content": build_prompt(
            g,
            task_prompt,
            peels_path=peels_path,
            floor_path=floor_path,
        ),
    }]
    reply = ask(g.model, messages, g.temperature, gen_timeout,
                seed=generation_seed)
    completion = extract(reply, g)

    for attempt in range(g.repair_attempts):
        ok, diag = cobc_gate(completion, g.format_mode)
        if ok:
            break
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user",
                         "content": g.repair_prompt.format(diagnostics=diag)})
        repair_seed = (
            None if generation_seed is None else generation_seed + attempt + 1
        )
        reply = ask(g.model, messages, g.temperature, gen_timeout,
                    seed=repair_seed)
        completion = extract(reply, g)
    return completion

# ======================================================================
# ── module: dgm/evaluate.py (flattened) ──
# ======================================================================
"""DGM fitness: score a Genome on COBOLEval through real execution.

Legacy callers may select a positional slice. Confirmatory callers must pass
``task_ids`` and a corpus path, which performs exact-ID selection and never
interprets IDs as offsets.
"""



HERE = Path(__file__).resolve().parent
# location-independent: find the COBOLEval dataset wherever this file lives
def _find_cobol_eval():
    _h = Path(__file__).resolve().parent
    for _b in (_h, _h.parent, Path.home() / "cobol-cool-demos"):
        if (_b / "eval" / "COBOLEval" / "data" / "CobolEval.jsonl").exists():
            return _b / "eval" / "COBOLEval"
    return _h / "eval" / "COBOLEval"
COBOLEVAL = _find_cobol_eval()
TASKS_FILE = COBOLEVAL / "data" / "CobolEval.jsonl"


@dataclass
class Fitness:
    genome_id: str
    n_tasks: int
    csr: float
    pass_at_1: float
    per_task: dict
    no_code: int
    diagnostics: dict = field(default_factory=dict)

    def key(self) -> tuple:
        return (self.csr, self.pass_at_1, -self.no_code)


def _read_tasks(tasks_file: Path = TASKS_FILE) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(tasks_file).read_text().splitlines()
        if line.strip()
    ]


def _load_tasks(n: int, offset: int = 0, tasks_file: Path = TASKS_FILE):
    return _read_tasks(tasks_file)[offset:offset + n]


def _load_tasks_by_ids(task_ids: list[str] | tuple[str, ...],
                       tasks_file: Path = TASKS_FILE) -> list[dict]:
    requested = [str(task_id) for task_id in task_ids]
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("task_ids must be a non-empty list of unique exact IDs")
    records = _read_tasks(tasks_file)
    by_id = {str(record["task_id"]): record for record in records}
    if len(by_id) != len(records):
        raise ValueError("task corpus contains duplicate task IDs")
    missing = [task_id for task_id in requested if task_id not in by_id]
    if missing:
        raise ValueError(f"task IDs absent from corpus: {missing}")
    return [by_id[task_id] for task_id in requested]


def task_generation_seed(base_seed: int | None, task_id: str) -> int | None:
    """Derive a stable per-task Ollama seed shared by compared models."""
    if base_seed is None:
        return None
    raw = f"{int(base_seed)}\0{task_id}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big") & 0x7fffffff


def evaluate(g: Genome, n_tasks: int | None = None, *, offset: int = 0,
             gen_timeout: int = 300, verbose: bool = False,
             generation_seed: int | None = None,
             pred_dir: Path | None = None,
             task_ids: list[str] | tuple[str, ...] | None = None,
             tasks_file: Path = TASKS_FILE,
             peels_path: Path = PEELS,
             floor_path: Path = FLOOR) -> Fitness:
    """Generate and score tasks for ``g``.

    ``task_ids`` is the leak-safe confirmatory interface. When supplied, exact
    IDs are resolved against ``tasks_file`` in the requested order; ``offset``
    is forbidden and ``n_tasks`` can only restate the exact list length.
    """
    tasks_file = Path(tasks_file)
    if not tasks_file.exists():
        sys.exit(f"FATAL: COBOLEval tasks missing at {tasks_file}")
    if task_ids is not None:
        if offset != 0:
            raise ValueError("offset cannot be combined with exact task_ids")
        tasks = _load_tasks_by_ids(task_ids, tasks_file)
        if n_tasks is not None and n_tasks != len(tasks):
            raise ValueError("n_tasks does not match exact task_ids length")
    else:
        if n_tasks is None:
            raise ValueError("n_tasks is required for legacy slice evaluation")
        tasks = _load_tasks(n_tasks, offset, tasks_file)

    if pred_dir is None:
        pred_dir = COBOLEVAL / "preds" / f"dgm_{g.genome_id}"
        pred_dir.mkdir(parents=True, exist_ok=True)
        samples_mode = "w"
    else:
        pred_dir = Path(pred_dir)
        pred_dir.mkdir(parents=True, exist_ok=False)
        samples_mode = "x"
    samples = pred_dir / "samples.jsonl"

    with samples.open(samples_mode) as out:
        for index, task in enumerate(tasks):
            task_seed = task_generation_seed(generation_seed, task["task_id"])
            try:
                completion = solve_task(
                    g,
                    task["prompt"],
                    gen_timeout,
                    generation_seed=task_seed,
                    peels_path=peels_path,
                    floor_path=floor_path,
                )
            except Exception as error:
                completion = ""
                if verbose:
                    print(
                        f"  [{index + 1}/{len(tasks)}] {task['task_id']} "
                        f"GEN-ERROR: {error}", flush=True,
                    )
            out.write(json.dumps({
                "sample_id": 0,
                "task_id": task["task_id"],
                "completion": completion,
                "generation_seed": task_seed,
            }, sort_keys=True) + "\n")
            out.flush()
            if verbose:
                print(
                    f"  [{index + 1}/{len(tasks)}] {task['task_id']} "
                    f"{'ok' if completion else 'NO-CODE'}", flush=True,
                )

    return _score(g.genome_id, pred_dir, tasks_file=tasks_file)


def _score(genome_id: str, pred_dir: Path,
           tasks_file: Path = TASKS_FILE) -> Fitness:
    """Run the COBOLEval execution harness and read per-task verdicts."""
    sys.path.insert(0, str(COBOLEVAL / "scripts"))
    cwd = os.getcwd()
    os.chdir(COBOLEVAL)
    try:
        from evaluation import evaluate_functional_correctness
        evaluate_functional_correctness(
            str(pred_dir), k=[1], problem_file=str(Path(tasks_file).resolve())
        )
    finally:
        os.chdir(cwd)

    per_task, compiled, passed = {}, 0, 0
    results_file = pred_dir / "samples.jsonl_results.jsonl"
    for line in results_file.read_text().splitlines():
        result = json.loads(line)
        ok_compile = bool(result["compiled"]) and all(result["compiled"])
        per_task[result["task_id"]] = {
            "compiled": ok_compile,
            "all_passed": bool(result["all_passed"]),
        }
        compiled += ok_compile
        passed += bool(result["all_passed"])

    empty_ids = set()
    for line in (pred_dir / "samples.jsonl").read_text().splitlines():
        row = json.loads(line)
        if not row["completion"].strip():
            empty_ids.add(row["task_id"])

    n = len(per_task)
    return Fitness(
        genome_id=genome_id,
        n_tasks=n,
        csr=round(compiled / n, 4) if n else 0.0,
        pass_at_1=round(passed / n, 4) if n else 0.0,
        per_task=per_task,
        no_code=len(empty_ids),
        diagnostics=classify(pred_dir, empty_ids),
    )

# ======================================================================
# ── module: dgm/archive.py (flattened) ──
# ======================================================================
"""DGM archive — open-ended store of every evaluated genome.

The defining DGM property: nothing is thrown away. Regressions are kept as
stepping stones because a worse scaffold can still be the ancestor of the best
one. Parent selection therefore balances performance against under-exploration
(few children) so the search does not collapse onto the current champion —
mirroring the Sakana DGM's novelty-aware sampling.

SQLite-backed so a run is resumable and inspectable: `sqlite3 archive.db`.
"""



_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    genome_id   TEXT PRIMARY KEY,
    parent_id   TEXT,
    generation  INTEGER,
    origin      TEXT,
    fingerprint TEXT,
    genome_json TEXT NOT NULL,
    csr         REAL,
    pass_at_1   REAL,
    n_tasks     INTEGER,
    no_code     INTEGER,
    children    INTEGER DEFAULT 0,
    seq         INTEGER,          -- insertion order (also the tiebreak clock)
    notes       TEXT,
    diagnostics TEXT              -- json: failure-class histogram for the proposer
);
"""


class Archive:
    def __init__(self, db_path: Path, rng: random.Random | None = None):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(_SCHEMA)
        # migration for archives created before the diagnostics column existed.
        # Idempotent + concurrency-tolerant: if a racing process added the column
        # (or holds a DDL lock) between our check and ALTER, swallow the
        # duplicate-column/locked error — the column ends up present either way.
        cols = {r["name"] for r in self.con.execute("PRAGMA table_info(agents)")}
        if "diagnostics" not in cols:
            try:
                self.con.execute("ALTER TABLE agents ADD COLUMN diagnostics TEXT")
                self.con.commit()
            except sqlite3.OperationalError:
                if "diagnostics" not in {
                    r["name"] for r in self.con.execute("PRAGMA table_info(agents)")
                }:
                    raise  # genuinely failed to migrate — do not run half-migrated
        self.rng = rng or random.Random(1234)  # deterministic by default

    # ------------------------------------------------------------- writes
    def add(self, g: Genome, fit: Fitness) -> bool:
        """Insert a newly-evaluated genome, atomically idempotent.

        Uses `INSERT ... ON CONFLICT(genome_id) DO NOTHING` so a re-added
        genome_id is a clean no-op (returns False) with NO TOCTOU window — a
        concurrent writer cannot make this raise IntegrityError or double-count
        the parent's `children`/rewrite `seq`. The parent child-count fires only
        when a row was truly inserted (checked via total_changes delta).

        Note: `seq` monotonicity assumes a single writer — which the DGM loop
        guarantees. The archive is not designed for concurrent evolution."""
        seq = (self.con.execute("SELECT COALESCE(MAX(seq), -1) FROM agents").fetchone()[0]) + 1
        before = self.con.total_changes
        self.con.execute(
            "INSERT INTO agents (genome_id, parent_id, generation, origin, "
            "fingerprint, genome_json, csr, pass_at_1, n_tasks, no_code, "
            "children, seq, notes, diagnostics) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?) "
            "ON CONFLICT(genome_id) DO NOTHING",
            (g.genome_id, g.parent_id, g.generation, g.origin, g.fingerprint(),
             g.to_json(), fit.csr, fit.pass_at_1, fit.n_tasks, fit.no_code,
             seq, g.notes, json.dumps(fit.diagnostics or {})),
        )
        inserted = (self.con.total_changes - before) == 1
        if inserted and g.parent_id:
            self.con.execute(
                "UPDATE agents SET children = children + 1 WHERE genome_id = ?",
                (g.parent_id,),
            )
        self.con.commit()
        return inserted

    # ------------------------------------------------------------- reads
    def has_fingerprint(self, fp: str) -> bool:
        return self.con.execute(
            "SELECT 1 FROM agents WHERE fingerprint = ? LIMIT 1", (fp,)
        ).fetchone() is not None

    def size(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM agents").fetchone()[0]

    def best(self) -> sqlite3.Row | None:
        # champion = highest CSR, then pass@1, then earliest discovered
        return self.con.execute(
            "SELECT * FROM agents ORDER BY csr DESC, pass_at_1 DESC, seq ASC LIMIT 1"
        ).fetchone()

    def get_genome(self, genome_id: str) -> Genome:
        row = self.con.execute(
            "SELECT genome_json FROM agents WHERE genome_id = ?", (genome_id,)
        ).fetchone()
        if not row:
            raise KeyError(genome_id)
        return Genome.from_json(row["genome_json"])

    def get_diagnostics(self, genome_id: str) -> dict:
        """The stored failure-class histogram for a genome (empty if none/old row)."""
        row = self.con.execute(
            "SELECT diagnostics FROM agents WHERE genome_id = ?", (genome_id,)
        ).fetchone()
        if not row or not row["diagnostics"]:
            return {}
        return json.loads(row["diagnostics"])

    def all_rows(self):
        return self.con.execute("SELECT * FROM agents ORDER BY seq ASC").fetchall()

    # --------------------------------------------------- parent selection
    def select_parent(self) -> Genome:
        """Open-ended, novelty-aware sampling.

        weight = sigmoid(performance) * 1/(1 + children)
        Performance rewards good scaffolds; the 1/(1+children) term keeps the
        search exploring stepping stones instead of endlessly refining the
        current champion. Every archived genome remains eligible."""
        rows = self.all_rows()
        if not rows:
            raise RuntimeError("archive is empty — seed it before selecting")
        weights = []
        for r in rows:
            perf = (r["csr"] or 0.0) + 0.25 * (r["pass_at_1"] or 0.0)
            sig = 1.0 / (1.0 + math.exp(-6.0 * (perf - 0.15)))  # centre near seed CSR
            weights.append(sig / (1.0 + (r["children"] or 0)))
        chosen = self.rng.choices(rows, weights=weights, k=1)[0]
        return Genome.from_json(chosen["genome_json"])

    def close(self) -> None:
        self.con.close()

# ======================================================================
# ── module: dgm/mutate.py (flattened) ──
# ======================================================================
"""DGM self-modification operators — propose a child scaffold from a parent.

Two proposers, same interface `propose(parent, failures, rng) -> (changes, notes)`:

  * heuristic (default, OFFLINE, zero deps) — guided moves over the genome knobs
    plus a bank of prompt variants. Lets the loop close and self-improve on any
    machine with no API key. This is what keeps the deliverable offline.

  * brain (pluggable upgrade) — hands the parent scaffold + its failure summary
    to a strong model and parses back a JSON scaffold edit. Faithful DGM shape:
    a frozen strong brain drives self-modification of the scaffold, while the
    frozen local model remains the offline solver. Fails fast if unavailable.

`changes` only ever targets Genome.EVOLVABLE — Genome.child() enforces that.
"""



# Compiler-error class -> a one-line instruction directive that targets it.
# Appended to the parent's instructions (base preserved) so a good prompt isn't
# thrown away — only sharpened at its actual failure mode.
_TARGETED_DIRECTIVES = {
    "user_function":
        "- Never define your own FUNCTION (or a paragraph used as one); use "
        "intrinsic functions (FUNCTION ABS, FUNCTION MOD, FUNCTION MAX ...) "
        "directly, and declare EVERY data name in WORKING-STORAGE before use.",
    "subscript_misuse":
        "- RESULT and other scalar LINKAGE items are scalars: write "
        "MOVE <value> TO RESULT — never subscript them like RESULT(I).",
    "reserved_word":
        "- Do NOT use reserved words (SUM, COUNT, DATA, LENGTH, TYPE ...) as "
        "data names; prefix your own (WS-SUM, WS-COUNT).",
    "column_overflow":
        "- Fixed-format: keep all code within columns 12-72; never let a "
        "statement run past column 72.",
    "expr_syntax":
        "- COBOL has NO inline arithmetic/expressions in PERFORM or IF (e.g. "
        "FROM WS-I + 1). COMPUTE values into a WORKING-STORAGE field first "
        "(COMPUTE WS-J = WS-I + 1) then reference it; call intrinsics as "
        "FUNCTION NAME(arg), never NAME(arg).",
}

# Alternative instruction blocks the heuristic proposer can swap in. Each is a
# plausible, self-contained rephrasing of the task contract — variety in the
# prompt is one of the cheapest, highest-signal scaffold levers.
_PROMPT_VARIANTS = [
    # sharper on the reserved-word + column pitfalls that dominate cobc failures
    """Complete this GnuCOBOL 3.2 subprogram. Reply with the COMPLETE program in\n"""
    """ONE ```cobol block, IDENTIFICATION DIVISION through END PROGRAM.\n\n"""
    """Hard rules:\n"""
    """- WORKING-STORAGE SECTION comes BEFORE LINKAGE SECTION.\n"""
    """- Copy the LINKAGE SECTION from the skeleton verbatim; keep every PIC.\n"""
    """- PROCEDURE DIVISION USING LINKED-ITEMS. Put the answer in RESULT, GOBACK.\n"""
    """- Fixed-format: code in columns 12-72 only. Never exceed column 72.\n"""
    """- Do NOT use reserved words as data names (SUM, COUNT, DATA, LENGTH, ...).\n"""
    """- End with: END PROGRAM <program-id>.""",
    # terse, worked-example framing
    """You are completing a GnuCOBOL 3.2 subprogram called as a subroutine.\n"""
    """Output ONLY the full program in one ```cobol block.\n\n"""
    """Checklist before you answer:\n"""
    """1. WORKING-STORAGE SECTION, then LINKAGE SECTION (verbatim from skeleton).\n"""
    """2. PROCEDURE DIVISION USING LINKED-ITEMS.\n"""
    """3. Compute, MOVE result into RESULT, then GOBACK.\n"""
    """4. Fixed-format columns 12-72; END PROGRAM <program-id> last.""",
]


# --------------------------------------------------------------- heuristic
def _heuristic(parent: Genome, failures: list[str], rng: random.Random):
    """Pick one guided move over the scaffold. Never a no-op."""
    moves = []

    # temperature jitter (explore decoding) — clamp to a sane band
    def temp_move():
        t = round(min(0.7, max(0.0, parent.temperature + rng.choice([-0.2, -0.1, 0.1, 0.2, 0.3]))), 2)
        return {"temperature": t} if t != parent.temperature else {"temperature": 0.2}
    moves.append(("temperature", temp_move))

    # more repair rounds (compiler feedback is the strongest signal we have)
    moves.append(("repair_attempts",
                  lambda: {"repair_attempts": min(5, parent.repair_attempts + rng.choice([1, 2]))}))

    # retrieval depth
    moves.append(("top_k_peels",
                  lambda: {"top_k_peels": min(8, max(0, parent.top_k_peels + rng.choice([-2, 2])))}))
    moves.append(("top_k_atoms",
                  lambda: {"top_k_atoms": min(10, max(0, parent.top_k_atoms + rng.choice([-3, 3])))}))

    # toggle grounding sources (does RAG help or distract this model?)
    moves.append(("use_atoms", lambda: {"use_atoms": not parent.use_atoms}))
    moves.append(("use_peels", lambda: {"use_peels": not parent.use_peels}))

    # format probe for the repair gate
    moves.append(("format_mode",
                  lambda: {"format_mode": rng.choice([m for m in ("fixed", "free", "auto") if m != parent.format_mode])}))

    # swap the instruction block for a variant the parent isn't already using
    def prompt_move():
        cands = [p for p in _PROMPT_VARIANTS if p.strip() != parent.instructions.strip()]
        return {"instructions": rng.choice(cands)} if cands else {"temperature": 0.1}
    moves.append(("instructions", prompt_move))

    # Honour the "never a no-op" contract: try moves (shuffled) until one
    # actually changes a field. Boundary clamps (top_k at a limit,
    # repair_attempts already 5, temp jitter landing on the same value) can
    # yield an empty diff — those are skipped, not emitted.
    order = list(moves)
    rng.shuffle(order)
    for label, fn in order:
        changes = {k: v for k, v in fn().items() if getattr(parent, k) != v}
        if changes:
            return changes, f"heuristic:{label} -> {json.dumps(changes)[:120]}"
    # Every knob is pinned at a boundary — force a guaranteed-different move.
    forced = 0.1 if parent.temperature != 0.1 else 0.3
    return {"temperature": forced}, f"heuristic:temperature(forced) -> {forced}"


# ------------------------------------------------------------------- brain
_META_PROMPT = """You are the mutation operator of a Darwin Godel Machine that improves a \
COBOL coding agent. The agent's frozen local model is fixed; you may only edit \
its SCAFFOLD. Here is the current scaffold (JSON):

{scaffold}

Its recent COBOLEval failures (compiler diagnostics / no-code):
{failures}

Propose ONE targeted change to improve compile+test pass rate. You may change \
only these keys: {evolvable}. Reply with ONLY a JSON object of the changed \
key(s) and a one-line "why". Example: {{"repair_attempts": 3, "why": "..."}}"""


def _brain(parent: Genome, failures: list[str], proposer: str):
    """Ask a strong model for a scaffold edit. `proposer` names the CLI brain."""
    cmd = _brain_cmd(proposer)
    scaffold = json.dumps(parent.evolvable(), indent=2)
    fail_txt = "\n".join(f"- {f[:300]}" for f in failures[:6]) or "- (none captured)"
    prompt = _META_PROMPT.format(
        scaffold=scaffold, failures=fail_txt,
        evolvable=", ".join(Genome.EVOLVABLE),
    )
    out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError(f"brain proposer '{proposer}' failed: {out.stderr[:300]}")
    m = re.search(r"\{.*\}", out.stdout, re.S)
    if not m:
        raise RuntimeError(f"brain proposer '{proposer}' returned no JSON:\n{out.stdout[:300]}")
    obj = json.loads(m.group(0))
    why = obj.pop("why", "")
    changes = {k: v for k, v in obj.items() if k in Genome.EVOLVABLE}
    if not changes:
        raise RuntimeError(f"brain proposer touched no evolvable key: {obj}")
    return changes, f"brain:{proposer} -> {why[:160]}"


def _brain_cmd(proposer: str) -> list[str]:
    table = {
        "claude": ["claude", "-p"],
        "codex":  ["codex", "exec", "-"],
        "kist":   ["kist", "-p", "claude-cli"],
        "local":  ["ollama", "run", "cobol-jeeves-ft"],  # faithful self-reference
    }
    if proposer not in table:
        raise ValueError(f"unknown brain proposer '{proposer}' (have: {list(table)})")
    exe = table[proposer][0]
    if shutil.which(exe) is None:
        raise RuntimeError(f"brain proposer '{proposer}' needs '{exe}' on PATH — "
                           f"use --proposer heuristic to stay fully offline")
    return table[proposer]


# ------------------------------------------------------- failure-targeted
def _targeted(parent: Genome, diagnostics: dict, rng: random.Random):
    """A scaffold move aimed at the parent's DOMINANT compiler-error class, or
    None if there's no useful signal (caller then falls back to heuristic).
    Directives are only appended when not already present — so repeatedly
    hitting the same class doesn't re-emit a no-op."""
    cls = dominant(diagnostics)
    if cls is None:
        return None
    directive = _TARGETED_DIRECTIVES.get(cls)
    if directive and directive not in parent.instructions:
        new = parent.instructions.rstrip() + "\n" + directive
        return {"instructions": new}, f"targeted:{cls} +directive"
    if cls == "flow_mismatch" and parent.repair_attempts < 5:
        # dangling scope terminators are exactly what compiler feedback fixes
        return {"repair_attempts": parent.repair_attempts + 1}, "targeted:flow_mismatch +repair"
    if cls == "no_code":
        if parent.temperature > 0.0:
            return {"temperature": round(max(0.0, parent.temperature - 0.2), 2)}, "targeted:no_code -temp"
        if parent.repair_attempts < 5:
            return {"repair_attempts": parent.repair_attempts + 1}, "targeted:no_code +repair"
    return None


def _diag_to_failures(diagnostics: dict) -> list[str]:
    """Flatten a diagnostics dict into failure strings for a brain proposer."""
    samples = (diagnostics or {}).get("samples") or {}
    counts = (diagnostics or {}).get("counts") or {}
    return [f"[{cls} x{counts.get(cls, '?')}] {txt}" for cls, txt in samples.items()]


# ------------------------------------------------------------------- entry
def propose(parent: Genome, diagnostics: dict, *, proposer: str,
            rng: random.Random) -> Genome:
    """Return a child Genome derived from `parent`.

    heuristic: exploit the dominant failure class ~70% of the time (targeted
    directive), else explore via a guided-random move — targeted-but-not-greedy
    keeps the open-ended search alive. brain: hand the diagnostics to the model."""
    if proposer == "heuristic":
        move = None
        if diagnostics and rng.random() < 0.7:
            move = _targeted(parent, diagnostics, rng)
        changes, notes = move if move else _heuristic(parent, [], rng)
    else:
        changes, notes = _brain(parent, _diag_to_failures(diagnostics), proposer)
    return parent.child(changes, origin=proposer, notes=notes).with_id()

# ======================================================================
# ── module: dgm/loop.py (flattened) ──
# ======================================================================
"""cobol-dgm main loop — the Darwin Godel Machine, closed.

    seed the archive with genome-zero (proven baseline scaffold)
    repeat N times:
        parent  = archive.select_parent()          # open-ended, novelty-aware
        child   = propose(parent, failures)  # self-modify the scaffold
        fitness = evaluate(child)                    # REAL COBOLEval execution
        archive.add(child, fitness)                  # keep it, win or lose

Design commitments (all serve the core goal — a better OFFLINE COBOL model):
  * frozen local model + evolving scaffold (never touches weights)
  * every genome kept (stepping stones), champion tracked separately
  * resumable: archive is a sqlite file; re-running continues the search
  * honest: regressions are logged as regressions, not hidden

PROTOTYPE. Run: python -m dgm.loop --iterations 8 --tasks 12
"""



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
        # Feed the parent's own compiler-failure histogram to the proposer so it
        # can aim at the dominant error class instead of mutating blind.
        parent_diag = arc.get_diagnostics(parent.genome_id)
        child = propose(parent, parent_diag, proposer=args.proposer, rng=rng)

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
