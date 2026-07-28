# COBOL Offline Model — plan (researched + cited, 2026-07-28)

**Goal:** a fully offline COBOL coding model on this Mac, served by Ollama, wrapped by our
own app layer (TinkyMind pattern), trained/grounded on OUR verified corpus (peels, rulebook,
floor atoms, working programs).

**Status: PROTOTYPE plan.** Nothing below is built yet except the corpus itself.
Research = deep-research-plus run wf_a8040e56-c03 (19 claims confirmed 3-0, 3 refuted,
3 unverified-by-rate-limit — refutations and abstains listed at the bottom, not hidden).

---

## Hardware reality check (changes the original ask)

This Mac has **16 GB RAM, not 64**. That caps local inference at **7B Q4 comfortably,
14B Q4 as a tight stretch**, 32B out. All choices below respect the 16 GB ceiling.
Already pulled in Ollama: `qwen2.5-coder:7b`, `granite-code:3b`, `qwen3-vl:4b`.

## The three verdicts (what the evidence picked)

### 1. Base model: **Qwen2.5-Coder-7B** (fallback: Qwen2.5-Coder-14B Q4)

- COBOL-Coder (arXiv 2604.03986) fine-tuned exactly this family: COBOL-Coder-**7B** hits
  **73.80% compile-success / 44.70 Pass@1** on COBOLEval vs **GPT-4o at 41.8% / 16.4**.
  A tuned 7B beats a frontier generalist at COBOL. [3-0 verified]
- StarCoder2 / CodeLlama / CodeGemma score **0% compile success** on COBOLEval zero-shot —
  eliminated. [verified]
- XMainframe (arXiv 2408.04660) confirms the pattern (~10.5B tuned model beats GPT-4 on
  mainframe knowledge 77.89% vs 73.90%). NOTE: the claim that XMainframe's base was
  DeepSeek-Coder was REFUTED in verification — cite the result, not that lineage.
- We already have `qwen2.5-coder:7b` pulled. Zero download cost to start.

### 2. Tuning vs RAG: **grounded-RAG first, LoRA second — the corpus decides**

The honest evidence chain:
- Fine-tuning beats RAG in *stable* domains (GnuCOBOL 3.2 idioms = frozen domain). [3-0]
- LoRA beats RAG/ICL on CodeLlama-7B — **but at ~2,000 training pairs** (Conala 2,135 /
  CodeAlpacaPy 2,192). The break-even is *at most* ~2k pairs; nothing proves LoRA wins at
  our raw size (~19 unique programs + 13 peels + 63 atoms). [3-0, including the honest
  scale caveat as its own verified claim]
- Therefore: **ship the RAG/system-prompt-grounded model NOW (R0), and only LoRA after
  the synthetic pipeline reaches ~2k cobc-verified pairs (R2→R3).** No leap of faith.

### 3. Toolchain: **MLX-LM LoRA → fuse → llama.cpp GGUF → `ollama create`**

- MLX runs LoRA natively on M-series, no CUDA (unsloth-mlx confirmed as the
  Unsloth-API-on-MLX wrapper). [3-0]
- ⚠️ unsloth-mlx's "complete path to GGUF/Ollama" claim was **REFUTED (1-2)** — do NOT
  rely on its exporter. Use plain `mlx_lm.lora` → `mlx_lm.fuse` (merge adapter into base)
  → llama.cpp `convert_hf_to_gguf.py` → `ollama create`.
- Ollama `ADAPTER` supports GGUF + safetensors adapters, BUT safetensors adapters only for
  Llama/Mistral/Gemma — **Qwen is not on the list**, and the adapter must come from the
  EXACT same base as the Modelfile base or behavior is undefined. [both 3-0]
  → For Qwen: **merge-then-convert** is the safe path; GGUF-converted adapter is the
  experimental alternative.
- Fallback toolchain: axolotl-on-Mac (blog-grade evidence only) or a one-off cloud LoRA
  run — training location doesn't violate the offline requirement; **inference offline**
  is the requirement.

### 4. Synthetic data: **cobc as reject-sampler, compiler-in-the-loop repair**

Directly validated recipe (it's literally how COBOL-Coder built its corpus):
- Keep only programs that compile; failed ones get LLM repair guided by compiler
  diagnostics, max K=3 iterations (they got 31,492 compilable programs this way). [3-0]
- CodeV-style multi-level summarization: generate instruction pairs by summarizing REAL
  working code (our 19 programs) at function/paragraph/program level, then invert
  (summary→code) and keep only pairs where the code compiles under `cobc -std=default`
  (+ runs where a harness exists — our peels already carry sandbox tests). [3-0]
- Target: **~2,000 verified pairs** (the proven break-even scale) from:
  - 19 unique working programs (games incl. FIGHTER, cobolwolf FPS, bankday.cbl, VSAM/ESQL)
  - 13 proven peels (each = a rule + a compiling proof program + a failure counterexample —
    these are GOLD: rule→bug→fix triplets)
  - 63 floor atoms (typed relations → Q&A pairs)
  - COBOL_GAME_CORE.md + COBOL_FIGHTER_PLAN.md (rulebook prose → instruction pairs)
  - Today's fighter debugging session (3 real bug→fix pairs: PIC-width loop wrap,
    nested-FUNCTION parse, GO-TO-out-of-PERFORM-range → THRU fix)

### 5. Eval: **COBOLEval + CobolCodeBench, compile-pass rate as the headline**

- COBOLEval: github.com/zorse-project/COBOLEval — 146 tasks, the metric the whole field
  reports (CSR + Pass@1). CobolCodeBench on HF (harshini-kumar/CobolCodeBench) as second
  bench. [3-0]
- Wire `cobc` compile-pass as the gate in OUR harness too — same shape as the peel
  training loop we already run in perslis-dos-snake.

---

## Build phases (each shippable, each labeled)

- **R0 — Grounded model, TODAY-grade (PROTOTYPE).** `ollama create cobol-jeeves` from
  `qwen2.5-coder:7b` + SYSTEM prompt distilled from the 13 peels + game-core rules
  (fixed-format discipline, COMP-3, no-GO-TO-out-of-PERFORM, own-your-loop-counter,
  PIC-width-vs-bound). Wrapper CLI (`~/bin/cobol-jeeves`, TinkyMind pattern: wrapper owns
  retrieval + safety + session) does SQLite FTS over legacy_floor.db + peels.jsonl and
  injects the top-k rules per query. **Fully offline day one.**
- **R1 — Eval harness.** Clone COBOLEval, wire cobc, measure: raw qwen2.5-coder:7b vs
  R0-grounded. This is the baseline every later phase must beat. No number, no claims.
- **R2 — Dataset to ~2k pairs.** The cobc reject-sampler pipeline above
  (generate → compile → repair ≤3 → keep/drop; log drop rate honestly). Store as JSONL
  chat format; every pair carries the sha of the compile proof.
- **R3 — QLoRA on M4 (16 GB).** `mlx_lm.lora` on Qwen2.5-Coder-7B, 4-bit, small batch,
  seq 2048. Overnight-scale job, not minutes.
- **R4 — Fuse → GGUF → Ollama, A/B.** Merge, convert, `ollama create cobol-jeeves-ft`.
  Ship ONLY if it beats the R0 grounded baseline on COBOLEval CSR/Pass@1. If it loses,
  R0 stays the product and we say so.
- **R5 — Wrapper app hardening.** Session isolation + safety-guard + dock (port the
  TinkyMind wrapper shape from tinkybink-dashboard/apps/tinkyspeak/src/lib/tinkymind).
  Optional: register as a kist MCP tool (remember the toolEffects gate).

## R1 RESULTS (2026-07-28) — baseline measured

25-task COBOLEval subset, temperature 0, strict scoring + one model-agnostic
normalization (the upstream skeleton's invalid WORKING-STORAGE-after-LINKAGE
order is mechanically reordered; the benchmark's own prompt invites the error):

| model | compile rate | Pass@1 |
|---|---|---|
| qwen2.5-coder:7b (raw) | **0/25 (0%)** | 0% |
| cobol-jeeves (R0 grounded) | **2/25 (8%)** | 0% |
| COBOL-Coder-7B (paper, full 146) | 73.8% | 44.7 |
| GPT-4o (paper) | 41.8% | 16.4 |

Replicates the paper's "raw open models ≈ 0% CSR" finding — harness works,
gap quantified. Failure histogram (dominant first): `level number must begin
with 01 or 77` (declaring 05-items at root in WORKING-STORAGE), undefined
identifiers, missing period before END PROGRAM (+period tier recovers only
2/25 — it's not the main blocker). Grounding via game-domain peels doesn't
teach general syntax discipline — expected, and it tells R2 exactly what the
dataset must contain:

1. every pair's completion = full compilable subprogram, standard section order
2. drill 01/77-level declaration discipline and sentence-final periods
3. include LINKAGE + PROCEDURE DIVISION USING subprogram calling-convention
   examples (the COBOLEval shape, which is also the real-world subprogram shape)

## Honest ledger from the research run

- **Refuted (0-3 / 1-2):** "LoRA gives 80-90% of full-FT at 10-20% cost" (not in the cited
  survey); unsloth-mlx's GGUF/Ollama export claim; XMainframe's DeepSeek-Coder lineage.
- **Unverified (rate-limit abstains, NOT refuted):** KODCODE 447K-triplet pipeline details;
  execution-based self-verification <2.5% error rate; n=10 retry retention numbers. Re-run
  verification on these if we lean on them for R2 design decisions.
- Session limit killed the workflow's synthesize step; this document IS the synthesis,
  done inline from the 19 confirmed claims.

**Sources (primary):** arXiv 2604.03986 (COBOL-Coder), 2408.04660 (XMainframe),
2410.03981 (LRPL/DSL survey), 2308.10462 (LoRA vs RAG vs ICL), ollama/ollama#5788,
docs.ollama.com/modelfile, github.com/masna-ai/unsloth-mlx,
github.com/zorse-project/COBOLEval, HF harshini-kumar/CobolCodeBench,
aclanthology 2025.findings-acl.365 (KODCODE, unverified parts flagged).
