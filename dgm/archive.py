"""DGM archive — open-ended store of every evaluated genome.

The defining DGM property: nothing is thrown away. Regressions are kept as
stepping stones because a worse scaffold can still be the ancestor of the best
one. Parent selection therefore balances performance against under-exploration
(few children) so the search does not collapse onto the current champion —
mirroring the Sakana DGM's novelty-aware sampling.

SQLite-backed so a run is resumable and inspectable: `sqlite3 archive.db`.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
from pathlib import Path

from .evaluate import Fitness
from .genome import Genome

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
