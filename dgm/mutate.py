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
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
from dataclasses import asdict

from .genome import Genome

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


# ------------------------------------------------------------------- entry
def propose(parent: Genome, failures: list[str], *, proposer: str,
            rng: random.Random) -> Genome:
    """Return a child Genome derived from `parent` via the chosen proposer."""
    if proposer == "heuristic":
        changes, notes = _heuristic(parent, failures, rng)
    else:
        changes, notes = _brain(parent, failures, proposer)
    return parent.child(changes, origin=proposer, notes=notes).with_id()
