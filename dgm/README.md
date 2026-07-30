# cobol-dgm — a Darwin Gödel Machine for offline COBOL

**Label: PROTOTYPE** (research / exploration). Not pilot- or production-ready.
See "Honest gaps" below. Isolated on branch `feat/cobol-dgm`; touches nothing
in the shipped `cobol-jeeves` path.

A self-improving loop, after Sakana's [Darwin Gödel Machine](https://sakana.ai/dgm/).
The original Gödel Machine required a *formal proof* that a self-modification
helps — intractable. DGM's move: replace proof with **empirical validation on a
benchmark**, and keep an **open-ended archive** of every agent so worse-but-
different scaffolds survive as stepping stones. We do exactly that for COBOL.

## Core-goal alignment

The whole point is *an offline COBOL model that writes correct, compiling COBOL
and gets better on its own.* Every design choice serves that:

- **Solver is 100% offline** — the frozen local model (`cobol-jeeves-ft`) over
  `localhost:11434` only. No weights are ever modified.
- **What evolves is the *scaffold*** — prompt, RAG grounding, decoding, repair
  policy — the faithful DGM shape (frozen model, evolving code around it).
- **Fitness is real execution** — COBOLEval compiles each completion and runs
  its tests (`compile_all_tests_rate` = CSR, primary; `pass_at_1`, tiebreak).
- **Default mutation operator is offline** (`heuristic`) so the loop closes with
  zero API keys. A strong-brain proposer is an opt-in upgrade, never a runtime
  dependency of the shipped artifact.

## DGM ⟷ substrate mapping

| DGM concept | Here |
|---|---|
| Self-modifying coding agent | `genome.py` — the evolvable scaffold (a `Genome`) |
| Run the agent on a task | `solver.py` — ground → generate → normalize → cobc-repair |
| Benchmark / empirical validation | `evaluate.py` — COBOLEval execution → `Fitness` |
| Open-ended archive + selection | `archive.py` — keep everything; novelty-aware sampling |
| Self-modification operator | `mutate.py` — heuristic (offline) + brain (pluggable) |
| The loop | `loop.py` — seed → select → mutate → evaluate → archive |

Baseline (genome-zero) = the proven scaffold: **CSR 0.24 / Pass@1 0.08** (n=25).
That is the number the machine must beat.

## Run

```bash
cd ~/cobol-cool-demos
ollama serve &                       # model must be reachable
python -m dgm.loop --iterations 8 --tasks 12         # fully offline
python -m dgm.loop --iterations 8 --tasks 12 --proposer claude   # brain-driven
```

Archive is a resumable sqlite file at `dgm/runs/archive.db`:

```bash
sqlite3 dgm/runs/archive.db \
  'SELECT genome_id, generation, origin, csr, pass_at_1, children FROM agents ORDER BY csr DESC;'
```

## Honest gaps (what blocks a higher label)

- **Evaluation cost**: COBOLEval is slow (~15–40 s/task on this box). Runs use a
  task *subset*; the champion must be re-validated on the full 146 before any
  claim. Subset scores are noisy at small n — treat as search signal, not truth.
- **Tier-B not built**: evolving the *dataset → LoRA → new model genome* (the
  weight axis) is scaffolded conceptually only. Hardware-gated (16 GB, prior
  training-induced kernel panics). The current loop evolves scaffold only.
- **Heuristic proposer is shallow**: guided random moves, not reasoning about
  failures. Brain proposer is the intended driver once a run is trusted.
- **No held-out split yet**: subset overlap between iterations can overfit the
  window. Add a rotating/held-out task set before trusting deltas.
- Single-sample (temp may be >0 but k=1). No multi-sample Pass@k.

## Next rungs

1. Feed per-task compiler diagnostics into the heuristic proposer (targeted, not random).
2. Held-out validation split + full-146 re-score of the champion.
3. Brain proposer default once offline loop is trusted; log lineage graphs.
4. Tier-B: mine archived failures → training pairs → gated LoRA → new frozen genome.
