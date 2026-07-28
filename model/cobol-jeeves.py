#!/usr/bin/env python3
"""cobol-jeeves — offline COBOL model wrapper (TinkyMind pattern).

Retrieval-grounded chat over the local cobol-jeeves Ollama model:
  * scores the 13 proven COBOL peels (~/.perslis/peels.jsonl) against the query
  * scores typed atoms from the legacy floor (~/.perslis/legacy_floor.db)
  * injects the top-k as GROUNDING (compiler-verified facts) into the prompt
  * --check extracts the first COBOL block from the reply and gates it
    through cobc; the compile verdict is printed, never assumed.

Fully offline: talks only to localhost:11434. Fails fast on missing pieces.
"""
import argparse
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

OLLAMA = "http://localhost:11434/api/chat"
MODEL = "cobol-jeeves"
PEELS = Path.home() / ".perslis" / "peels.jsonl"
FLOOR = Path.home() / ".perslis" / "legacy_floor.db"
TOP_K_PEELS = 4
TOP_K_ATOMS = 6

STOP = frozenset(
    "a an and are as at be by for from how in is it of on or that the to "
    "what when with write me i you can please program cobol".split()
)


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9-]+", text.lower()) if t not in STOP]


def score(query_toks, text):
    body = text.lower()
    return sum(body.count(t) for t in set(query_toks))


def load_peels(query_toks):
    if not PEELS.exists():
        sys.exit(f"FATAL: {PEELS} missing — peels are the grounding corpus")
    scored = []
    for line in PEELS.read_text().splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        blob = json.dumps(p)[:2000]
        if "cobol" not in blob.lower():
            continue
        rule = p.get("title") or p.get("rule") or ""
        s = score(query_toks, rule)
        if s > 0:
            scored.append((s, p.get("id", "?"), rule))
    scored.sort(reverse=True)
    return scored[:TOP_K_PEELS]


def load_atoms(query_toks):
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
        sc = score(query_toks, f"{s} {r} {o}")
        if sc > 0:
            scored.append((sc, f"{s} {r.replace('_', ' ')} {o}"))
    scored.sort(reverse=True)
    return scored[:TOP_K_ATOMS]


def build_prompt(query):
    q = tokens(query)
    peels = load_peels(q)
    atoms = load_atoms(q)
    parts = []
    if peels:
        parts.append("GROUNDING — compiler-verified rules from this machine:")
        parts += [f"- [{pid}] {rule}" for _, pid, rule in peels]
    if atoms:
        parts.append("GROUNDING — known facts:")
        parts += [f"- {fact}" for _, fact in atoms]
    parts.append(f"TASK: {query}")
    return "\n".join(parts), [pid for _, pid, _ in peels]


def ask(messages):
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps(
            {"model": MODEL, "messages": messages, "stream": False}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.load(resp)["message"]["content"]
    except urllib.error.URLError as e:
        sys.exit(f"FATAL: Ollama unreachable at localhost:11434 ({e}). Run: ollama serve")


def cobc_check(reply):
    m = re.search(r"```(?:cobol)?\n(.*?)```", reply, re.S)
    if not m:
        return "NO-CODE-BLOCK: nothing to compile"
    src = m.group(1)
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "gen.cob"
        f.write_text(src)
        fails = []
        # fixed first (col 72 rules apply), then free (columns ignored) —
        # pass on either, report which one took.
        for label, extra in (("fixed", []), ("free", ["-free"])):
            cmd = ["cobc", "-x", *extra, "-o", str(Path(td) / "gen"), str(f)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                return f"COMPILE-PASS ({label}-format, cobc -x{' -free' if extra else ''})"
            fails.append(f"--- {label}-format ---\n{r.stderr.strip()[:800]}")
        return "COMPILE-FAIL:\n" + "\n".join(fails)


def main():
    ap = argparse.ArgumentParser(description="offline COBOL model, peel-grounded")
    ap.add_argument("query", nargs="+", help="what to ask/build")
    ap.add_argument("--check", action="store_true", help="gate reply code through cobc")
    ap.add_argument(
        "--repair", type=int, default=2, metavar="K",
        help="with --check: feed compiler diagnostics back up to K times (default 2)",
    )
    ap.add_argument("--show-grounding", action="store_true")
    args = ap.parse_args()

    query = " ".join(args.query)
    prompt, peel_ids = build_prompt(query)
    if args.show_grounding:
        print(prompt, "\n" + "=" * 60, file=sys.stderr)
    print(f"[grounded on: {', '.join(peel_ids) or 'system prompt only'}]", file=sys.stderr)

    messages = [{"role": "user", "content": prompt}]
    reply = ask(messages)

    if args.check:
        verdict = cobc_check(reply)
        attempt = 0
        while verdict.startswith("COMPILE-FAIL") and attempt < args.repair:
            attempt += 1
            print(f"[repair {attempt}/{args.repair}] compile failed, feeding "
                  "diagnostics back", file=sys.stderr)
            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": "Your program does NOT compile. cobc says:\n\n"
                + verdict
                + "\n\nFix every error and reply with the complete corrected "
                "program in one ```cobol block. Remember: fixed-format code "
                "must not pass column 72; avoid reserved words (SUM, COUNT, "
                "DATA, ...) as data names.",
            })
            reply = ask(messages)
            verdict = cobc_check(reply)
        print(reply)
        print(f"\n[cobc verdict after {attempt} repair(s)] {verdict}", file=sys.stderr)
        sys.exit(0 if verdict.startswith("COMPILE-PASS") else 3)
    print(reply)


if __name__ == "__main__":
    main()
