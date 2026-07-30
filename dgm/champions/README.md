# cobol-dgm champions

Durable, committed snapshots of the best scaffolds the Darwin Gödel Machine has
discovered. The live search lives in the gitignored `dgm/runs/archive.db`; these
JSON files preserve the *winning genomes* (and the evidence for them) so a swept
run directory never loses the payoff.

## g003_c61b — first evolved champion (2026-07-30)

**Run:** 8 iterations, heuristic (offline) proposer, `cobol-jeeves-ft`, 15-task
evolution window (COBOLEval tasks 0–14).

**Result — head-to-head vs the seed scaffold:**

| window | genome | CSR | Pass@1 |
|---|---|---|---|
| evolution (tasks 0–14, n=15) | seed g000 | 0.267 | 0.0 |
| evolution (tasks 0–14, n=15) | **champ g003** | **0.333** | 0.0 |
| **held-out (tasks 15–39, n=25)** | seed g000 | 0.12 | 0.0 |
| **held-out (tasks 15–39, n=25)** | **champ g003** | **0.32** | **0.12** |

The improvement **generalizes**: on tasks it was never optimized against, the
champion beats the seed by **+0.20 CSR (≈3×)** and **+0.12 Pass@1**. The seed
degrades on the harder held-out window (0.267→0.12); the champion holds
(0.333→0.32) — robustness, not overfit.

**What the machine discovered (scaffold diff seed → champion):**

- `use_peels: True → False` — **turned peel RAG grounding OFF**
- `top_k_atoms: 6 → 3` — fewer legacy-floor atoms
- `instructions:` verbose (582 chars) → **terse checklist variant (379 chars)**

**The insight:** the original `cobol-jeeves` design assumed peel/atom RAG
grounding helps. The DGM empirically found the opposite for the *fine-tuned*
model — the retrieved context is noise once the model has internalized COBOL
patterns from training; less grounding + a shorter prompt wins. This was reached
*through* two flat-looking stepping stones (`top_k_atoms→3`, `use_peels→False`,
both CSR 0.20) that the open-ended archive refused to discard — the `use_peels`
step is what first unlocked nonzero Pass@1. Textbook DGM behaviour.

**Caveat (honest):** n is small (15/25). This is a strong, generalizing signal,
not a full-146 claim. Next: re-score on the full benchmark and feed per-task
compiler diagnostics into the proposer to push further.
