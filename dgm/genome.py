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
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

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
