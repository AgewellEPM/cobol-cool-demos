# COBOL FIGHTER — plan

*A PS2-style fighting game written in COBOL. Researched + designed 2026-07-27.*

I have everything I need — the exact renderer paragraphs (`WRITE-PIXBUF`, `PUT-BYTE` with `FUNCTION CHAR`, `WRITE ROW-RECORD` per scanline), the palette-index PIX buffer (`PIX OCCURS ... PIC 9(3) COMP`), the sprite-bitmap `FILLER`/`REDEFINES`/`OCCURS` peel, and the fixed-point-trig peel. Here is the plan.

---

## Context (the honest "PS2 in COBOL" reality)

"Build a PS2 fighting game in COBOL" is three different claims wearing one sentence. Stated plainly:

| Claim | What it literally means | Truth here |
|---|---|---|
| **"PS2-STYLE fighter, rendered in COBOL"** | GnuCOBOL 3.2 on this Mac computes every frame as raw RGB24 → ffmpeg → video. "PS2" = the *look* (640×448-ish aspect, health bars, dithered palette), NOT the console. | **Achievable now.** Same rig that already shipped `DOOMFIRE.cob` and `GAME2048.cob`. |
| **"Playable fighter, COBOL is the engine"** | COBOL owns all state + logic + pixel output; a ~40-line C/Python shim does only keyboard + window blit (things COBOL can't do portably). | **Achievable, harder.** Perf ceiling is the risk, not the path. |
| **"A COBOL game running on PS2 / in PCSX2"** | `cobc -C` → cross-compile the emitted C + `libcob` against `ee-gcc`/PS2SDK/newlib → EE ELF → boots in PCSX2. | **Feasible but unstarted research.** No `ee-gcc`, no PS2SDK, no `libcob` sources on this machine yet. The load-bearing unknown is whether `libcob` cross-compiles clean against newlib. **The R5900 no-double FPU wall is genuinely dodged** because GnuCOBOL's numeric core is integer/BCD (`COMP-3`, `PIC 9`) — *provided `COMP-2` is banned.* |

The one discipline that governs all copy: **"PS2-STYLE" is honest; "on PS2" / "PS2 game" is a lie until an ELF boots in PCSX2 with a photo/capture to prove it.** Never blur style into hardware.

## Recommended path — staged A → B → (C stretch)

Ship in the order the scores dictate:

- **A first (build:9 reuse:10 honesty:8 wow:7).** The guaranteed, this-week artifact. Reuses the repo and all proven peels wholesale — it *is* the DOOMFIRE/2048 formula Luke has landed twice. Gate it on the M1 render bench (below); that one number decides per-pixel vs slab-blit.
- **B next (build:8 reuse:9 honesty:7 wow:8).** The honest *center* of the ask: a genuinely playable 2-player local fighter where COBOL is provably the engine. Higher wow than A precisely because it's playable, not a video. It's a direct extension of A's engine + a tiny I/O shim.
- **C as a clearly-labeled EXPERIMENTAL spike (build:4 reuse:4 honesty:9 wow:9).** The crown jewel — a real EE ELF booting in PCSX2 is unprecedented and screenshot-defensible — but its buildability is low and the `libcob` cross-compile is an unbounded blocker. **Never the headline.** Gate it behind a trivial one-line-DISPLAY ELF; keep or kill based purely on whether `libcob` links against newlib.

Rationale: A and B share ~90% of the COBOL (state machine + `WRITE-PIXBUF`/`PUT-BYTE` renderer). C shares almost none of it (the renderer must be redirected from a *file* to the GS framebuffer via net-new gsKit C). So A→B is one continuous build; C is a separate research fork.

## Architecture — the COBOL engine (constructs named)

All logic lives in `WORKING-STORAGE`, advances in one `PERFORM UNTIL` tick loop, emits pixels through the exact proven `gnucobol:raw-rgb24-video` mechanism from `GAME2048.cob` (`RECORD CONTAINS width*3`, one `WRITE ROW-RECORD` per scanline, each byte = `FUNCTION CHAR(value+1)`).

**Frame buffer & renderer (reuse GAME2048 lines 21–22, 47, 432–449 verbatim in shape):**
- `01 PIX ... OCCURS (W*H) TIMES PIC 9(3) COMP.` — palette-index buffer (not raw RGB; store the color id, expand at write time — this is the 2048 trick and it's ~3× cheaper per pixel).
- `01 COL-R / COL-G / COL-B OCCURS n PIC 9(3) COMP.` — palette. PS2-style dithered ramp lives here.
- `WRITE-PIXBUF` paragraph: `PERFORM VARYING` scanline; per pixel `MOVE PIX(idx) TO WV-CID`, three `PERFORM PUT-BYTE`, then `WRITE ROW-RECORD`.
- `PUT-BYTE` paragraph: `MOVE FUNCTION CHAR(D-BYTE) TO D-CHAR` → `MOVE D-CHAR TO ROW-RECORD(D-POS:1)` (reference modification). Byte-exact, proven.

**Fighter state — FSM.** Two records:
```
01 FIGHTER OCCURS 2 TIMES.
   05 F-X          PIC S9(4).        *> screen x (fixed step)
   05 F-Y          PIC S9(4).
   05 F-VX         PIC S9(4).        *> velocity, integer physics
   05 F-VY         PIC S9(4).
   05 F-FACING     PIC S9.           *> +1 / -1
   05 F-HP         PIC 9(3).         *> 0..100
   05 F-STATE      PIC 9(2).         *> 01 IDLE 02 WALK 03 JUMP
   05 F-STATE-T    PIC 9(3).         *>   04 ATK-L 05 ATK-H 06 BLOCK
   05 F-FRAME      PIC 9(2).         *>   07 HITSTUN 08 KO
```
FSM = an `EVALUATE F-STATE` in a `PERFORM-STATE` paragraph; transitions are `MOVE new-state TO F-STATE / MOVE 0 TO F-STATE-T`. `F-STATE-T` counts frames-in-state to drive startup/active/recovery windows and animation.

**Frame-data table (move properties).** One `OCCURS` table keyed by (state, animation-frame):
```
01 MOVE-DATA.
   05 MD OCCURS 32 TIMES.       *> one row per move
      10 MD-STARTUP  PIC 9(2).  10 MD-ACTIVE   PIC 9(2).
      10 MD-RECOVER  PIC 9(2).  10 MD-DAMAGE   PIC 9(3).
      10 MD-HB-DX    PIC S9(3). 10 MD-HB-DY    PIC S9(3).
      10 MD-HB-W     PIC 9(3).  10 MD-HB-H     PIC 9(3).
      10 MD-BLOCKSTUN PIC 9(2). 10 MD-HITSTUN  PIC 9(2).
```
Fill with `VALUE` clauses (or a `SELECT ... ASSIGN` record file if we want to hot-tune without recompiling — happy path is in-source `VALUE`). This is the fighting-game "frame data" as literal COBOL rows.

**Hitbox collision — pure integer AABB.** During a move's active window (`F-STATE-T` within `[STARTUP, STARTUP+ACTIVE]`), compute attacker hitbox = `F-X + F-FACING*MD-HB-DX`, etc.; compare against defender hurtbox (a fixed AABB around `F-X/F-Y`). Overlap = four `IF` comparisons — no floats, `COMP-3`/`PIC S9` throughout. On hit: `SUBTRACT MD-DAMAGE FROM F-HP`, set defender `F-STATE = HITSTUN`, `F-STATE-T = MD-HITSTUN`. Block check first (`F-STATE = BLOCK` and facing correct → apply `MD-BLOCKSTUN`, chip only).

**Motion-input matcher.** A ring buffer of recent directional inputs:
```
01 INBUF.
   05 IB OCCURS 2 TIMES.
      10 IB-DIR OCCURS 12 TIMES PIC 9.   *> numpad notation 1..9
      10 IB-HEAD PIC 9(2).
```
Match a quarter-circle-forward (2→3→6 + punch) by scanning the last N entries with a `PERFORM VARYING` and an `EVALUATE`/`IF` chain against a pattern table `01 SPECIAL-PAT OCCURS`. Windowed by frame age so a stale input can't fire. **This is where the two proven bug-rule peels are load-bearing:**
- `gnucobol:shared-perform-varying-counter` — the matcher and the collision loop MUST NOT share a `VARYING` counter with the outer render loop. Each nested scan gets its own dedicated index (`M-I`, `H-I`, `WV-R` stay distinct). A shared counter is the classic silent-corruption bug this peel pins.
- `gnucobol:goto-escapes-perform-range` — when a pattern matches, escape the scan cleanly (set a `MATCHED` flag and let the `PERFORM ... UNTIL MATCHED` fall through). **Do not `GO TO` out of a `PERFORM` range** — that peel proves it corrupts the range stack. Regression assert: no `GO TO` targets outside its own paragraph.

**CPU AI.** A reactive FSM over the same state, seeded by the existing LCG (`WV-SEED`/`WV-RANDF` pattern from 2048). `EVALUATE` on distance-to-opponent × opponent-state: far → walk-in; mid → poke (short attack); close+opponent-startup → block or throw; low HP → defensive bias. Difficulty = probability gates on the LCG. Deterministic given a seed → reproducible for verification.

**Sprites.** Reuse `gnucobol:sprite-bitmap` (`FILLER`/`REDEFINES`/`OCCURS` + reference-modification sampling). Fighters are palette-index sprite sheets blitted into `PIX` with facing-flip via reverse column index. Optional fixed-point-trig peel (`PIC S9V9(5)` + `FUNCTION SIN/COS`) only if we add arced projectiles — otherwise integer physics is enough.

**I/O seam (B only).** Top of tick: `ACCEPT` a small input record (2 bytes: P1 cmd, P2 cmd) written by the shim; bottom of tick: `WRITE-PIXBUF` to a frame the shim reads and blits. COBOL owns everything above the keyboard and below the window.

## Milestones (each shippable)

- **M0 — Render bench (GATE, half a day).** Fork `GAME2048.cob`'s `WRITE-PIXBUF`/`PUT-BYTE` into a throwaway that fills a moving 2-rectangle + scrolling background scene at target res, writes N=600 frames (10s @60fps), and reports wall-clock + `.raw` size. **This number chooses the renderer strategy for everything after it.** No fight logic until it's known.
- **M1 — Two idle fighters + health bars.** Static scene, sprite blit, HUD (two health bars, round timer, "PS2-STYLE" framing). One frame proven byte-exact, then a short idle-loop video. *Ship: a screenshot + clip.*
- **M2 — Movement + attacks + collision.** Walk/jump physics, light/heavy attacks with startup/active/recovery from `MOVE-DATA`, AABB hitbox, HP subtraction, hitstun. A scripted exchange that lands a hit. *Ship: clip of a real hit registering, HP dropping.*
- **M3 — KO + rounds.** `F-HP = 0` → KO state + K.O. banner; best-of-3 round flow; win screen. *Ship: a full bout ending in a genuine KO — the money shot.*
- **M4 — Motion specials + CPU AI.** Input ring buffer + special matcher (QCF+P fireball / DP), CPU-vs-CPU or CPU-vs-scripted match. *Ship: a special move firing on a real motion input; an AI that fights back.*
- **M5 — Terminal build video + Reddit cut.** Green-phosphor `cat` of the real `.cob` source → `cobc -x` compile → run → split-screen with the gameplay video. GIF + MP4 for Reddit/VC. This is the artifact.
- **C-STRETCH (EXPERIMENTAL, separate fork) — PS2 ELF bridge.** In this exact order, each a hard gate:
  1. Install `ps2toolchain-ee` + PS2SDK; fetch GnuCOBOL 3.2 **source** (Homebrew ships only the dylib).
  2. `cobc -C` a one-line `DISPLAY "COBOL ON PS2"` → cross-compile emitted C + **cross-built `libcob`** against `ee-gcc`/newlib → EE ELF → `pcsx2 --elf=` (no ISO). **If `libcob` won't link against newlib, the approach is dead — you learn it here in days for near-zero cost.**
  3. Only then: redirect `WRITE-PIXBUF` output from a *file* to the GS framebuffer via a thin gsKit C shim; boot the fighter ELF.
  4. Only then: mode-2/2352 ISO9660 + `SYSTEM.CNF` (`BOOT2=cdrom0:\GAME.ELF;1`), 8.3 uppercase names, for real-hardware boot (needs the physical console + FMCB to *prove*).

## Performance plan

The datapoint: 2048 at 260×260 (67,600 px) did per-pixel `PUT-BYTE` and took ~10s for 254 mostly-static frames (~25 render-fps). A fighter is worse on two axes — 640×448 = 286,720 px (4.2×) *and* every frame is a moving full scene, so a naive port is tens-of-minutes-to-hours renders and a multi-GB `.raw`. Mitigations, in priority order:

1. **Small internal resolution, upscale in ffmpeg.** Render 320×224 (PS2-authentic low-res, 71,680 px ≈ the 2048 budget we already know finishes), then `ffmpeg ... -vf scale=640:448:flags=neighbor` for the crisp PS2 pixel look. Biggest single win.
2. **Palette-index buffer, not RGB.** Store `PIX` as color id (already the 2048 design); expand to 3 bytes only in `PUT-BYTE`. Keeps the inner loop cheap.
3. **Row-slab blitting instead of full per-pixel repaint.** Redraw the background once into a template row set; each frame `MOVE` the template into `PIX` and overwrite only fighter/HUD spans. Cuts per-frame pixel touches by the ratio of moving-area to screen.
4. **Pre-render is the honest 60fps for A/M5.** The terminal-build-video treatment does not need live realtime. Render offline, encode at 60fps, ship the video — the label stays "rendered in COBOL," fully honest.
5. **For B (playable):** fixed-step logic decoupled from render; target a *measured, honestly-recorded* interactive fps at 320×224. If it lands below ~30fps, say so and either drop resolution further or present B as "playable-slow, honestly benchmarked" rather than claiming a smoothness it doesn't have.

## Honest labels per deliverable

- **M0–M1:** PROTOTYPE — "PS2-STYLE fighter frames rendered by GnuCOBOL 3.2, no graphics library." No gameplay claim yet.
- **M2–M3:** PILOT-READY artifact — "A fighting game with real hitbox collision, KO, and rounds, entirely computed in COBOL and rendered to video." Byte-exact frame math + a real KO on tape.
- **M4:** Same tier, expanded — "special moves via motion-input matching and a CPU opponent, all in COBOL WORKING-STORAGE." Still a *video*, still "PS2-STYLE."
- **M5 (A/B ship):** The shareable artifact. Copy says **"PS2-STYLE fighting game written in COBOL"** — never "PS2 game," never "on PS2." If B is included, add "playable, 2-player local, with a thin C/Python I/O shim for keyboard + window (COBOL is the engine)."
- **C-STRETCH:** **EXPERIMENTAL / PROTOTYPE** until an ELF boots. Only after step C.2 passes may copy say "COBOL-authored game logic running on the PS2 via a C bridge (in PCSX2)." Only after C.4 with a photo may anyone say "on real PS2 hardware." Not one word sooner.

None of A–C is ENTERPRISE-READY or PRODUCTION-READY — these are demo/shareable artifacts, not products for vulnerable users; label them as artifacts and don't imply otherwise.

## Verification

- **M0:** the bench prints wall-clock + `.raw` byte count; assert `size == W*H*3*N` exactly (proves the raw-rgb24 record math is byte-exact before any content). This gates the whole build.
- **M1:** decode one emitted frame with ffmpeg → PNG; assert a known pixel span (a health-bar edge) has the exact palette RGB triple the COBOL computed. Byte-exact, reproducible from a fixed seed.
- **M2:** a scripted deterministic exchange (fixed `WV-SEED`) MUST show defender `F-HP` decreasing by exactly `MD-DAMAGE` on the frame the AABB overlaps — assert the HP value in a debug `DISPLAY` log and assert the corresponding HUD pixels changed.
- **M3:** the recorded bout MUST end with a real `F-HP = 0` transition to KO — verify by the HP log hitting 0 *and* the KO banner pixels appearing; a "real KO in the video" is the acceptance criterion, not a staged frame.
- **M4:** feed a scripted QCF+P input sequence; assert the special-move state fires exactly when the matcher window closes and NOT on a stale/partial motion. Per-peel regression: (a) assert no nested scan shares the outer render `VARYING` counter (`shared-perform-varying-counter`); (b) assert no `GO TO` leaves any `PERFORM` range (`goto-escapes-perform-range`). One assertion per site, named.
- **M5:** the terminal build video must show the *actual* `.cob` being compiled and run (no faked terminal); verify the on-screen source hash matches the committed file.
- **C-STRETCH:** the only acceptable proof of "in PCSX2" is a capture of the COBOL-authored ELF running under `pcsx2 --elf=` with the string/frame on the GS; "on hardware" requires a photo/capture of a real console. Until that exists, the claim stays EXPERIMENTAL.

**Files/paths:** repo `/Users/lukekist/cobol-cool-demos` (reuse `GAME2048.cob` lines 21–22, 47, 432–449 for the renderer; `DOOMFIRE.cob` for the palette/encode pipeline). Proven peels: `/Users/lukekist/perslis-dos-snake/docs/cobol-game-proofs/peel-data-format-cobol-sprite-bitmap.cob` and `.../peel-capability-cobol-fixed-point-trig.cob`. Toolchain confirmed on-machine: `cobc (GnuCOBOL) 3.2.0` at `/opt/homebrew/bin/cobc`, `ffmpeg` at `/opt/homebrew/bin/ffmpeg`, `PCSX2.app` in `/Applications`. NOT on-machine (C-stretch must fetch): `ee-gcc`, PS2SDK, `ps2toolchain`, GnuCOBOL source tarball.
---

## M0 RESULTS (2026-07-27) — GATE PASSED

Built `FIGHTBENCH.cob` (naive full-repaint) and `FIGHTBENCH2.cob` (optimized) —
a real fighter scene: scrolling background, floor, two moving fighter bodies,
two draining health bars, at 320×224 → upscaled 640×448 nearest-neighbor.

| Build | render fps | note |
|---|---|---|
| FIGHTBENCH (per-byte `PUT-BYTE` PERFORM) | **9.4** | the DOOMFIRE/2048 mechanism, verbatim |
| FIGHTBENCH2 (precomputed 3-byte `COL-STR`, one `MOVE`/pixel) | **13.1** | +39%, still byte-exact |

Byte-exact both: `320*224*3*300 = 64,512,000` bytes, `exact=True`.

**Verdict:**
- **Path A (offline-rendered fighter video) is GREEN.** 13 fps render → a 10 s
  60 fps clip (600 frames) renders in ~46 s. Fully fine for the M5 shareable
  artifact. Proceed.
- **Path B (realtime playable) is NOT free at full repaint** (13 fps < 30). It
  needs the plan's mitigation #3 — **row-slab blitting** (redraw the background
  template once, MOVE it into `PIX` each frame, overwrite only fighter/HUD
  spans) — plus possibly a smaller inner res. Scoped, not blocking; do it when
  we reach B.
- Biggest proven lever so far: replacing the per-byte `PUT-BYTE` PERFORM with a
  precomputed 3-byte `COL-STR` `MOVE`. Bake this into the real engine renderer.

Next: **M1 — two idle fighters + health bars as the real engine skeleton**
(sprite bodies via the sprite-bitmap peel, HUD text via the 2048 pixel-font),
reusing FIGHTBENCH2's renderer.
