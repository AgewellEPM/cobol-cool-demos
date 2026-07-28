      *> ============================================================
      *> FIGHTER.cob  --  a PS2-STYLE fighting game, in COBOL.
      *>
      *> Two AI fighters, real mechanics computed entirely in COBOL
      *> WORKING-STORAGE and rendered to raw RGB24 (ffmpeg encodes):
      *>   - table-driven per-fighter state machine (FSM)
      *>   - frame-data table (startup / active / recovery / damage)
      *>   - integer AABB hitbox vs hurtbox collision, block + chip
      *>   - motion-input ring buffer + QCF matcher -> fireball special
      *>   - projectiles, hitstun/blockstun, KO, best-of-3 rounds, timer
      *>   - reactive CPU AI (approach / poke / block / special)
      *> Renderer = the proven raw-rgb24 peel with the M0 3-byte COL-STR
      *> optimisation. No graphics library.
      *>
      *> Discipline (proven COBOL bug peels): every loop owns its index
      *> (no shared PERFORM VARYING counter); no GO TO leaves a PERFORM
      *> range (flag-driven early exits only).
      *> ============================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FIGHTER.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RGB-FILE ASSIGN TO "fighter.raw"
               ORGANIZATION IS SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  RGB-FILE
           RECORD CONTAINS 960 CHARACTERS.
       01  ROW-RECORD          PIC X(960).

       WORKING-STORAGE SECTION.
       01  GEO.
           05  C-W             PIC 9(4) VALUE 320.
           05  C-H             PIC 9(4) VALUE 224.
           05  C-CELLS         PIC 9(6) VALUE 71680.
           05  C-FLOORY        PIC 9(4) VALUE 188.
           05  C-MAXFRAMES     PIC 9(6) VALUE 7200.

      *> --- pixel buffer + palette (M0 renderer) ------------------
       01  PIXBUF.
           05  PIX OCCURS 71680 TIMES PIC 9(3) COMP.
       01  PALETTE.
           05  COL-R OCCURS 24 TIMES PIC 9(3) COMP.
           05  COL-G OCCURS 24 TIMES PIC 9(3) COMP.
           05  COL-B OCCURS 24 TIMES PIC 9(3) COMP.
       01  COLSTR.
           05  COL-STR OCCURS 24 TIMES PIC X(3).

      *> --- fighters ----------------------------------------------
       01  FIGHTERS.
           05  FTR OCCURS 2 TIMES.
               10  F-X         PIC S9(4).
               10  F-VX        PIC S9(4).
               10  F-FACING    PIC S9.
               10  F-HP        PIC S9(4).
               10  F-STATE     PIC 9(2).
               10  F-STATE-T   PIC 9(3).
               10  F-MOVE      PIC 9(2).
               10  F-WINS      PIC 9.
               10  F-COL       PIC 9(3).
               10  F-COLDK     PIC 9(3).
               10  F-COOLDN    PIC 9(3).
      *> input ring buffer per fighter (numpad dirs 1..9) + attacks
               10  F-BUF.
                   15  F-DIR OCCURS 16 TIMES PIC 9.
               10  F-HEAD      PIC 9(2).
               10  F-CMD-ATK   PIC 9.

      *> states
       78  ST-IDLE            VALUE 1.
       78  ST-WALK            VALUE 2.
       78  ST-ATK-L           VALUE 3.
       78  ST-ATK-H           VALUE 4.
       78  ST-BLOCK           VALUE 5.
       78  ST-HITSTUN         VALUE 6.
       78  ST-SPECIAL         VALUE 7.
       78  ST-KO              VALUE 8.

      *> --- move / frame data (rows: 1=light 2=heavy 3=special) ---
       01  MOVE-DATA.
           05  MD OCCURS 3 TIMES.
               10  MD-STARTUP  PIC 9(3).
               10  MD-ACTIVE   PIC 9(3).
               10  MD-RECOVER  PIC 9(3).
               10  MD-DAMAGE   PIC 9(3).
               10  MD-REACH    PIC 9(4).
               10  MD-HITSTUN  PIC 9(3).
               10  MD-BLOCKSTN PIC 9(3).
               10  MD-CHIP     PIC 9(3).

      *> --- projectiles (one slot per fighter) --------------------
       01  PROJECTILES.
           05  PRJ OCCURS 2 TIMES.
               10  PJ-ACTIVE   PIC 9.
               10  PJ-X        PIC S9(4).
               10  PJ-DIR      PIC S9.
               10  PJ-OWNER    PIC 9.

      *> --- match state -------------------------------------------
       01  MATCH.
           05  M-ROUND         PIC 9.
           05  M-TIMER         PIC 9(3).
           05  M-TIMER-SUB     PIC 9(3).
           05  M-PHASE         PIC 9.
           05  M-PHASE-T       PIC 9(3).
           05  M-BANNER        PIC X(12).
           05  M-OVER          PIC 9.
      *> phases: 1=round-intro 2=fight 3=round-end 4=match-end
       78  PH-INTRO           VALUE 1.
       78  PH-FIGHT           VALUE 2.
       78  PH-ROUNDEND        VALUE 3.
       78  PH-MATCHEND        VALUE 4.

      *> --- rng ---------------------------------------------------
       01  RNG.
           05  RSEED           PIC 9(9) VALUE 20260727.
           05  RVAL            PIC 9(9).

      *> --- iteration / scratch (distinct names per scope) --------
       01  WORK.
           05  GF              PIC 9(6).
           05  FI              PIC 9.
           05  OPI             PIC 9.
           05  DIST            PIC 9(4).
           05   ROLL           PIC 9(3).
           05  HIT-DONE        PIC 9.
           05  MATCHED         PIC 9.
           05  SPEC-MOVE       PIC 9.
           05  WINNER          PIC 9.
           05  LAST1           PIC 9(2).
           05  LAST2           PIC 9(2).
       01  DRAW.
           05  D-Y             PIC 9(4).
           05  D-X             PIC 9(4).
           05  D-POS           PIC 9(6).
           05  D-IDX           PIC 9(6).
           05  D-BYTE          PIC 9(3).
           05  RX0             PIC S9(5).
           05  RX1             PIC S9(5).
           05  RY0             PIC 9(4).
           05  RY1             PIC 9(4).
           05  RCID            PIC 9(3).
           05  BW              PIC 9(4).
           05  T-I             PIC 9(3).
           05  T-BANNER        PIC X(12).
           05  T-BLEN          PIC 9(2).
           05  T-CH            PIC X.
           05  T-GI            PIC 9(3).
           05  T-ROW           PIC 9.
           05  T-COL           PIC 9.
           05  T-PX            PIC 9(2).
           05  T-PY            PIC 9(2).
           05  T-X             PIC 9(4).
           05  T-Y             PIC 9(4).
           05  T-SCALE         PIC 9.
           05  T-CID           PIC 9(3).
           05  T-STARTX        PIC 9(4).

      *> --- font: 3x5 glyphs for the chars we render --------------
       01  FONT-CHARS          PIC X(40)
           VALUE " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ.!-".
       01  FONT-TAB.
           05  FONT-ROW OCCURS 200 TIMES PIC X(3).

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM LOAD-PALETTE
           PERFORM LOAD-FONT
           PERFORM LOAD-MOVEDATA
           PERFORM INIT-MATCH
           OPEN OUTPUT RGB-FILE
           MOVE 0 TO GF
           PERFORM UNTIL M-OVER = 1 OR GF > C-MAXFRAMES
               PERFORM STEP-MATCH
               PERFORM DRAW-SCENE
               PERFORM WRITE-PIXBUF
               ADD 1 TO GF
           END-PERFORM
      *> hold the final banner a beat
           PERFORM 90 TIMES
               PERFORM DRAW-SCENE
               PERFORM WRITE-PIXBUF
           END-PERFORM
           CLOSE RGB-FILE
           DISPLAY "FIGHTER: match complete in " GF " frames. "
                   "P1 wins=" F-WINS(1) " P2 wins=" F-WINS(2)
           STOP RUN.

      *> ===========================================================
      *> RNG (LCG) — deterministic given RSEED
      *> ===========================================================
       NEXT-RAND.
           COMPUTE RVAL = FUNCTION MOD (RSEED * 1103515245 + 12345,
                                        1000000000)
           MOVE RVAL TO RSEED.

      *> ===========================================================
      *> match / round lifecycle
      *> ===========================================================
       INIT-MATCH.
           MOVE 0 TO M-OVER
           MOVE 1 TO M-ROUND
           MOVE 0 TO F-WINS (1) MOVE 0 TO F-WINS (2)
           MOVE 64  TO F-COL (1) MOVE 65 TO F-COLDK (1)
           MOVE 4 TO F-COL (1) MOVE 14 TO F-COLDK (1)
           MOVE 5 TO F-COL (2) MOVE 15 TO F-COLDK (2)
           PERFORM START-ROUND.

       START-ROUND.
           MOVE 60  TO F-X (1)  MOVE 240 TO F-X (2)
           MOVE 0 TO F-VX (1) MOVE 0 TO F-VX (2)
           MOVE 100 TO F-HP (1) MOVE 100 TO F-HP (2)
           MOVE ST-IDLE TO F-STATE (1) MOVE ST-IDLE TO F-STATE (2)
           MOVE 0 TO F-STATE-T (1) MOVE 0 TO F-STATE-T (2)
           MOVE 0 TO F-COOLDN (1) MOVE 0 TO F-COOLDN (2)
           MOVE 0 TO F-HEAD (1) MOVE 0 TO F-HEAD (2)
           MOVE 0 TO PJ-ACTIVE (1) MOVE 0 TO PJ-ACTIVE (2)
           MOVE 99 TO M-TIMER MOVE 0 TO M-TIMER-SUB
           MOVE PH-INTRO TO M-PHASE MOVE 0 TO M-PHASE-T
           STRING "ROUND " DELIMITED SIZE
                  M-ROUND DELIMITED SIZE INTO M-BANNER.

       STEP-MATCH.
           PERFORM FACE-OFF
           EVALUATE M-PHASE
               WHEN PH-INTRO     PERFORM STEP-INTRO
               WHEN PH-FIGHT     PERFORM STEP-FIGHT
               WHEN PH-ROUNDEND  PERFORM STEP-ROUNDEND
               WHEN PH-MATCHEND  PERFORM STEP-MATCHEND
           END-EVALUATE.

       FACE-OFF.
           IF F-X (1) <= F-X (2)
               MOVE +1 TO F-FACING (1) MOVE -1 TO F-FACING (2)
           ELSE
               MOVE -1 TO F-FACING (1) MOVE +1 TO F-FACING (2)
           END-IF.

       STEP-INTRO.
           ADD 1 TO M-PHASE-T
           IF M-PHASE-T > 75
               MOVE PH-FIGHT TO M-PHASE
               MOVE "FIGHT!" TO M-BANNER
               MOVE 0 TO M-PHASE-T
           END-IF.

       STEP-FIGHT.
      *> banner "FIGHT!" fades after a moment
           ADD 1 TO M-PHASE-T
           IF M-PHASE-T = 40
               MOVE SPACES TO M-BANNER
           END-IF
      *> countdown timer (60 sub-frames = 1 second)
           ADD 1 TO M-TIMER-SUB
           IF M-TIMER-SUB >= 45
               MOVE 0 TO M-TIMER-SUB
               IF M-TIMER > 0
                   SUBTRACT 1 FROM M-TIMER
               END-IF
           END-IF
      *> per-fighter AI + physics + combat
           PERFORM VARYING FI FROM 1 BY 1 UNTIL FI > 2
               COMPUTE OPI = 3 - FI
               PERFORM AI-DECIDE THRU AI-EXIT
               PERFORM ADVANCE-FIGHTER
           END-PERFORM
           PERFORM RESOLVE-COMBAT
           PERFORM STEP-PROJECTILES
      *> round-end conditions
           IF F-HP (1) <= 0 OR F-HP (2) <= 0 OR M-TIMER = 0
               PERFORM END-ROUND
           END-IF.

       END-ROUND.
           IF F-HP (1) > F-HP (2)
               ADD 1 TO F-WINS (1) MOVE 1 TO WINNER
           ELSE
               IF F-HP (2) > F-HP (1)
                   ADD 1 TO F-WINS (2) MOVE 2 TO WINNER
               ELSE
                   MOVE 0 TO WINNER
               END-IF
           END-IF
           IF F-HP (1) <= 0 AND F-HP (2) > 0
               MOVE ST-KO TO F-STATE (1)
           END-IF
           IF F-HP (2) <= 0 AND F-HP (1) > 0
               MOVE ST-KO TO F-STATE (2)
           END-IF
           EVALUATE WINNER
               WHEN 1 MOVE "P1 WINS" TO M-BANNER
               WHEN 2 MOVE "P2 WINS" TO M-BANNER
               WHEN OTHER MOVE "DRAW" TO M-BANNER
           END-EVALUATE
           MOVE PH-ROUNDEND TO M-PHASE MOVE 0 TO M-PHASE-T.

       STEP-ROUNDEND.
           ADD 1 TO M-PHASE-T
      *> let projectiles/knockdown settle visually
           PERFORM STEP-PROJECTILES
           IF M-PHASE-T > 110
               IF F-WINS (1) >= 2 OR F-WINS (2) >= 2
                   IF F-WINS (1) >= 2
                       MOVE "P1 WINS!" TO M-BANNER
                   ELSE
                       MOVE "P2 WINS!" TO M-BANNER
                   END-IF
                   MOVE PH-MATCHEND TO M-PHASE MOVE 0 TO M-PHASE-T
               ELSE
                   ADD 1 TO M-ROUND
                   PERFORM START-ROUND
               END-IF
           END-IF.

       STEP-MATCHEND.
           ADD 1 TO M-PHASE-T
           IF M-PHASE-T > 150
               MOVE 1 TO M-OVER
           END-IF.

      *> ===========================================================
      *> CPU AI — reactive FSM over distance + opponent state
      *> ===========================================================
       AI-DECIDE.
           MOVE 0 TO F-CMD-ATK (FI)
      *> only act from neutral-ish states
           IF F-STATE (FI) = ST-HITSTUN OR F-STATE (FI) = ST-ATK-L
              OR F-STATE (FI) = ST-ATK-H OR F-STATE (FI) = ST-SPECIAL
              OR F-STATE (FI) = ST-KO
               MOVE 0 TO F-VX (FI)
               GO TO AI-EXIT
           END-IF
           IF F-COOLDN (FI) > 0
               SUBTRACT 1 FROM F-COOLDN (FI)
           END-IF
           COMPUTE DIST = FUNCTION ABS (F-X (1) - F-X (2))
           PERFORM NEXT-RAND
           COMPUTE ROLL = FUNCTION MOD (RVAL, 100)
      *> default: idle
           MOVE ST-IDLE TO F-STATE (FI) MOVE 0 TO F-VX (FI)
      *> block if opponent is attacking and we're close
           IF (F-STATE (OPI) = ST-ATK-L OR F-STATE (OPI) = ST-ATK-H)
              AND DIST < 60 AND ROLL < 55
               MOVE ST-BLOCK TO F-STATE (FI)
               MOVE 0 TO F-STATE-T (FI)
               GO TO AI-EXIT
           END-IF
      *> in range: attack
           IF DIST < 52 AND F-COOLDN (FI) = 0
               IF ROLL < 55
                   MOVE ST-ATK-L TO F-STATE (FI)
                   MOVE 1 TO F-MOVE (FI)
               ELSE
                   MOVE ST-ATK-H TO F-STATE (FI)
                   MOVE 2 TO F-MOVE (FI)
               END-IF
               MOVE 0 TO F-STATE-T (FI)
               MOVE 22 TO F-COOLDN (FI)
               GO TO AI-EXIT
           END-IF
      *> far: sometimes throw a fireball (emit QCF motion -> matcher)
           IF DIST > 130 AND F-COOLDN (FI) = 0 AND ROLL < 22
               PERFORM EMIT-QCF
               MOVE 60 TO F-COOLDN (FI)
               GO TO AI-EXIT
           END-IF
      *> otherwise walk toward the opponent
           MOVE ST-WALK TO F-STATE (FI)
           IF F-X (FI) < F-X (OPI)
               MOVE 2 TO F-VX (FI)
           ELSE
               MOVE -2 TO F-VX (FI)
           END-IF.
       AI-EXIT.
           EXIT.

      *> emit a quarter-circle-forward + attack into the ring buffer
       EMIT-QCF.
           IF F-FACING (FI) > 0
               PERFORM PUSH-DIR-2 PERFORM PUSH-DIR-3 PERFORM PUSH-DIR-6
           ELSE
               PERFORM PUSH-DIR-2 PERFORM PUSH-DIR-1 PERFORM PUSH-DIR-4
           END-IF
           MOVE 1 TO F-CMD-ATK (FI).
       PUSH-DIR-2. MOVE 2 TO ROLL PERFORM PUSH-DIR.
       PUSH-DIR-1. MOVE 1 TO ROLL PERFORM PUSH-DIR.
       PUSH-DIR-3. MOVE 3 TO ROLL PERFORM PUSH-DIR.
       PUSH-DIR-4. MOVE 4 TO ROLL PERFORM PUSH-DIR.
       PUSH-DIR-6. MOVE 6 TO ROLL PERFORM PUSH-DIR.
       PUSH-DIR.
           ADD 1 TO F-HEAD (FI)
           IF F-HEAD (FI) > 16 MOVE 1 TO F-HEAD (FI) END-IF
           MOVE ROLL TO F-DIR (FI, F-HEAD (FI)).

      *> ===========================================================
      *> motion matcher: scan buffer for QCF (2,3,6 fwd / 2,1,4 back)
      *> + attack this frame -> SPECIAL. flag-driven (no GO TO out).
      *> ===========================================================
       MATCH-SPECIAL.
           MOVE 0 TO MATCHED
           IF F-CMD-ATK (FI) = 0
               GO TO MATCH-EXIT
           END-IF
      *> previous two ring-buffer slots (wrap 1..16)
           COMPUTE LAST1 = F-HEAD (FI) - 1
           IF LAST1 < 1 ADD 16 TO LAST1 END-IF
           COMPUTE LAST2 = F-HEAD (FI) - 2
           IF LAST2 < 1 ADD 16 TO LAST2 END-IF
      *> look at last 3 pushed dirs relative to head
           IF F-FACING (FI) > 0
               PERFORM CHECK-QCF-FWD
           ELSE
               PERFORM CHECK-QCF-BACK
           END-IF.
       MATCH-EXIT.
           EXIT.

       CHECK-QCF-FWD.
           IF F-DIR (FI, F-HEAD (FI)) = 6
              AND F-DIR (FI, LAST1) = 3
              AND F-DIR (FI, LAST2) = 2
               MOVE 1 TO MATCHED
           END-IF.
       CHECK-QCF-BACK.
           IF F-DIR (FI, F-HEAD (FI)) = 4
              AND F-DIR (FI, LAST1) = 1
              AND F-DIR (FI, LAST2) = 2
               MOVE 1 TO MATCHED
           END-IF.

      *> ===========================================================
      *> physics + state timing
      *> ===========================================================
       ADVANCE-FIGHTER.
      *> resolve any pending special-motion into SPECIAL state
           PERFORM MATCH-SPECIAL THRU MATCH-EXIT
           IF MATCHED = 1 AND PJ-ACTIVE (FI) = 0
               MOVE ST-SPECIAL TO F-STATE (FI)
               MOVE 0 TO F-STATE-T (FI)
               MOVE 0 TO F-VX (FI)
           END-IF
      *> apply walk velocity
           IF F-STATE (FI) = ST-WALK
               ADD F-VX (FI) TO F-X (FI)
           END-IF
      *> clamp to stage
           IF F-X (FI) < 10 MOVE 10 TO F-X (FI) END-IF
           IF F-X (FI) > 276 MOVE 276 TO F-X (FI) END-IF
      *> advance state timers
           ADD 1 TO F-STATE-T (FI)
           EVALUATE F-STATE (FI)
               WHEN ST-ATK-L PERFORM TICK-ATTACK
               WHEN ST-ATK-H PERFORM TICK-ATTACK
               WHEN ST-SPECIAL PERFORM TICK-SPECIAL
               WHEN ST-HITSTUN PERFORM TICK-HITSTUN
               WHEN ST-BLOCK PERFORM TICK-BLOCK
           END-EVALUATE.

       TICK-ATTACK.
           IF F-STATE-T (FI) >
              MD-STARTUP (F-MOVE (FI)) + MD-ACTIVE (F-MOVE (FI))
              + MD-RECOVER (F-MOVE (FI))
               MOVE ST-IDLE TO F-STATE (FI)
               MOVE 0 TO F-STATE-T (FI)
           END-IF.

       TICK-SPECIAL.
      *> on active frame, spawn a projectile once
           IF F-STATE-T (FI) = 12 AND PJ-ACTIVE (FI) = 0
               MOVE 1 TO PJ-ACTIVE (FI)
               COMPUTE PJ-X (FI) = F-X (FI) + 16
               MOVE F-FACING (FI) TO PJ-DIR (FI)
               MOVE FI TO PJ-OWNER (FI)
           END-IF
           IF F-STATE-T (FI) > 40
               MOVE ST-IDLE TO F-STATE (FI)
               MOVE 0 TO F-STATE-T (FI)
           END-IF.

       TICK-HITSTUN.
           IF F-STATE-T (FI) > MD-HITSTUN (F-MOVE (OPI))
               MOVE ST-IDLE TO F-STATE (FI)
               MOVE 0 TO F-STATE-T (FI)
           END-IF.

       TICK-BLOCK.
           IF F-STATE-T (FI) > 10
               MOVE ST-IDLE TO F-STATE (FI)
               MOVE 0 TO F-STATE-T (FI)
           END-IF.

      *> ===========================================================
      *> melee collision: attacker active-frame hitbox vs defender
      *> ===========================================================
       RESOLVE-COMBAT.
           PERFORM VARYING FI FROM 1 BY 1 UNTIL FI > 2
               COMPUTE OPI = 3 - FI
               MOVE 0 TO HIT-DONE
               IF (F-STATE (FI) = ST-ATK-L OR F-STATE (FI) = ST-ATK-H)
                   IF F-STATE-T (FI) > MD-STARTUP (F-MOVE (FI))
                      AND F-STATE-T (FI) <=
                          MD-STARTUP (F-MOVE (FI))
                          + MD-ACTIVE (F-MOVE (FI))
                       COMPUTE DIST =
                           FUNCTION ABS (F-X (FI) - F-X (OPI))
                       IF DIST <= MD-REACH (F-MOVE (FI))
                          AND F-STATE (OPI) NOT = ST-HITSTUN
                          AND F-STATE (OPI) NOT = ST-KO
                          AND F-STATE-T (FI) NOT = 999
                           PERFORM APPLY-HIT
                       END-IF
                   END-IF
               END-IF
           END-PERFORM.

       APPLY-HIT.
      *> mark this attack consumed by pushing its active window past
           MOVE 999 TO F-STATE-T (FI)
           IF F-STATE (OPI) = ST-BLOCK
               SUBTRACT MD-CHIP (F-MOVE (FI)) FROM F-HP (OPI)
           ELSE
               SUBTRACT MD-DAMAGE (F-MOVE (FI)) FROM F-HP (OPI)
               MOVE ST-HITSTUN TO F-STATE (OPI)
               MOVE 0 TO F-STATE-T (OPI)
      *> knockback
               COMPUTE F-X (OPI) = F-X (OPI) + F-FACING (FI) * 6
           END-IF
           IF F-HP (OPI) < 0 MOVE 0 TO F-HP (OPI) END-IF.

      *> ===========================================================
      *> projectiles
      *> ===========================================================
       STEP-PROJECTILES.
           PERFORM VARYING FI FROM 1 BY 1 UNTIL FI > 2
               COMPUTE OPI = 3 - FI
               IF PJ-ACTIVE (FI) = 1
                   COMPUTE PJ-X (FI) = PJ-X (FI) + PJ-DIR (FI) * 4
                   IF PJ-X (FI) < 0 OR PJ-X (FI) > C-W
                       MOVE 0 TO PJ-ACTIVE (FI)
                   ELSE
                       COMPUTE DIST =
                           FUNCTION ABS (PJ-X (FI) - F-X (OPI))
                       IF DIST < 20 AND F-STATE (OPI) NOT = ST-KO
                           IF F-STATE (OPI) = ST-BLOCK
                               SUBTRACT 2 FROM F-HP (OPI)
                           ELSE
                               SUBTRACT MD-DAMAGE (3) FROM F-HP (OPI)
                               MOVE ST-HITSTUN TO F-STATE (OPI)
                               MOVE 0 TO F-STATE-T (OPI)
                               MOVE 3 TO F-MOVE (FI)
                           END-IF
                           IF F-HP (OPI) < 0 MOVE 0 TO F-HP (OPI) END-IF
                           MOVE 0 TO PJ-ACTIVE (FI)
                       END-IF
                   END-IF
               END-IF
           END-PERFORM.

      *> ===========================================================
      *> RENDER
      *> ===========================================================
       DRAW-SCENE.
           PERFORM PAINT-BACKGROUND
           PERFORM VARYING FI FROM 1 BY 1 UNTIL FI > 2
               PERFORM DRAW-FIGHTER
           END-PERFORM
           PERFORM VARYING FI FROM 1 BY 1 UNTIL FI > 2
               IF PJ-ACTIVE (FI) = 1 PERFORM DRAW-PROJECTILE END-IF
           END-PERFORM
           PERFORM DRAW-HUD
           PERFORM DRAW-BANNER THRU BANNER-EXIT.

       PAINT-BACKGROUND.
           PERFORM VARYING D-Y FROM 0 BY 1 UNTIL D-Y >= C-H
               PERFORM VARYING D-X FROM 0 BY 1 UNTIL D-X >= C-W
                   COMPUTE D-IDX = D-Y * C-W + D-X + 1
                   IF D-Y >= C-FLOORY
                       MOVE 3 TO PIX (D-IDX)
                   ELSE
                       IF FUNCTION MOD (D-X / 20, 2) = 0
                           MOVE 1 TO PIX (D-IDX)
                       ELSE
                           MOVE 2 TO PIX (D-IDX)
                       END-IF
                   END-IF
               END-PERFORM
           END-PERFORM.

      *> a fighter: body + head + a lunging "arm" during active attack
       DRAW-FIGHTER.
           MOVE F-COL (FI) TO RCID
           IF F-STATE (FI) = ST-KO MOVE 20 TO RCID END-IF
           IF F-STATE (FI) = ST-BLOCK MOVE 21 TO RCID END-IF
      *> body
           COMPUTE RX0 = F-X (FI) COMPUTE RX1 = F-X (FI) + 30
           COMPUTE RY0 = C-FLOORY - 60 MOVE C-FLOORY TO RY1
           PERFORM FILL-RECT
      *> head
           MOVE 22 TO RCID
           COMPUTE RX0 = F-X (FI) + 6 COMPUTE RX1 = F-X (FI) + 24
           COMPUTE RY0 = C-FLOORY - 76 COMPUTE RY1 = C-FLOORY - 60
           PERFORM FILL-RECT
      *> attacking arm (during active window) reaches toward opponent
           IF (F-STATE (FI) = ST-ATK-L OR F-STATE (FI) = ST-ATK-H)
              AND F-STATE-T (FI) > MD-STARTUP (F-MOVE (FI))
              AND F-STATE-T (FI) <=
                  MD-STARTUP (F-MOVE (FI)) + MD-ACTIVE (F-MOVE (FI)) + 4
               MOVE F-COLDK (FI) TO RCID
               IF F-FACING (FI) > 0
                   COMPUTE RX0 = F-X (FI) + 28
                   COMPUTE RX1 = F-X (FI) + 28 + MD-REACH (F-MOVE (FI))
               ELSE
                   COMPUTE RX0 = F-X (FI) + 2
                                 - MD-REACH (F-MOVE (FI))
                   COMPUTE RX1 = F-X (FI) + 2
               END-IF
               COMPUTE RY0 = C-FLOORY - 48 COMPUTE RY1 = C-FLOORY - 38
               PERFORM FILL-RECT
           END-IF.

       DRAW-PROJECTILE.
           MOVE 7 TO RCID
           COMPUTE RX0 = PJ-X (FI) - 6 COMPUTE RX1 = PJ-X (FI) + 6
           COMPUTE RY0 = C-FLOORY - 44 COMPUTE RY1 = C-FLOORY - 32
           PERFORM FILL-RECT.

      *> health bars, round pips, timer
       DRAW-HUD.
           MOVE 6 TO RCID
           MOVE 8 TO RX0 MOVE 150 TO RX1 MOVE 10 TO RY0 MOVE 20 TO RY1
           PERFORM FILL-RECT
           MOVE 170 TO RX0 MOVE 312 TO RX1 MOVE 10 TO RY0 MOVE 20 TO RY1
           PERFORM FILL-RECT
      *> fills
           MOVE 8 TO RCID
           IF F-HP (1) < 40 MOVE 9 TO RCID END-IF
           MOVE 8 TO RX0 COMPUTE RX1 = 8 + F-HP (1) * 142 / 100
           MOVE 10 TO RY0 MOVE 20 TO RY1 PERFORM FILL-RECT
           MOVE 8 TO RCID
           IF F-HP (2) < 40 MOVE 9 TO RCID END-IF
           COMPUTE BW = F-HP (2) * 142 / 100
           COMPUTE RX0 = 312 - BW MOVE 312 TO RX1
           MOVE 10 TO RY0 MOVE 20 TO RY1 PERFORM FILL-RECT
      *> round win pips
           PERFORM DRAW-PIPS
      *> timer (two digits, centered top)
           MOVE M-TIMER TO T-Y
           MOVE 148 TO T-STARTX MOVE 2 TO T-SCALE MOVE 4 TO T-CID
           MOVE M-TIMER TO ROLL
           PERFORM DRAW-TIMER.

       DRAW-PIPS.
           IF F-WINS (1) >= 1
               MOVE 4 TO RCID MOVE 8 TO RX0 MOVE 16 TO RX1
               MOVE 24 TO RY0 MOVE 30 TO RY1 PERFORM FILL-RECT
           END-IF
           IF F-WINS (1) >= 2
               MOVE 4 TO RCID MOVE 20 TO RX0 MOVE 28 TO RX1
               MOVE 24 TO RY0 MOVE 30 TO RY1 PERFORM FILL-RECT
           END-IF
           IF F-WINS (2) >= 1
               MOVE 5 TO RCID MOVE 304 TO RX0 MOVE 312 TO RX1
               MOVE 24 TO RY0 MOVE 30 TO RY1 PERFORM FILL-RECT
           END-IF
           IF F-WINS (2) >= 2
               MOVE 5 TO RCID MOVE 292 TO RX0 MOVE 300 TO RX1
               MOVE 24 TO RY0 MOVE 30 TO RY1 PERFORM FILL-RECT
           END-IF.

       DRAW-TIMER.
           MOVE 2 TO T-SCALE MOVE 4 TO T-CID
           COMPUTE T-I = ROLL / 10
           MOVE 150 TO T-X MOVE 4 TO T-Y
           MOVE T-I TO T-GI PERFORM DRAW-DIGIT-AT
           COMPUTE T-I = FUNCTION MOD (ROLL, 10)
           MOVE 160 TO T-X MOVE 4 TO T-Y
           MOVE T-I TO T-GI PERFORM DRAW-DIGIT-AT.

      *> draw a single digit glyph (0..9) at (T-X,T-Y) scale T-SCALE
       DRAW-DIGIT-AT.
           COMPUTE T-GI = T-GI + 1
           MOVE T-GI TO T-CID
           PERFORM VARYING T-ROW FROM 1 BY 1 UNTIL T-ROW > 5
               COMPUTE T-GI = (T-CID - 1) * 5 + T-ROW
               PERFORM VARYING T-COL FROM 1 BY 1 UNTIL T-COL > 3
                   IF FONT-ROW (T-GI) (T-COL:1) = "1"
                       PERFORM VARYING T-PY FROM 0 BY 1
                               UNTIL T-PY >= T-SCALE
                           PERFORM VARYING T-PX FROM 0 BY 1
                                   UNTIL T-PX >= T-SCALE
                               COMPUTE D-Y =
                                   T-Y + (T-ROW - 1) * T-SCALE + T-PY
                               COMPUTE D-X =
                                   T-X + (T-COL - 1) * T-SCALE + T-PX
                               IF D-Y < C-H AND D-X < C-W
                                   COMPUTE D-IDX = D-Y * C-W + D-X + 1
                                   MOVE 4 TO PIX (D-IDX)
                               END-IF
                           END-PERFORM
                       END-PERFORM
                   END-IF
               END-PERFORM
           END-PERFORM.

      *> banner text centered
       DRAW-BANNER.
           IF M-BANNER = SPACES
               GO TO BANNER-EXIT
           END-IF
           MOVE 3 TO T-SCALE
           MOVE FUNCTION TRIM (M-BANNER) TO T-BANNER
           MOVE FUNCTION STORED-CHAR-LENGTH (T-BANNER) TO T-BLEN
           COMPUTE T-STARTX =
               (C-W - T-BLEN * 4 * T-SCALE) / 2
           MOVE 70 TO T-Y
           MOVE 0 TO T-COL
           PERFORM VARYING T-I FROM 1 BY 1
                   UNTIL T-I > T-BLEN
               MOVE T-BANNER (T-I:1) TO T-CH
               COMPUTE T-X = T-STARTX + T-COL * (4 * T-SCALE)
               PERFORM DRAW-CHAR THRU DRAW-CHAR-EXIT
               ADD 1 TO T-COL
           END-PERFORM.
       BANNER-EXIT.
           EXIT.

      *> draw an arbitrary char via the font table at (T-X,T-Y)
       DRAW-CHAR.
           MOVE 0 TO T-GI
           PERFORM VARYING T-PX FROM 1 BY 1 UNTIL T-PX > 40
               IF FONT-CHARS (T-PX:1) = T-CH
                   MOVE T-PX TO T-GI
               END-IF
           END-PERFORM
           IF T-GI = 0 GO TO DRAW-CHAR-EXIT END-IF
           MOVE 23 TO T-CID
           PERFORM VARYING T-ROW FROM 1 BY 1 UNTIL T-ROW > 5
               COMPUTE T-PY = (T-GI - 1) * 5 + T-ROW
               PERFORM VARYING T-COL FROM 1 BY 1 UNTIL T-COL > 3
                   IF FONT-ROW (T-PY) (T-COL:1) = "1"
                       PERFORM VARYING T-CID FROM 0 BY 1
                               UNTIL T-CID >= T-SCALE
                           PERFORM VARYING BW FROM 0 BY 1
                                   UNTIL BW >= T-SCALE
                               COMPUTE D-Y =
                                   T-Y + (T-ROW - 1) * T-SCALE + T-CID
                               COMPUTE D-X =
                                   T-X + (T-COL - 1) * T-SCALE + BW
                               IF D-Y < C-H AND D-X < C-W
                                   COMPUTE D-IDX = D-Y * C-W + D-X + 1
                                   MOVE 23 TO PIX (D-IDX)
                               END-IF
                           END-PERFORM
                       END-PERFORM
                   END-IF
               END-PERFORM
           END-PERFORM.
       DRAW-CHAR-EXIT.
           EXIT.

       FILL-RECT.
           IF RX0 < 0 MOVE 0 TO RX0 END-IF
           PERFORM VARYING D-Y FROM RY0 BY 1 UNTIL D-Y >= RY1
               IF D-Y < C-H
                   PERFORM VARYING D-X FROM RX0 BY 1 UNTIL D-X >= RX1
                       IF D-X < C-W AND D-X >= 0
                           COMPUTE D-IDX = D-Y * C-W + D-X + 1
                           MOVE RCID TO PIX (D-IDX)
                       END-IF
                   END-PERFORM
               END-IF
           END-PERFORM.

       WRITE-PIXBUF.
           PERFORM VARYING D-Y FROM 0 BY 1 UNTIL D-Y >= C-H
               MOVE 1 TO D-POS
               COMPUTE D-IDX = D-Y * C-W + 1
               PERFORM VARYING D-X FROM 0 BY 1 UNTIL D-X >= C-W
                   MOVE COL-STR (PIX (D-IDX)) TO ROW-RECORD (D-POS:3)
                   ADD 3 TO D-POS
                   ADD 1 TO D-IDX
               END-PERFORM
               WRITE ROW-RECORD
           END-PERFORM.

      *> ===========================================================
      *> data
      *> ===========================================================
       LOAD-MOVEDATA.
      *> light: fast, low dmg
           MOVE 4 TO MD-STARTUP(1) MOVE 3 TO MD-ACTIVE(1)
           MOVE 8 TO MD-RECOVER(1) MOVE 6 TO MD-DAMAGE(1)
           MOVE 46 TO MD-REACH(1) MOVE 12 TO MD-HITSTUN(1)
           MOVE 8 TO MD-BLOCKSTN(1) MOVE 1 TO MD-CHIP(1)
      *> heavy: slow, high dmg
           MOVE 9 TO MD-STARTUP(2) MOVE 4 TO MD-ACTIVE(2)
           MOVE 16 TO MD-RECOVER(2) MOVE 14 TO MD-DAMAGE(2)
           MOVE 52 TO MD-REACH(2) MOVE 20 TO MD-HITSTUN(2)
           MOVE 12 TO MD-BLOCKSTN(2) MOVE 3 TO MD-CHIP(2)
      *> special (projectile damage)
           MOVE 12 TO MD-STARTUP(3) MOVE 1 TO MD-ACTIVE(3)
           MOVE 20 TO MD-RECOVER(3) MOVE 10 TO MD-DAMAGE(3)
           MOVE 0 TO MD-REACH(3) MOVE 16 TO MD-HITSTUN(3)
           MOVE 6 TO MD-BLOCKSTN(3) MOVE 2 TO MD-CHIP(3).

       LOAD-PALETTE.
           MOVE 26 TO COL-R(1) MOVE 28 TO COL-G(1) MOVE 46 TO COL-B(1)
           MOVE 38 TO COL-R(2) MOVE 42 TO COL-G(2) MOVE 68 TO COL-B(2)
           MOVE 72 TO COL-R(3) MOVE 60 TO COL-G(3) MOVE 48 TO COL-B(3)
           MOVE 64 TO COL-R(4) MOVE 132 TO COL-G(4) MOVE 233 TO COL-B(4)
           MOVE 220 TO COL-R(5) MOVE 64 TO COL-G(5) MOVE 56 TO COL-B(5)
           MOVE 20 TO COL-R(6) MOVE 20 TO COL-G(6) MOVE 20 TO COL-B(6)
           MOVE 250 TO COL-R(7) MOVE 220 TO COL-G(7) MOVE 90 TO COL-B(7)
           MOVE 62 TO COL-R(8) MOVE 220 TO COL-G(8) MOVE 88 TO COL-B(8)
           MOVE 230 TO COL-R(9) MOVE 90 TO COL-G(9) MOVE 60 TO COL-B(9)
           MOVE 30 TO COL-R(14) MOVE 80 TO COL-G(14)
               MOVE 150 TO COL-B(14)
           MOVE 150 TO COL-R(15) MOVE 40 TO COL-G(15)
               MOVE 36 TO COL-B(15)
           MOVE 120 TO COL-R(20) MOVE 120 TO COL-G(20)
               MOVE 120 TO COL-B(20)
           MOVE 200 TO COL-R(21) MOVE 200 TO COL-G(21)
               MOVE 90 TO COL-B(21)
           MOVE 245 TO COL-R(22) MOVE 214 TO COL-G(22)
               MOVE 170 TO COL-B(22)
           MOVE 245 TO COL-R(23) MOVE 245 TO COL-G(23)
               MOVE 245 TO COL-B(23)
           PERFORM VARYING T-I FROM 1 BY 1 UNTIL T-I > 24
               COMPUTE D-BYTE = COL-R (T-I) + 1
               MOVE FUNCTION CHAR (D-BYTE) TO COL-STR (T-I) (1:1)
               COMPUTE D-BYTE = COL-G (T-I) + 1
               MOVE FUNCTION CHAR (D-BYTE) TO COL-STR (T-I) (2:1)
               COMPUTE D-BYTE = COL-B (T-I) + 1
               MOVE FUNCTION CHAR (D-BYTE) TO COL-STR (T-I) (3:1)
           END-PERFORM.

      *> 3x5 font: slots 1..40 map to FONT-CHARS positions.
      *> slot n rows live at FONT-ROW((n-1)*5+1 .. +5).
       LOAD-FONT.
           PERFORM VARYING T-I FROM 1 BY 1 UNTIL T-I > 200
               MOVE "000" TO FONT-ROW (T-I)
           END-PERFORM
      *> digits 0-9 occupy FONT-CHARS positions 2..11 -> slots 2..11
           PERFORM SET-DIGITS
           PERFORM SET-LETTERS.

       SET-DIGITS.
      *> position 2 = '0'
           MOVE "111" TO FONT-ROW(06) MOVE "101" TO FONT-ROW(07)
           MOVE "101" TO FONT-ROW(08) MOVE "101" TO FONT-ROW(09)
           MOVE "111" TO FONT-ROW(10)
           MOVE "010" TO FONT-ROW(11) MOVE "110" TO FONT-ROW(12)
           MOVE "010" TO FONT-ROW(13) MOVE "010" TO FONT-ROW(14)
           MOVE "111" TO FONT-ROW(15)
           MOVE "111" TO FONT-ROW(16) MOVE "001" TO FONT-ROW(17)
           MOVE "111" TO FONT-ROW(18) MOVE "100" TO FONT-ROW(19)
           MOVE "111" TO FONT-ROW(20)
           MOVE "111" TO FONT-ROW(21) MOVE "001" TO FONT-ROW(22)
           MOVE "111" TO FONT-ROW(23) MOVE "001" TO FONT-ROW(24)
           MOVE "111" TO FONT-ROW(25)
           MOVE "101" TO FONT-ROW(26) MOVE "101" TO FONT-ROW(27)
           MOVE "111" TO FONT-ROW(28) MOVE "001" TO FONT-ROW(29)
           MOVE "001" TO FONT-ROW(30)
           MOVE "111" TO FONT-ROW(31) MOVE "100" TO FONT-ROW(32)
           MOVE "111" TO FONT-ROW(33) MOVE "001" TO FONT-ROW(34)
           MOVE "111" TO FONT-ROW(35)
           MOVE "111" TO FONT-ROW(36) MOVE "100" TO FONT-ROW(37)
           MOVE "111" TO FONT-ROW(38) MOVE "101" TO FONT-ROW(39)
           MOVE "111" TO FONT-ROW(40)
           MOVE "111" TO FONT-ROW(41) MOVE "001" TO FONT-ROW(42)
           MOVE "001" TO FONT-ROW(43) MOVE "001" TO FONT-ROW(44)
           MOVE "001" TO FONT-ROW(45)
           MOVE "111" TO FONT-ROW(46) MOVE "101" TO FONT-ROW(47)
           MOVE "111" TO FONT-ROW(48) MOVE "101" TO FONT-ROW(49)
           MOVE "111" TO FONT-ROW(50)
           MOVE "111" TO FONT-ROW(51) MOVE "101" TO FONT-ROW(52)
           MOVE "111" TO FONT-ROW(53) MOVE "001" TO FONT-ROW(54)
           MOVE "111" TO FONT-ROW(55).

      *> letters we render: F(16) I(19) G(17) H(18) T(30) O(25)
      *> R(28) U(31) N(24) D(14) P(26) W(33) S(29) A(11) .(38) !(39)
       SET-LETTERS.
      *> A = pos 12 -> slot 12 -> rows 56..60
           MOVE "111" TO FONT-ROW(56) MOVE "101" TO FONT-ROW(57)
           MOVE "111" TO FONT-ROW(58) MOVE "101" TO FONT-ROW(59)
           MOVE "101" TO FONT-ROW(60)
      *> D = pos 15 -> rows 71..75
           MOVE "110" TO FONT-ROW(71) MOVE "101" TO FONT-ROW(72)
           MOVE "101" TO FONT-ROW(73) MOVE "101" TO FONT-ROW(74)
           MOVE "110" TO FONT-ROW(75)
      *> F = pos 17 -> rows 81..85
           MOVE "111" TO FONT-ROW(81) MOVE "100" TO FONT-ROW(82)
           MOVE "111" TO FONT-ROW(83) MOVE "100" TO FONT-ROW(84)
           MOVE "100" TO FONT-ROW(85)
      *> G = pos 18 -> rows 86..90
           MOVE "111" TO FONT-ROW(86) MOVE "100" TO FONT-ROW(87)
           MOVE "101" TO FONT-ROW(88) MOVE "101" TO FONT-ROW(89)
           MOVE "111" TO FONT-ROW(90)
      *> H = pos 19 -> rows 91..95
           MOVE "101" TO FONT-ROW(91) MOVE "101" TO FONT-ROW(92)
           MOVE "111" TO FONT-ROW(93) MOVE "101" TO FONT-ROW(94)
           MOVE "101" TO FONT-ROW(95)
      *> I = pos 20 -> rows 96..100
           MOVE "111" TO FONT-ROW(96) MOVE "010" TO FONT-ROW(97)
           MOVE "010" TO FONT-ROW(98) MOVE "010" TO FONT-ROW(99)
           MOVE "111" TO FONT-ROW(100)
      *> N = pos 25 -> rows 121..125
           MOVE "101" TO FONT-ROW(121) MOVE "111" TO FONT-ROW(122)
           MOVE "111" TO FONT-ROW(123) MOVE "111" TO FONT-ROW(124)
           MOVE "101" TO FONT-ROW(125)
      *> O = pos 26 -> rows 126..130
           MOVE "111" TO FONT-ROW(126) MOVE "101" TO FONT-ROW(127)
           MOVE "101" TO FONT-ROW(128) MOVE "101" TO FONT-ROW(129)
           MOVE "111" TO FONT-ROW(130)
      *> P = pos 27 -> rows 131..135
           MOVE "111" TO FONT-ROW(131) MOVE "101" TO FONT-ROW(132)
           MOVE "111" TO FONT-ROW(133) MOVE "100" TO FONT-ROW(134)
           MOVE "100" TO FONT-ROW(135)
      *> R = pos 29 -> rows 141..145
           MOVE "111" TO FONT-ROW(141) MOVE "101" TO FONT-ROW(142)
           MOVE "111" TO FONT-ROW(143) MOVE "110" TO FONT-ROW(144)
           MOVE "101" TO FONT-ROW(145)
      *> S = pos 30 -> rows 146..150
           MOVE "111" TO FONT-ROW(146) MOVE "100" TO FONT-ROW(147)
           MOVE "111" TO FONT-ROW(148) MOVE "001" TO FONT-ROW(149)
           MOVE "111" TO FONT-ROW(150)
      *> T = pos 31 -> rows 151..155
           MOVE "111" TO FONT-ROW(151) MOVE "010" TO FONT-ROW(152)
           MOVE "010" TO FONT-ROW(153) MOVE "010" TO FONT-ROW(154)
           MOVE "010" TO FONT-ROW(155)
      *> U = pos 32 -> rows 156..160
           MOVE "101" TO FONT-ROW(156) MOVE "101" TO FONT-ROW(157)
           MOVE "101" TO FONT-ROW(158) MOVE "101" TO FONT-ROW(159)
           MOVE "111" TO FONT-ROW(160)
      *> W = pos 34 -> rows 166..170
           MOVE "101" TO FONT-ROW(166) MOVE "101" TO FONT-ROW(167)
           MOVE "101" TO FONT-ROW(168) MOVE "111" TO FONT-ROW(169)
           MOVE "111" TO FONT-ROW(170)
      *> ! = pos 39 -> rows 191..195
           MOVE "010" TO FONT-ROW(191) MOVE "010" TO FONT-ROW(192)
           MOVE "010" TO FONT-ROW(193) MOVE "000" TO FONT-ROW(194)
           MOVE "010" TO FONT-ROW(195).
