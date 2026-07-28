# R1 — COBOLEval baseline harness (offline models)

Scores local Ollama models on COBOLEval (146 HumanEval tasks transpiled to
COBOL): compile-success rate + Pass@1, via the upstream harness with
execution enabled.

Setup (COBOLEval is cloned, not vendored):

    git clone --depth 1 https://github.com/zorse-project/COBOLEval.git eval/COBOLEval
    cd eval/COBOLEval && git apply ../enable-execution.patch   # enables the run step
    /opt/homebrew/bin/python3.12 -m venv eval/venv             # >=3.10 (match stmts)
    eval/venv/bin/pip install numpy tqdm loguru

Run (writes preds/<model>/summary.json):

    cd eval && ./venv/bin/python run_local.py --model qwen2.5-coder:7b --tasks 25
    cd eval && ./venv/bin/python run_local.py --model cobol-jeeves --tasks 25

Notes:
- Harness self-test: task 0's `canonical_solution` is the PYTHON original
  (upstream ships no COBOL references) — validate with a hand-written
  solution instead (4/4 tests passed on 2026-07-28).
- Execution of generated code is enabled deliberately on this box; the
  upstream 5s cmd() timeout guards infinite loops.
