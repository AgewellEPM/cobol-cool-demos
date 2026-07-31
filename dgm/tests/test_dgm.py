"""cobol-dgm regression suite — pins the invariants verified during R0-R2.

Pure logic + cobc only (NO model, NO GPU): runs in seconds and guards every
correctness property Codex flagged or that the loop depends on. Run:

    PYTHONPATH=. eval/venv/bin/python -m unittest dgm.tests.test_dgm -v
"""
import os
import random
import tempfile
import unittest
from pathlib import Path

import json

from dgm.archive import Archive
from dgm.diagnostics import classify, classify_error, dominant
from dgm.evaluate import Fitness
from dgm.genome import Genome, seed_genome
from dgm import harvest, mutate

_VALID_COBOL = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n"
                "       PROCEDURE DIVISION.\n           GOBACK.\n       END PROGRAM T.\n")


def _fit(gid, csr=0.2, p=0.0, diag=None):
    return Fitness(gid, 15, csr, p, {}, 0, diag or {})


class TestGenome(unittest.TestCase):
    def test_id_format_and_fingerprint_stable(self):
        g = seed_genome()
        self.assertTrue(g.genome_id.startswith("g000-"))
        self.assertEqual(g.fingerprint(), seed_genome().fingerprint())

    def test_child_rejects_non_evolvable(self):
        g = seed_genome()
        with self.assertRaises(ValueError):
            g.child({"model": "x"}, origin="t", notes="")   # weights are frozen
        with self.assertRaises(ValueError):
            g.child({"generation": 9}, origin="t", notes="")

    def test_child_differs_and_tracks_lineage(self):
        g = seed_genome()
        c = g.child({"temperature": 0.5}, origin="h", notes="n").with_id()
        self.assertNotEqual(c.fingerprint(), g.fingerprint())
        self.assertEqual(c.parent_id, g.genome_id)
        self.assertEqual(c.generation, 1)


class TestArchive(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "a.db"
        self.arc = Archive(self.db)

    def test_add_idempotent_no_double_count(self):
        g = seed_genome()
        c = g.child({"temperature": 0.3}, origin="h", notes="").with_id()
        self.assertTrue(self.arc.add(g, _fit(g.genome_id)))
        self.assertTrue(self.arc.add(c, _fit(c.genome_id, csr=0.3)))
        for _ in range(4):   # the old INSERT-OR-REPLACE double-count path
            self.assertFalse(self.arc.add(c, _fit(c.genome_id, csr=0.9)))
        row = self.arc.con.execute(
            "SELECT children FROM agents WHERE genome_id=?", (g.genome_id,)).fetchone()
        crow = self.arc.con.execute(
            "SELECT csr, seq FROM agents WHERE genome_id=?", (c.genome_id,)).fetchone()
        self.assertEqual(row["children"], 1)          # not re-incremented
        self.assertEqual(crow["csr"], 0.3)            # score not clobbered
        self.assertEqual(crow["seq"], 1)              # seq not rewritten
        self.assertEqual(self.arc.size(), 2)

    def test_best_ordering(self):
        for i, csr in enumerate([0.1, 0.4, 0.4]):
            g = Genome(temperature=0.1 * i).with_id()
            self.arc.add(g, _fit(g.genome_id, csr=csr, p=0.05 * i))
        self.assertAlmostEqual(self.arc.best()["csr"], 0.4)

    def test_select_parent_nonempty_and_weighted(self):
        with self.assertRaises(RuntimeError):
            self.arc.select_parent()                  # empty archive fails loud
        g = seed_genome()
        self.arc.add(g, _fit(g.genome_id))
        self.assertEqual(self.arc.select_parent().genome_id, g.genome_id)

    def test_diagnostics_roundtrip(self):
        g = seed_genome()
        diag = {"counts": {"expr_syntax": 4}, "samples": {}, "n_failed": 4}
        self.arc.add(g, _fit(g.genome_id, diag=diag))
        self.assertEqual(dominant(self.arc.get_diagnostics(g.genome_id)), "expr_syntax")

    def test_migration_adds_column(self):
        # simulate a pre-diagnostics archive by dropping the column
        raw = Path(tempfile.mkdtemp()) / "old.db"
        a = Archive(raw)
        a.add(seed_genome(), _fit("g000-x"))
        a.con.execute("CREATE TABLE t AS SELECT genome_id,parent_id,generation,"
                      "origin,fingerprint,genome_json,csr,pass_at_1,n_tasks,"
                      "no_code,children,seq,notes FROM agents")
        a.con.execute("DROP TABLE agents")
        a.con.execute("ALTER TABLE t RENAME TO agents")
        a.con.commit(); a.close()
        a2 = Archive(raw)   # must migrate, not crash
        cols = {r["name"] for r in a2.con.execute("PRAGMA table_info(agents)")}
        self.assertIn("diagnostics", cols)
        self.assertEqual(a2.size(), 1)


class TestMutate(unittest.TestCase):
    def test_heuristic_never_noop_even_pinned(self):
        pinned = Genome(temperature=0.7, repair_attempts=5, top_k_peels=8,
                        top_k_atoms=10, format_mode="fixed").with_id()
        for s in range(200):
            changes, _ = mutate._heuristic(pinned, [], random.Random(s))
            self.assertTrue(changes)
            for k, v in changes.items():
                self.assertNotEqual(getattr(pinned, k), v)

    def test_targeted_directive_and_idempotent(self):
        g = seed_genome()
        diag = {"counts": {"expr_syntax": 3}, "samples": {}, "n_failed": 3}
        move = mutate._targeted(g, diag, random.Random(0))
        self.assertIsNotNone(move)
        self.assertIn("COMPUTE", move[0]["instructions"])
        child = g.child(move[0], origin="t", notes="").with_id()
        self.assertIsNone(mutate._targeted(child, diag, random.Random(0)))  # no re-append

    def test_propose_never_noop_and_honours_signal(self):
        g = seed_genome()
        diag = {"counts": {"expr_syntax": 5}, "samples": {}, "n_failed": 5}
        targeted = 0
        for s in range(200):
            c = mutate.propose(g, diag, proposer="heuristic", rng=random.Random(s))
            self.assertNotEqual(c.fingerprint(), g.fingerprint())
            targeted += c.notes.startswith("targeted:")
        self.assertGreater(targeted, 100)   # ~70% exploit the signal
        self.assertLess(targeted, 200)      # but still explores

    def test_propose_no_diag_falls_back_to_heuristic(self):
        c = mutate.propose(seed_genome(), {}, proposer="heuristic", rng=random.Random(1))
        self.assertTrue(c.notes.startswith("heuristic:"))


class TestDiagnostics(unittest.TestCase):
    def test_classify_error_specific_before_broad(self):
        # a column/undefined message must not be swallowed by user_function
        self.assertEqual(classify_error("error: 'FOO' requires one subscript"), "subscript_misuse")
        self.assertEqual(classify_error("error: reserved word cannot be used"), "reserved_word")
        self.assertEqual(classify_error("error: syntax error, unexpected ("), "expr_syntax")
        self.assertEqual(classify_error("error: unexpected END-PERFORM"), "flow_mismatch")
        self.assertEqual(classify_error("error: 'ABS' is not defined"), "user_function")
        self.assertEqual(classify_error("error: something totally novel"), "syntax_other")

    def test_dominant_empty(self):
        self.assertIsNone(dominant({}))
        self.assertIsNone(dominant({"counts": {}}))

    def test_classify_real_cobc_on_bad_program(self):
        # end-to-end: a program with C-style inline arithmetic must be flagged
        d = Path(tempfile.mkdtemp())
        (d / "solutions").mkdir()
        (d / "solutions" / "bad.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. BAD.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-I PIC 9.\n"
            "       PROCEDURE DIVISION.\n"
            "           PERFORM VARYING WS-I FROM WS-I + 1 BY 1 UNTIL WS-I > 5\n"
            "           END-PERFORM.\n"
            "           GOBACK.\n"
            "       END PROGRAM BAD.\n"
        )
        out = classify(d)
        self.assertGreaterEqual(out["n_failed"], 1)


class TestHarvest(unittest.TestCase):
    """Tier-B harvest — the contamination guard is the load-bearing test."""

    def _pred_dir(self, root, rows):
        """rows: list of (task_id, completion, all_passed)."""
        d = root / "dgm_x"
        d.mkdir(parents=True)
        (d / "samples.jsonl").write_text("".join(
            json.dumps({"sample_id": 0, "task_id": t, "completion": c}) + "\n"
            for t, c, _ in rows))
        (d / "samples.jsonl_results.jsonl").write_text("".join(
            json.dumps({"task_id": t, "compiled": [p], "all_passed": p}) + "\n"
            for t, _, p in rows))
        return root

    def test_refuses_held_out_and_keeps_pool(self):
        root = self._pred_dir(Path(tempfile.mkdtemp()), [
            ("HumanEval/5",   _VALID_COBOL, True),   # train pool -> keep
            ("HumanEval/120", _VALID_COBOL, True),   # HELD-OUT -> must refuse
        ])
        prompts = {"HumanEval/5": "skel5", "HumanEval/120": "skel120"}
        pairs, prov, stats = harvest.harvest(root, prompts)
        self.assertEqual(stats["unique_pairs"], 1)
        self.assertEqual(stats["held_out_refused"], 1)
        self.assertEqual(prov[0]["task_id"], "HumanEval/5")
        self.assertIn("skel5", pairs[0]["messages"][0]["content"])

    def test_drops_noncompiling_and_failing(self):
        root = self._pred_dir(Path(tempfile.mkdtemp()), [
            ("HumanEval/6", "not cobol at all", True),    # all_passed but won't build
            ("HumanEval/7", _VALID_COBOL, False),          # not all_passed
        ])
        prompts = {"HumanEval/6": "s", "HumanEval/7": "s"}
        pairs, prov, stats = harvest.harvest(root, prompts)
        self.assertEqual(stats["unique_pairs"], 0)
        self.assertEqual(stats["recheck_dropped"], 1)

    def test_split_is_disjoint_and_covers_range(self):
        self.assertLess(harvest.TRAIN_POOL_END, harvest.HELD_OUT_TEST_START)
        self.assertEqual(harvest.HELD_OUT_TEST_START, harvest.TRAIN_POOL_END + 1)

    def test_bad_task_id_shape_fails_loud(self):
        root = self._pred_dir(Path(tempfile.mkdtemp()), [("foo/5", _VALID_COBOL, True)])
        with self.assertRaises(ValueError):   # not HumanEval/<n> -> refuse to split
            harvest.harvest(root, {"foo/5": "s"})

    def test_duplicate_task_id_fails_loud(self):
        d = Path(tempfile.mkdtemp()) / "dgm_x"
        d.mkdir(parents=True)
        (d / "samples.jsonl").write_text(
            json.dumps({"task_id": "HumanEval/5", "completion": _VALID_COBOL}) + "\n" +
            json.dumps({"task_id": "HumanEval/5", "completion": _VALID_COBOL}) + "\n")
        (d / "samples.jsonl_results.jsonl").write_text(
            json.dumps({"task_id": "HumanEval/5", "compiled": [True], "all_passed": True}) + "\n")
        with self.assertRaises(ValueError):   # can't trust pairing
            harvest.harvest(d.parent, {"HumanEval/5": "s"})


if __name__ == "__main__":
    unittest.main()
