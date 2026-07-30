"""cobol-dgm — a Darwin Godel Machine for offline COBOL generation.

PROTOTYPE (research/exploration). Self-improving loop over the frozen local
COBOL model: the *scaffold* (prompt, grounding, decoding, repair) evolves and
is validated empirically on COBOLEval (compile + test execution). The model
weights are frozen and every artifact stays fully offline (localhost only),
exactly matching the core goal: an offline COBOL model that writes correct
COBOL and gets measurably better on its own.

See README.md for the DGM<->substrate mapping and honest gaps.
"""
