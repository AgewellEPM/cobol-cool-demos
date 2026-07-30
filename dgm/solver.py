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
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .genome import Genome

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


def _score(query_toks, text: str) -> int:
    body = text.lower()
    return sum(body.count(t) for t in set(query_toks))


def _load_peels(query_toks, k: int):
    if not PEELS.exists():
        return []
    scored = []
    for line in PEELS.read_text().splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        if "cobol" not in json.dumps(p)[:2000].lower():
            continue
        rule = p.get("title") or p.get("rule") or ""
        s = _score(query_toks, rule)
        if s > 0:
            scored.append((s, p.get("id", "?"), rule))
    scored.sort(reverse=True)
    return scored[:k]


def _load_atoms(query_toks, k: int):
    if not FLOOR.exists():
        return []
    con = sqlite3.connect(f"file:{FLOOR}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT subject, relation_type, object FROM typed_relations "
            "WHERE subject LIKE '%cobol%' OR object LIKE '%cobol%'"
        ).fetchall()
    finally:
        con.close()
    scored = []
    for s, r, o in rows:
        sc = _score(query_toks, f"{s} {r} {o}")
        if sc > 0:
            scored.append((sc, f"{s} {r.replace('_', ' ')} {o}"))
    scored.sort(reverse=True)
    return scored[:k]


def build_prompt(g: Genome, task_prompt: str) -> str:
    """Genome instructions + (optional) RAG grounding + the COBOL skeleton."""
    parts = [g.instructions.strip(), ""]
    if g.use_peels or g.use_atoms:
        q = _tokens(task_prompt)
        if g.use_peels:
            for _, pid, rule in _load_peels(q, g.top_k_peels):
                parts.append(f"- GROUNDING [{pid}] {rule}")
        if g.use_atoms:
            for _, fact in _load_atoms(q, g.top_k_atoms):
                parts.append(f"- GROUNDING {fact}")
        parts.append("")
    parts.append("```cobol\n" + task_prompt + "\n```")
    return "\n".join(parts)


# ------------------------------------------------------------------- generation
def ask(model: str, messages, temperature: float, timeout: int = 300) -> str:
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps({
            "model": model, "messages": messages,
            "options": {"temperature": temperature}, "stream": False,
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
def solve_task(g: Genome, task_prompt: str, gen_timeout: int = 300) -> str:
    """Run the full genome pipeline; return the final (repaired) completion.

    Raises on transport failure so the evaluator can score the task as failed
    rather than silently swallowing a broken run."""
    messages = [{"role": "user", "content": build_prompt(g, task_prompt)}]
    reply = ask(g.model, messages, g.temperature, gen_timeout)
    completion = extract(reply, g)

    for _ in range(g.repair_attempts):
        ok, diag = cobc_gate(completion, g.format_mode)
        if ok:
            break
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user",
                         "content": g.repair_prompt.format(diagnostics=diag)})
        reply = ask(g.model, messages, g.temperature, gen_timeout)
        completion = extract(reply, g)
    return completion
