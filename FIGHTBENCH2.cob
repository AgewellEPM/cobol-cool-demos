      *> ============================================================
      *> FIGHTBENCH.cob  --  M0 render-budget gate for COBOL FIGHTER.
      *>
      *> Renders a full fighting-game scene EVERY frame (worst case, no
      *> slab optimisation yet): scrolling background, a floor, two moving
      *> fighter bodies, two health bars. 320x224 (PS2-authentic low res),
      *> raw RGB24 via the proven gnucobol:raw-rgb24-video mechanism.
      *>
      *> Purpose: measure wall-clock + prove byte-exact output so we know
      *> whether the fighter renders offline-only or can approach realtime.
      *> Each loop owns its own index (no shared PERFORM VARYING counter);
      *> no GO TO leaves a PERFORM range. (The two proven COBOL bug peels.)
      *> ============================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FIGHTBENCH2.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RGB-FILE ASSIGN TO "fightbench2.raw"
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
           05  C-FRAMES        PIC 9(4) VALUE 300.
           05  C-FLOORY        PIC 9(4) VALUE 180.

       01  PIXBUF.
           05  PIX OCCURS 71680 TIMES PIC 9(3) COMP.

       01  PALETTE.
           05  COL-R OCCURS 16 TIMES PIC 9(3) COMP.
           05  COL-G OCCURS 16 TIMES PIC 9(3) COMP.
           05  COL-B OCCURS 16 TIMES PIC 9(3) COMP.
       01  COLSTR.
           05  COL-STR OCCURS 16 TIMES PIC X(3).

      *> distinct indices per scope (shared-counter peel)
       01  WORK.
           05  WV-FRAME        PIC 9(4).
           05  WV-Y            PIC 9(4).
           05  WV-X            PIC 9(4).
           05  WV-IDX          PIC 9(6).
           05  WV-CID          PIC 9(3).
           05  WV-SCROLL       PIC 9(4).
           05  WV-BAND         PIC 9(4).
           05  P1X             PIC 9(4).
           05  P2X             PIC 9(4).
           05  P1HP            PIC 9(4).
           05  P2HP            PIC 9(4).
           05  WV-PHASE        PIC 9(4).

       01  DRAW.
           05  D-Y             PIC 9(4).
           05  D-X             PIC 9(4).
           05  D-POS           PIC 9(6).
           05  D-IDX           PIC 9(6).
           05  D-BYTE          PIC 9(3).
           05  D-CHAR          PIC X.
           05  RX0             PIC 9(4).
           05  RX1             PIC 9(4).
           05  RY0             PIC 9(4).
           05  RY1             PIC 9(4).
           05  RCID            PIC 9(3).
           05  BW              PIC 9(4).

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM LOAD-PALETTE
           OPEN OUTPUT RGB-FILE
           PERFORM VARYING WV-FRAME FROM 1 BY 1
                   UNTIL WV-FRAME > C-FRAMES
               PERFORM COMPUTE-SCENE
               PERFORM DRAW-SCENE
               PERFORM WRITE-PIXBUF
           END-PERFORM
           CLOSE RGB-FILE
           DISPLAY "FIGHTBENCH rendered " C-FRAMES " frames at "
                   C-W "x" C-H
           STOP RUN.

      *> --- per-frame animation state (fighters bob + close in) -------
       COMPUTE-SCENE.
           COMPUTE WV-SCROLL = FUNCTION MOD (WV-FRAME * 2, C-W)
      *> P1 walks right, P2 walks left, meeting in the middle then back
           COMPUTE WV-PHASE = FUNCTION MOD (WV-FRAME, 240)
           IF WV-PHASE > 120
               COMPUTE WV-PHASE = 240 - WV-PHASE
           END-IF
           COMPUTE P1X = 40 + WV-PHASE
           COMPUTE P2X = 250 - WV-PHASE
      *> health bars drain over the run
           COMPUTE P1HP = 100 - FUNCTION MOD (WV-FRAME, 100)
           COMPUTE P2HP = 100 - FUNCTION MOD (WV-FRAME * 2, 100).

      *> --- paint the whole frame (worst-case full repaint) -----------
       DRAW-SCENE.
      *> background: scrolling vertical bands (motion every frame)
           PERFORM VARYING D-Y FROM 0 BY 1 UNTIL D-Y >= C-H
               PERFORM VARYING D-X FROM 0 BY 1 UNTIL D-X >= C-W
                   COMPUTE WV-BAND =
                       FUNCTION MOD ((D-X + WV-SCROLL) / 16, 2)
                   COMPUTE WV-IDX = D-Y * C-W + D-X + 1
                   IF D-Y >= C-FLOORY
                       MOVE 3 TO PIX (WV-IDX)
                   ELSE
                       IF WV-BAND = 0
                           MOVE 1 TO PIX (WV-IDX)
                       ELSE
                           MOVE 2 TO PIX (WV-IDX)
                       END-IF
                   END-IF
               END-PERFORM
           END-PERFORM
      *> fighter 1 (blue) and fighter 2 (red): 34x72 bodies on the floor
           MOVE P1X TO RX0 COMPUTE RX1 = P1X + 34
           COMPUTE RY0 = C-FLOORY - 72 MOVE C-FLOORY TO RY1
           MOVE 4 TO RCID PERFORM FILL-RECT
           MOVE P2X TO RX0 COMPUTE RX1 = P2X + 34
           MOVE 5 TO RCID PERFORM FILL-RECT
      *> health bar backs
           MOVE 10 TO RX0 MOVE 150 TO RX1 MOVE 10 TO RY0 MOVE 22 TO RY1
           MOVE 6 TO RCID PERFORM FILL-RECT
           MOVE 170 TO RX0 MOVE 310 TO RX1 MOVE 10 TO RY0 MOVE 22 TO RY1
           MOVE 6 TO RCID PERFORM FILL-RECT
      *> health bar fills (green, width scales with HP)
           MOVE 10 TO RX0 COMPUTE RX1 = 10 + P1HP * 140 / 100
           MOVE 10 TO RY0 MOVE 22 TO RY1 MOVE 7 TO RCID PERFORM FILL-RECT
           COMPUTE BW = P2HP * 140 / 100
           COMPUTE RX0 = 310 - BW MOVE 310 TO RX1
           MOVE 10 TO RY0 MOVE 22 TO RY1 MOVE 7 TO RCID PERFORM FILL-RECT.

      *> filled rectangle [RX0,RX1) x [RY0,RY1) in color RCID, clipped
       FILL-RECT.
           PERFORM VARYING D-Y FROM RY0 BY 1 UNTIL D-Y >= RY1
               IF D-Y < C-H
                   PERFORM VARYING D-X FROM RX0 BY 1 UNTIL D-X >= RX1
                       IF D-X < C-W
                           COMPUTE D-IDX = D-Y * C-W + D-X + 1
                           MOVE RCID TO PIX (D-IDX)
                       END-IF
                   END-PERFORM
               END-IF
           END-PERFORM.

      *> --- emit the frame: proven raw-rgb24 mechanism ----------------
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

       LOAD-PALETTE.
      *> 1,2 = bg bands  3 = floor  4 = P1  5 = P2  6 = hp back
      *> 7 = hp green
           MOVE 026 TO COL-R(01) MOVE 028 TO COL-G(01)
               MOVE 046 TO COL-B(01)
           MOVE 038 TO COL-R(02) MOVE 042 TO COL-G(02)
               MOVE 068 TO COL-B(02)
           MOVE 072 TO COL-R(03) MOVE 060 TO COL-G(03)
               MOVE 048 TO COL-B(03)
           MOVE 064 TO COL-R(04) MOVE 132 TO COL-G(04)
               MOVE 233 TO COL-B(04)
           MOVE 220 TO COL-R(05) MOVE 064 TO COL-G(05)
               MOVE 056 TO COL-B(05)
           MOVE 020 TO COL-R(06) MOVE 020 TO COL-G(06)
               MOVE 020 TO COL-B(06)
           MOVE 062 TO COL-R(07) MOVE 220 TO COL-G(07)
               MOVE 088 TO COL-B(07)
           PERFORM VARYING WV-IDX FROM 1 BY 1 UNTIL WV-IDX > 16
               COMPUTE D-BYTE = COL-R (WV-IDX) + 1
               MOVE FUNCTION CHAR (D-BYTE) TO COL-STR (WV-IDX) (1:1)
               COMPUTE D-BYTE = COL-G (WV-IDX) + 1
               MOVE FUNCTION CHAR (D-BYTE) TO COL-STR (WV-IDX) (2:1)
               COMPUTE D-BYTE = COL-B (WV-IDX) + 1
               MOVE FUNCTION CHAR (D-BYTE) TO COL-STR (WV-IDX) (3:1)
           END-PERFORM.
