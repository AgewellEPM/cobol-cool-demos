"""DGM archive — open-ended store of every evaluated genome.

The defining DGM property: nothing is thrown away. Regressions are kept as
stepping stones because a worse scaffold can still be the ancestor of the best
one. Parent selection therefore balances performance against under-exploration
(few children) so the search does not collapse onto the current champion —
mirroring the Sakana DGM's novelty-aware sampling.

SQLite-backed so a run is resumable and inspectable: `sqlite3 archive.db`.
"""
from __future__ import annotations

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
    notes       TEXT
);
"""


class Archive:
    def __init__(self, db_path: Path, rng: random.Random | None = None):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(_SCHEMA)
        self.rng = rng or random.Random(1234)  # deterministic by default

    # ------------------------------------------------------------- writes
    def add(self, g: Genome, fit: Fitness) -> bool:
        """Insert a newly-evaluated genome. Idempotent: re-adding an existing
        genome_id is a no-op (returns False) — never double-counts a parent's
        `children` or rewrites `seq`. A plain INSERT (not INSERT OR REPLACE) so
        the child-accounting below can only ever fire for a genuinely new row."""
        if self.con.execute(
            "SELECT 1 FROM agents WHERE genome_id = ?", (g.genome_id,)
        ).fetchone() is not None:
            return False
        seq = (self.con.execute("SELECT COALESCE(MAX(seq), -1) FROM agents").fetchone()[0]) + 1
        self.con.execute(
            "INSERT INTO agents (genome_id, parent_id, generation, origin, "
            "fingerprint, genome_json, csr, pass_at_1, n_tasks, no_code, "
            "children, seq, notes) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)",
            (g.genome_id, g.parent_id, g.generation, g.origin, g.fingerprint(),
             g.to_json(), fit.csr, fit.pass_at_1, fit.n_tasks, fit.no_code,
             seq, g.notes),
        )
        if g.parent_id:
            self.con.execute(
                "UPDATE agents SET children = children + 1 WHERE genome_id = ?",
                (g.parent_id,),
            )
        self.con.commit()
        return True

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
