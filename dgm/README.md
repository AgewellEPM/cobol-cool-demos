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

- **Eval noise (measured)**: ollama is nondeterministic even at temperature 0 —
  the seed scaffold scored CSR 0.267 and 0.20 on the *same* 15 tasks across two
  runs (±1 task ≈ ±0.067 at n=15). So small-n subset deltas are search signal,
  NOT truth: a champion must clear the noise band and be re-validated on a
  held-out window (and ideally the full 146) before any claim.
- **Tier-B LoRA not run yet**: the harvest half is built and leak-safe
  (`harvest.py`); the training run (`train/run_lora.sh`) is GPU-gated and, on
  this 16 GB box, kernel-panic-prone (batch 1 / max-seq 1024 required). Not
  fired blindly.
- **Single GPU serializes** every model job — evolution, validation, and LoRA
  cannot overlap without thrashing. Runs go one at a time.
- Single-sample (k=1); no multi-sample Pass@k, no variance bars yet.

## Results so far (PROTOTYPE, small n — see noise caveat)

Two independent evolution runs both improved over the seed and, in R1, the win
GENERALIZED to a held-out window:

| run | proposer | champion CSR (train window) | held-out (t15–39) |
|---|---|---|---|
| R1 | heuristic | 0.333 (vs seed 0.267) | **0.32 / p@1 0.12** vs seed 0.12 / 0.0 |
| R2 | failure-aware | 0.40 (vs seed 0.20) | *(validation running)* |

**Consistent finding across both runs (different lineages):** the terse
instruction-checklist prompt is the dominant lever; RAG grounding (peels/atoms)
is secondary and, for the fine-tuned model, sometimes harmful — R1 turned it off.

## Next rungs

1. ✅ Compiler-diagnostics → targeted proposer moves (`diagnostics.py` + R2).
2. ✅ Held-out re-validation tool (`revalidate.py`); full-146 re-score available.
3. ✅ Tier-B harvest, leak-safe (`harvest.py`). NEXT: run the gated LoRA on
   harvested + existing pairs → eval ONLY on the held-out split (tasks 100–145).
4. Reduce eval noise: multi-sample / larger n / variance bars before claims.
5. Brain proposer (claude/codex) as the mutation driver; lineage-graph logging.
