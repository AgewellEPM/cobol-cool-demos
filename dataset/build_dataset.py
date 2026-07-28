#!/usr/bin/env python3
"""R2 dataset builder — cobc-verified COBOL instruction pairs.

Every pair's code side is verified at build time:
  * drills:    generated subprogram + generated caller are compiled AND RUN;
               the printed result must equal a Python-computed expected value
               (functional triplet verification, KODCODE-style)
  * mutations: the broken side must FAIL to compile (asserted), the fixed
               side is the already-verified original
  * peels/atoms/fighter: answers are the proven rule texts / real diagnostics
               from this machine (compile-checked where they contain programs)

Outputs (chat JSONL for mlx_lm.lora):
  dataset/train.jsonl, dataset/valid.jsonl   — {"messages": [...]} only
  dataset/provenance.jsonl                   — parallel source/verify records
  dataset/stats.json
"""
import json
import random
import re
import sqlite3
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PEELS = Path.home() / ".perslis" / "peels.jsonl"
FLOOR = Path.home() / ".perslis" / "legacy_floor.db"
PROOFS = Path.home() / "perslis-dos-snake" / "docs" / "cobol-game-proofs"

rng = random.Random(20260728)  # deterministic build

# ----------------------------------------------------------------- helpers

def cobc(args, cwd):
    return subprocess.run(["cobc", *args], cwd=cwd, capture_output=True, text=True)


def compile_ok(source, free=False):
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "p.cbl"
        f.write_text(source)
        r = cobc(["-fsyntax-only", "-w", *(["-free"] if free else ["-fformat=variable"]), "p.cbl"], td)
        return r.returncode == 0, r.stderr.strip()


def run_pair(sub_src, caller_src, free=False):
    """Compile subprogram+caller, run, return (ok, stdout, stderr)."""
    fmt = "-free" if free else "-fformat=variable"
    with tempfile.TemporaryDirectory() as td:
        Path(td, "sub.cbl").write_text(sub_src)
        Path(td, "main.cbl").write_text(caller_src)
        r = cobc(["-w", fmt, "-x", "main.cbl", "sub.cbl", "-o", "run"], td)
        if r.returncode != 0:
            return False, "", r.stderr
        try:
            e = subprocess.run(["./run"], cwd=td, capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            return False, "", "timeout"
        return e.returncode == 0, e.stdout.strip(), e.stderr


def to_free_format(src):
    """Mechanical fixed→free conversion: drop the 7-column sequence/indicator
    prefix, keeping relative indentation (comment lines become *> form)."""
    out = []
    for l in src.split("\n"):
        if len(l) > 6 and l[6] == "*":
            out.append("*> " + l[7:].lstrip())
        elif l.startswith("       "):
            out.append(l[7:])
        else:
            out.append(l)
    return "\n".join(out)


PAIRS, PROV = [], []


def add(instruction, answer, source, verify):
    PAIRS.append({"messages": [
        {"role": "user", "content": instruction},
        {"role": "assistant", "content": answer},
    ]})
    PROV.append({"idx": len(PAIRS) - 1, "source": source, "verify": verify})


# ----------------------------------------------------------- drill factory
# The COBOLEval / real-world subprogram shape: LINKAGE + PROCEDURE DIVISION
# USING, result in RESULT. Targets R1's exact failure modes: section order,
# 01/77 level discipline, final period before END PROGRAM.

NAME_BANK = [
    ("ACCT-TOTALS", "account totals"), ("SENSOR-READS", "sensor readings"),
    ("SCORE-TAB", "game scores"), ("QTY-ON-HAND", "stock quantities"),
    ("DAILY-TEMPS", "daily temperatures"), ("TXN-AMTS", "transaction amounts"),
]

TABLE_OPS = {
    "sum":   ("compute the sum of", lambda v: sum(v)),
    "max":   ("find the largest value in", lambda v: max(v)),
    "min":   ("find the smallest value in", lambda v: min(v)),
    "count-neg": ("count how many entries are negative in", lambda v: sum(1 for x in v if x < 0)),
    "count-over": ("count how many entries exceed 100 in", lambda v: sum(1 for x in v if x > 100)),
    "range": ("compute max minus min of", lambda v: max(v) - min(v)),
    "sum-abs": ("compute the sum of absolute values of", lambda v: sum(abs(x) for x in v)),
    "avg": ("compute the integer average (truncated toward zero) of", lambda v: int(sum(v) / len(v))),
    "idx-max": ("find the 1-based index of the first largest value in", lambda v: v.index(max(v)) + 1),
}


def drill_subprogram(pid, field, n, op_key):
    """Generate a fixed-format subprogram implementing op over an OCCURS table."""
    body = {
        "sum": ["           MOVE 0 TO RESULT",
                "           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > {n}",
                "               ADD L-TAB(WS-I) TO RESULT",
                "           END-PERFORM"],
        "max": ["           MOVE L-TAB(1) TO RESULT",
                "           PERFORM VARYING WS-I FROM 2 BY 1 UNTIL WS-I > {n}",
                "               IF L-TAB(WS-I) > RESULT",
                "                   MOVE L-TAB(WS-I) TO RESULT",
                "               END-IF",
                "           END-PERFORM"],
        "min": ["           MOVE L-TAB(1) TO RESULT",
                "           PERFORM VARYING WS-I FROM 2 BY 1 UNTIL WS-I > {n}",
                "               IF L-TAB(WS-I) < RESULT",
                "                   MOVE L-TAB(WS-I) TO RESULT",
                "               END-IF",
                "           END-PERFORM"],
        "count-neg": ["           MOVE 0 TO RESULT",
                "           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > {n}",
                "               IF L-TAB(WS-I) < 0",
                "                   ADD 1 TO RESULT",
                "               END-IF",
                "           END-PERFORM"],
        "count-over": ["           MOVE 0 TO RESULT",
                "           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > {n}",
                "               IF L-TAB(WS-I) > 100",
                "                   ADD 1 TO RESULT",
                "               END-IF",
                "           END-PERFORM"],
        "range": ["           MOVE L-TAB(1) TO WS-MAX",
                "           MOVE L-TAB(1) TO WS-MIN",
                "           PERFORM VARYING WS-I FROM 2 BY 1 UNTIL WS-I > {n}",
                "               IF L-TAB(WS-I) > WS-MAX",
                "                   MOVE L-TAB(WS-I) TO WS-MAX",
                "               END-IF",
                "               IF L-TAB(WS-I) < WS-MIN",
                "                   MOVE L-TAB(WS-I) TO WS-MIN",
                "               END-IF",
                "           END-PERFORM",
                "           COMPUTE RESULT = WS-MAX - WS-MIN"],
        "sum-abs": ["           MOVE 0 TO RESULT",
                "           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > {n}",
                "               IF L-TAB(WS-I) < 0",
                "                   SUBTRACT L-TAB(WS-I) FROM RESULT",
                "               ELSE",
                "                   ADD L-TAB(WS-I) TO RESULT",
                "               END-IF",
                "           END-PERFORM"],
        "avg": ["           MOVE 0 TO WS-SUM",
                "           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > {n}",
                "               ADD L-TAB(WS-I) TO WS-SUM",
                "           END-PERFORM",
                "           COMPUTE RESULT = WS-SUM / {n}"],
        "idx-max": ["           MOVE 1 TO RESULT",
                "           PERFORM VARYING WS-I FROM 2 BY 1 UNTIL WS-I > {n}",
                "               IF L-TAB(WS-I) > L-TAB(RESULT)",
                "                   MOVE WS-I TO RESULT",
                "               END-IF",
                "           END-PERFORM"],
    }[op_key]
    extra_ws = ""
    if op_key == "range":
        extra_ws = (f"       01 WS-MAX PIC {field}.\n"
                    f"       01 WS-MIN PIC {field}.\n")
    if op_key == "avg":
        extra_ws = "       01 WS-SUM PIC S9(9).\n"
    body_txt = "\n".join(l.format(n=n) for l in body)
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {pid}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-I PIC 9(4).
{extra_ws}       LINKAGE SECTION.
       01 LINKED-ITEMS.
           05 L-TAB OCCURS {n} TIMES PIC {field}.
           05 RESULT PIC S9(9).
       PROCEDURE DIVISION USING LINKED-ITEMS.
{body_txt}
           GOBACK.
       END PROGRAM {pid}.
"""


def drill_caller(pid, n, values):
    moves = "\n".join(
        f"           MOVE {v} TO L-TAB({i + 1})" for i, v in enumerate(values)
    )
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {pid}-CALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 LINKED-ITEMS.
           05 L-TAB OCCURS {n} TIMES PIC S9(5).
           05 RESULT PIC S9(9).
       01 SHOW PIC +9(9).
       PROCEDURE DIVISION.
{moves}
           CALL "{pid}" USING LINKED-ITEMS
           MOVE RESULT TO SHOW
           DISPLAY SHOW
           STOP RUN.
"""


def drill_instructions(pid, phrase, n, fdesc, fmt):
    fmt_word = "fixed-format" if fmt == "fixed" else "free-format (cobc -x -free)"
    spec = (
        f"Write a {fmt_word} GnuCOBOL 3.2 subprogram named {pid} that "
        f"{phrase} a table of {n} signed integers ({fdesc}, PIC S9(5)) "
        f"passed via LINKAGE, storing the answer in the RESULT field. "
        f"Use the standard LINKED-ITEMS shape: 05 L-TAB OCCURS {n} TIMES "
        f"PIC S9(5), then 05 RESULT PIC S9(9). PROCEDURE DIVISION USING "
        f"LINKED-ITEMS; end with END PROGRAM."
    )
    casual = (
        f"I need a callable COBOL routine ({fmt_word}, GnuCOBOL 3.2). The caller "
        f"passes LINKED-ITEMS with {n} {fdesc} entries (PIC S9(5), OCCURS table "
        f"named L-TAB) plus a RESULT field (PIC S9(9)). Make PROGRAM-ID {pid} "
        f"{phrase} the table and put the answer in RESULT. Mind the rules: "
        f"WORKING-STORAGE before LINKAGE, 01/77 levels at root, and terminate "
        f"the final statement with a period before END PROGRAM."
    )
    return [("spec", spec), ("casual", casual)]


def build_drills():
    made = failed = 0
    for op_key, (phrase, pyfn) in TABLE_OPS.items():
        for n in (5, 6, 8, 10, 12):
            for fname, fdesc in rng.sample(NAME_BANK, 4):
                pid = f"{fname[:12].replace('-', '')[:8]}-{op_key.upper().replace('-', '')[:8]}-{n}"
                sub = drill_subprogram(pid, "S9(5)", n, op_key)
                values = [rng.randint(-400, 400) for _ in range(n)]
                # ensure count ops have interesting values
                if op_key == "count-over":
                    values = [rng.randint(-50, 300) for _ in range(n)]
                caller = drill_caller(pid, n, values)
                expected = pyfn(values)

                for fmt in ("fixed", "free"):
                    s = sub if fmt == "fixed" else to_free_format(sub)
                    c = caller if fmt == "fixed" else to_free_format(caller)
                    ok, out, err = run_pair(s, c, free=(fmt == "free"))
                    got = int(out.replace("+", "")) if ok and out else None
                    if not ok or got != expected:
                        failed += 1
                        continue
                    for style, instr in drill_instructions(pid, phrase, n, fdesc, fmt):
                        add(instr, f"```cobol\n{s}```",
                            f"drill:{op_key}:{fmt}:{style}",
                            {"kind": "run-verified", "expected": expected, "got": got})
                        made += 1
    return made, failed


# ------------------------------------------------------ string drill family

STR_OPS = {
    "length": ("return the length (excluding trailing spaces) of",
               lambda s: len(s.rstrip())),
    "count-char": ("count occurrences of the character 'A' in",
                   lambda s: s.count("A")),
    "count-vowels": ("count the vowels (A E I O U) in",
                     lambda s: sum(1 for c in s if c in "AEIOU")),
}

STR_SAMPLES = ["BANANA REPORT", "ACCOUNT AA", "MAINFRAME", "COBOL RULES",
               "ABEND CODE A", "VSAM MASTER", "AAA", "LEDGER BATCH"]


def str_subprogram(pid, op_key):
    body = {
        "length": [
            "           MOVE FUNCTION STORED-CHAR-LENGTH (L-STR) TO RESULT"],
        "count-char": [
            "           MOVE 0 TO RESULT",
            "           INSPECT L-STR TALLYING RESULT",
            "               FOR ALL \"A\""],
        "count-vowels": [
            "           MOVE 0 TO RESULT",
            "           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 20",
            "               IF L-STR(WS-I:1) = \"A\" OR L-STR(WS-I:1) = \"E\"",
            "                   OR L-STR(WS-I:1) = \"I\"",
            "                   OR L-STR(WS-I:1) = \"O\"",
            "                   OR L-STR(WS-I:1) = \"U\"",
            "                   ADD 1 TO RESULT",
            "               END-IF",
            "           END-PERFORM"],
    }[op_key]
    ws = "       01 WS-I PIC 9(4).\n" if op_key == "count-vowels" else ""
    body_txt = "\n".join(body)
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {pid}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
{ws}       LINKAGE SECTION.
       01 LINKED-ITEMS.
           05 L-STR PIC X(20).
           05 RESULT PIC S9(9).
       PROCEDURE DIVISION USING LINKED-ITEMS.
{body_txt}
           GOBACK.
       END PROGRAM {pid}.
"""


def str_caller(pid, text):
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {pid}-CALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 LINKED-ITEMS.
           05 L-STR PIC X(20).
           05 RESULT PIC S9(9).
       01 SHOW PIC +9(9).
       PROCEDURE DIVISION.
           MOVE "{text}" TO L-STR
           CALL "{pid}" USING LINKED-ITEMS
           MOVE RESULT TO SHOW
           DISPLAY SHOW
           STOP RUN.
"""


def build_string_drills():
    made = failed = 0
    for op_key, (phrase, pyfn) in STR_OPS.items():
        for text in STR_SAMPLES:
            pid = f"STR-{op_key.upper().replace('-', '')[:9]}-{sum(map(ord, text)) % 97}"
            sub = str_subprogram(pid, op_key)
            caller = str_caller(pid, text)
            expected = pyfn(text.ljust(20))
            for fmt in ("fixed", "free"):
                s = sub if fmt == "fixed" else to_free_format(sub)
                c = caller if fmt == "fixed" else to_free_format(caller)
                ok, out, err = run_pair(s, c, free=(fmt == "free"))
                got = int(out.replace("+", "")) if ok and out else None
                if not ok or got != expected:
                    failed += 1
                    continue
                fmt_word = "fixed-format" if fmt == "fixed" else "free-format (cobc -x -free)"
                instr = (
                    f"Write a {fmt_word} GnuCOBOL 3.2 subprogram named {pid} that "
                    f"{phrase} a PIC X(20) text field passed via LINKAGE "
                    f"(05 L-STR PIC X(20), then 05 RESULT PIC S9(9) under "
                    f"LINKED-ITEMS), storing the count in RESULT. "
                    f"PROCEDURE DIVISION USING LINKED-ITEMS; end with END PROGRAM."
                )
                add(instr, f"```cobol\n{s}```", f"strdrill:{op_key}:{fmt}",
                    {"kind": "run-verified", "expected": expected, "got": got})
                made += 1
    return made, failed


# ------------------------------------------------------- mutation factory

def swap_sections(src):
    """Move WORKING-STORAGE after LINKAGE — the invalid order that dominated
    R1 failures (and that the COBOLEval skeleton itself invites)."""
    lines = src.split("\n")
    try:
        ws = next(i for i, l in enumerate(lines) if "WORKING-STORAGE SECTION" in l)
        ls = next(i for i, l in enumerate(lines) if "LINKAGE SECTION" in l)
        pd = next(i for i, l in enumerate(lines) if "PROCEDURE DIVISION" in l)
    except StopIteration:
        return src
    if not (ws < ls < pd):
        return src
    return "\n".join(lines[:ws] + lines[ls:pd] + lines[ws:ls] + lines[pd:])


def mutate_pairs():
    """Take verified fixed-format drill sources and derive broken→fixed
    pairs. Broken side must FAIL to compile (asserted, per-site)."""
    made = 0
    per_class = {}
    CLASS_CAP = 90
    drill_idxs = [p["idx"] for p in PROV
                  if p["source"].startswith("drill:") and ":fixed:spec" in p["source"]]
    rng.shuffle(drill_idxs)
    for idx in drill_idxs:
        src = re.search(r"```cobol\n(.*?)```", PAIRS[idx]["messages"][1]["content"], re.S).group(1)

        muts = [
            # R1 failure class: final period dropped
            ("missing-period", src.replace("           GOBACK.\n", "           GOBACK\n")),
            # R1's dominant failure class: 05 at root in WORKING-STORAGE
            ("level-05-at-root", src.replace("       01 WS-I PIC 9(4).", "       05 WS-I PIC 9(4).")),
            # reserved word as data name
            ("reserved-word", src.replace("WS-I", "SUM")),
            # R1 killer: WORKING-STORAGE after LINKAGE
            ("section-order", swap_sections(src)),
            # unterminated loop body
            ("missing-end-perform", src.replace("           END-PERFORM\n", "\n", 1)),
        ]
        for tag, broken in muts:
            if per_class.get(tag, 0) >= CLASS_CAP or broken == src:
                continue
            ok, err = compile_ok(broken)
            if ok:
                continue  # mutation didn't break it — skip, never lie
            first_err = next((l for l in err.splitlines() if "error:" in l), err[:200])
            instr = (
                "This GnuCOBOL 3.2 subprogram fails to compile. cobc says:\n\n"
                f"{first_err}\n\n"
                "Fix it and reply with the complete corrected program in one "
                "```cobol block.\n\n```cobol\n" + broken + "```"
            )
            add(instr, f"```cobol\n{src}```", f"mutation:{tag}",
                {"kind": "broken-fails-fixed-passes", "error": first_err[:160]})
            per_class[tag] = per_class.get(tag, 0) + 1
            made += 1
    return made


# ---------------------------------------------------- peel / atom / fighter

def peel_pairs():
    made = 0
    q_templates = {
        "peel-renderer-recipe-cobol-raw-rgb24": "How do I render video frames from GnuCOBOL with no graphics library?",
        "peel-self-heal-cobol-shared-counter": "My GnuCOBOL program pegs the CPU at 100% and writes nothing. A paragraph inside my PERFORM VARYING loop also loops. What is the classic cause?",
        "peel-self-heal-cobol-goto-perform-range": "In GnuCOBOL, my program exits after one iteration and files end up unclosed. I use GO TO to jump to an exit paragraph. What is wrong?",
        "peel-data-format-cobol-comp3": "How are mainframe-style fixed-width bank records with COMP-3 amounts laid out, and how should I parse them?",
        "peel-api-contract-cobol-bank-reconcile": "How should a GnuCOBOL banking reconciler expose its outcome so it can be verified independently of log text?",
        "peel-capability-cobol-perslis-run-lane": "How do I build and run a COBOL program through Perslis and prove it actually ran?",
        "peel-capability-cobol-ansi256-raster": "How do I draw color graphics in a terminal from GnuCOBOL?",
        "peel-capability-cobol-fixed-point-trig": "Can GnuCOBOL do the trigonometry needed for a raycaster without floating point?",
        "peel-data-format-cobol-sprite-bitmap": "How do I store and sample a 2D sprite bitmap in COBOL?",
        "peel-capability-cobol-raycast-dda": "How do I march a ray across a grid map in GnuCOBOL for a pseudo-3D view?",
        "peel-capability-cobol-first-person-shooter": "Is a first-person shooter feasible in GnuCOBOL, and what are the key constructs?",
        "cobol-vsam-ksds-keyed-access": "What keyed-access behaviour does GnuCOBOL ORGANIZATION INDEXED (KSDS) guarantee?",
        "cobol-esql-sqlite-cursor": "Can EXEC SQL COBOL with cursors run on Apple Silicon, and how is it verified?",
    }
    for line in PEELS.read_text().splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        pid = p.get("id", "")
        if pid not in q_templates:
            continue
        rule = p.get("title") or p.get("rule") or ""
        add(q_templates[pid], rule, f"peel:{pid}", {"kind": "proven-peel"})
        made += 1
    return made


def atom_pairs():
    con = sqlite3.connect(f"file:{FLOOR}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT DISTINCT subject, relation_type, object FROM typed_relations "
        "WHERE subject LIKE '%cobol%' OR object LIKE '%cobol%'").fetchall()
    con.close()
    q_by_rel = {
        "produces": "What does {s} produce?",
        "prevents": "What does {s} prevent?",
        "requires": "What does {s} require?",
        "is_a": "What kind of thing is {s}?",
        "runs_on": "What does {s} run on?",
        "used_for": "What is {s} used for?",
        "composed_of": "What is {s} composed of?",
        "can_do": "What can {s} do?",
        "belongs_to": "What does {s} belong to?",
        "depends_on": "What does {s} depend on?",
        "packs_to": "What does {s} pack to in storage?",
        "part_of": "What is {s} part of?",
        "differs_from": "What does {s} differ from?",
        "enables": "What does {s} enable?",
        "instance_of": "What is {s} an instance of?",
        "works_in": "Where does {s} work?",
    }
    a_by_rel = {
        "produces": "{s} produces {o}.",
        "prevents": "{s} prevents {o}.",
        "requires": "{s} requires {o}.",
        "is_a": "{s} is a {o}.",
        "runs_on": "{s} runs on {o}.",
        "used_for": "{s} is used for {o}.",
        "composed_of": "{s} is composed of {o}.",
        "can_do": "{s} can {o}.",
        "belongs_to": "{s} belongs to {o}.",
        "depends_on": "{s} depends on {o}.",
        "packs_to": "{s} packs to {o}.",
        "part_of": "{s} is part of {o}.",
        "differs_from": "{s} differs from {o}.",
        "enables": "{s} enables {o}.",
        "instance_of": "{s} is an instance of {o}.",
        "works_in": "{s} works in {o}.",
    }
    made = 0
    for s, r, o in rows:
        if r not in q_by_rel:
            continue
        add(q_by_rel[r].format(s=s), a_by_rel[r].format(s=s, o=o),
            f"atom:{r}", {"kind": "floor-atom"})
        made += 1
    return made


FIGHTER_TRIPLETS = [
    ("A GnuCOBOL program spins at 100% CPU forever and its output file is "
     "never even created. It has:\n\n```cobol\n       01 T-I PIC 9(2).\n...\n"
     "       PERFORM VARYING T-I FROM 1 BY 1 UNTIL T-I > 200\n"
     "           MOVE \"000\" TO FONT-ROW (T-I)\n       END-PERFORM\n```\n\n"
     "What is wrong and what is the fix?",
     "The loop counter T-I is PIC 9(2): its maximum value is 99. Standard "
     "COBOL arithmetic truncates on overflow, so T-I wraps 99 back toward 0 "
     "and `T-I > 200` is never true — the loop never terminates, and since "
     "this runs before the output file is OPENed, the program spins with "
     "zero bytes written. Fix: widen the counter so it can exceed the "
     "bound — `01 T-I PIC 9(3).` The rule: a PERFORM VARYING counter's PIC "
     "must be wide enough to pass its UNTIL bound. (Observed for real in "
     "FIGHTER.cob's LOAD-FONT, 2026-07-28.)"),
    ("GnuCOBOL 3.2 rejects this line with a syntax error:\n\n```cobol\n"
     "           PERFORM VARYING T-I FROM 1 BY 1\n"
     "                   UNTIL T-I > FUNCTION LENGTH (FUNCTION TRIM (M-BANNER))\n"
     "```\n\nWhy, and what is the portable fix?",
     "GnuCOBOL 3.2 does not parse a nested intrinsic call in that position — "
     "FUNCTION LENGTH(FUNCTION TRIM(...)) fails with a syntax error. Move the "
     "trimmed value to a temporary first and use STORED-CHAR-LENGTH:\n\n"
     "```cobol\n           MOVE FUNCTION TRIM (M-BANNER) TO T-BANNER\n"
     "           MOVE FUNCTION STORED-CHAR-LENGTH (T-BANNER) TO T-BLEN\n"
     "           PERFORM VARYING T-I FROM 1 BY 1 UNTIL T-I > T-BLEN\n```\n\n"
     "(Observed for real in FIGHTER.cob's DRAW-BANNER, 2026-07-28.)"),
    ("A COBOL paragraph does `GO TO BANNER-EXIT` for an early return, and "
     "BANNER-EXIT is the next paragraph with just EXIT. Callers invoke it "
     "with `PERFORM DRAW-BANNER`. Sometimes control falls through into the "
     "following paragraphs. Why, and what is the fix?",
     "`PERFORM DRAW-BANNER` sets its return point at the end of DRAW-BANNER "
     "only. The GO TO jumps to BANNER-EXIT, which is OUTSIDE that range, so "
     "the return point is never reached — after BANNER-EXIT ends, control "
     "falls through into whatever paragraph comes next (in the real case, "
     "DRAW-CHAR ran with stale arguments). Fix every call site to name the "
     "range: `PERFORM DRAW-BANNER THRU BANNER-EXIT`. Rule: never GO TO a "
     "paragraph outside a simple PERFORM's range; either use THRU or a "
     "flag-driven fall-through. (Observed for real in FIGHTER.cob — four "
     "paragraphs had this bug, 2026-07-28.)"),
]


def fighter_pairs():
    for q, a in FIGHTER_TRIPLETS:
        add(q, a, "fighter:bug-fix", {"kind": "real-session-diagnostic"})
    return len(FIGHTER_TRIPLETS)


def proof_program_pairs():
    made = 0
    briefs = {
        "peel-capability-cobol-fixed-point-trig.cob":
            "Write a free-format GnuCOBOL program that proves FUNCTION SIN/COS/ATAN "
            "over PIC S9V9(5) fixed-point storage give correct unit vectors "
            "(sin 60° = 0.86602, cos 60° = 0.49999, atan 1 = 0.78539) and reports "
            "success through RETURN-CODE.",
        "peel-data-format-cobol-sprite-bitmap.cob":
            "Write a free-format GnuCOBOL program that stores a 2D sprite bitmap as "
            "FILLER rows under a group item, REDEFINES it into an indexable row "
            "table, samples texels with reference modification, and proves the "
            "sampling through RETURN-CODE.",
        "peel-capability-cobol-ansi256-raster.cob":
            "Write a free-format GnuCOBOL program that renders a color raster in the "
            "terminal using ANSI 256-color background escape cells built with STRING "
            "WITH POINTER, and resets the screen afterwards.",
        "peel-capability-cobol-raycast-dda.cob":
            "Write a free-format GnuCOBOL program that marches a ray across an OCCURS "
            "grid map with fixed depth steps (DDA-style) and proves the hit distance "
            "through RETURN-CODE.",
    }
    for fname, brief in briefs.items():
        f = PROOFS / fname
        if not f.exists():
            continue
        src = f.read_text()
        if len(src) > 9000:
            continue
        ok, err = compile_ok(src, free=True)
        if not ok:
            continue
        add(brief, f"```cobol\n{src}```", f"proof:{fname}",
            {"kind": "compile-verified", "free_format": True})
        made += 1
    return made


# ------------------------------------------------------------------- main

def main():
    counts = {}
    counts["drills"], counts["drill_rejects"] = build_drills()
    counts["str_drills"], counts["str_rejects"] = build_string_drills()
    counts["mutations"] = mutate_pairs()
    counts["peels"] = peel_pairs()
    counts["atoms"] = atom_pairs()
    counts["fighter"] = fighter_pairs()
    counts["proof_programs"] = proof_program_pairs()

    idx = list(range(len(PAIRS)))
    rng.shuffle(idx)
    n_valid = max(1, len(idx) // 20)
    valid_set = set(idx[:n_valid])

    with (HERE / "train.jsonl").open("w") as tr, (HERE / "valid.jsonl").open("w") as va:
        for i, pair in enumerate(PAIRS):
            (va if i in valid_set else tr).write(json.dumps(pair) + "\n")
    with (HERE / "provenance.jsonl").open("w") as pv:
        for rec in PROV:
            pv.write(json.dumps(rec) + "\n")

    counts["total"] = len(PAIRS)
    counts["train"] = len(PAIRS) - n_valid
    counts["valid"] = n_valid
    (HERE / "stats.json").write_text(json.dumps(counts, indent=2))
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
