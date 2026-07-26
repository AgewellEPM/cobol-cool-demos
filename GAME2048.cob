      *> ============================================================
      *> GAME2048.cob  --  2048, playing itself, in COBOL.
      *>
      *> Real 2048 rules (slide + merge + spawn) with a corner-stacking
      *> AI, rendered to raw 24-bit RGB frames: coloured tiles and a
      *> hand-drawn 3x5 pixel font for the numbers. ffmpeg turns the
      *> frames into a gameplay video. No graphics library.
      *> ============================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GAME2048.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RGB-FILE ASSIGN TO "game2048.raw"
               ORGANIZATION IS SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  RGB-FILE
           RECORD CONTAINS 780 CHARACTERS.
       01  ROW-RECORD          PIC X(780).

       WORKING-STORAGE SECTION.
      *> ---- geometry ---------------------------------------------
       01  GEO.
           05  C-W             PIC 9(4) VALUE 260.
           05  C-H             PIC 9(4) VALUE 260.
           05  C-TILE          PIC 9(4) VALUE 50.
           05  C-GAP           PIC 9(4) VALUE 12.
           05  C-MAXMOVES      PIC 9(4) VALUE 250.
           05  C-HOLD          PIC 9(2) VALUE 1.

      *> ---- board ------------------------------------------------
       01  BOARD.
           05  CELL OCCURS 4 TIMES.
               10  CELLV OCCURS 4 TIMES PIC 9(6).
       01  LINE-BUF.
           05  LB OCCURS 4 TIMES PIC 9(6).
       01  OUT-BUF.
           05  OB OCCURS 4 TIMES PIC 9(6).
       01  SHADOW-BUF.
           05  SB OCCURS 4 TIMES PIC 9(6).

      *> ---- per-pixel colour-id buffer ---------------------------
       01  PIXBUF.
           05  PIX OCCURS 67600 TIMES PIC 9(3) COMP.

      *> ---- colour table (id -> rgb) -----------------------------
       01  COLTAB.
           05  COL-R OCCURS 20 TIMES PIC 9(3) COMP.
           05  COL-G OCCURS 20 TIMES PIC 9(3) COMP.
           05  COL-B OCCURS 20 TIMES PIC 9(3) COMP.

      *> ---- 3x5 digit font, 10 digits x 5 rows -------------------
       01  FONT-TAB.
           05  FONT-ROW OCCURS 50 TIMES PIC X(3).

       01  WORK.
           05  WV-R            PIC 9(4).
           05  WV-C            PIC 9(4).
           05  WV-I            PIC 9(4).
           05  WV-J            PIC 9(4).
           05  WV-K            PIC 9(4).
           05  WV-MOVED        PIC X.
           05  WV-ANY          PIC X.
           05  WV-VAL          PIC 9(6).
           05  WV-EXP          PIC 9(2).
           05  WV-CID          PIC 9(3).
           05  WV-EMPTY        PIC 9(2).
           05  WV-SPAWNK       PIC 9(2).
           05  WV-MOVES        PIC 9(4).
           05  WV-FRAME        PIC 9(2).
           05  WV-DIR          PIC 9.
           05  WV-RANDF        PIC 9V9(6).
           05  WV-SEED         PIC 9(8).
           05  WV-GAMEOVER     PIC X VALUE "N".

      *> ---- pixel/drawing scratch --------------------------------
       01  DRAW.
           05  D-X             PIC 9(4).
           05  D-Y             PIC 9(4).
           05  D-X0            PIC 9(4).
           05  D-Y0            PIC 9(4).
           05  D-PX            PIC 9(4).
           05  D-PY            PIC 9(4).
           05  D-IDX           PIC 9(6).
           05  D-NUMS          PIC X(6).
           05  D-NLEN          PIC 9.
           05  D-DIG           PIC 9.
           05  D-CH            PIC X.
           05  D-COL           PIC 9(4).
           05  D-ROW           PIC 9.
           05  D-SCALE         PIC 9.
           05  D-TXTW          PIC 9(4).
           05  D-STARTX        PIC 9(4).
           05  D-STARTY        PIC 9(4).
           05  D-GI            PIC 9(3).
           05  D-BYTE          PIC 9(3).
           05  D-CHAR          PIC X.
           05  D-POS           PIC 9(6).
           05  D-TEXTID        PIC 9(3).
           05  D-FI            PIC 9.

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 2 TO WV-SEED
           COMPUTE WV-RANDF = FUNCTION RANDOM(WV-SEED)
           PERFORM LOAD-COLORS
           PERFORM LOAD-FONT
           PERFORM CLEAR-BOARD
           PERFORM SPAWN-TILE THRU SPAWN-EXIT
           PERFORM SPAWN-TILE THRU SPAWN-EXIT
           OPEN OUTPUT RGB-FILE
           PERFORM RENDER-HOLD
           MOVE 0 TO WV-MOVES
           PERFORM UNTIL WV-GAMEOVER = "Y" OR WV-MOVES > C-MAXMOVES
               PERFORM CHOOSE-AND-MOVE THRU CHOOSE-EXIT
               IF WV-ANY = "Y"
                   PERFORM SPAWN-TILE THRU SPAWN-EXIT
                   PERFORM RENDER-HOLD
                   ADD 1 TO WV-MOVES
               ELSE
                   MOVE "Y" TO WV-GAMEOVER
               END-IF
           END-PERFORM
           PERFORM RENDER-HOLD
           PERFORM RENDER-HOLD
           CLOSE RGB-FILE
           DISPLAY "2048 self-play finished after " WV-MOVES " moves"
           STOP RUN.

      *> ================= game logic ==============================
       CLEAR-BOARD.
           PERFORM VARYING WV-R FROM 1 BY 1 UNTIL WV-R > 4
               PERFORM VARYING WV-C FROM 1 BY 1 UNTIL WV-C > 4
                   MOVE 0 TO CELLV (WV-R WV-C)
               END-PERFORM
           END-PERFORM.

       SPAWN-TILE.
      *> pick a random empty cell, place 2 (90%) or 4 (10%)
           MOVE 0 TO WV-EMPTY
           PERFORM VARYING WV-R FROM 1 BY 1 UNTIL WV-R > 4
               PERFORM VARYING WV-C FROM 1 BY 1 UNTIL WV-C > 4
                   IF CELLV (WV-R WV-C) = 0
                       ADD 1 TO WV-EMPTY
                   END-IF
               END-PERFORM
           END-PERFORM
           IF WV-EMPTY = 0
               GO TO SPAWN-EXIT
           END-IF
           COMPUTE WV-RANDF = FUNCTION RANDOM
           COMPUTE WV-K = FUNCTION INTEGER (WV-RANDF * WV-EMPTY) + 1
           IF WV-K > WV-EMPTY
               MOVE WV-EMPTY TO WV-K
           END-IF
           COMPUTE WV-RANDF = FUNCTION RANDOM
           IF WV-RANDF < 0.1
               MOVE 4 TO WV-SPAWNK
           ELSE
               MOVE 2 TO WV-SPAWNK
           END-IF
           MOVE 0 TO WV-J
           PERFORM VARYING WV-R FROM 1 BY 1 UNTIL WV-R > 4
               PERFORM VARYING WV-C FROM 1 BY 1 UNTIL WV-C > 4
                   IF CELLV (WV-R WV-C) = 0
                       ADD 1 TO WV-J
                       IF WV-J = WV-K
                           MOVE WV-SPAWNK TO CELLV (WV-R WV-C)
                       END-IF
                   END-IF
               END-PERFORM
           END-PERFORM.
       SPAWN-EXIT.
           EXIT.

      *> slide LINE-BUF left into OUT-BUF; set WV-MOVED if changed
       SLIDE-LINE.
      *> shadow the input so we can detect whether anything changed
           MOVE LB (1) TO SB (1) MOVE LB (2) TO SB (2)
           MOVE LB (3) TO SB (3) MOVE LB (4) TO SB (4)
           MOVE 0 TO OB (1) MOVE 0 TO OB (2)
           MOVE 0 TO OB (3) MOVE 0 TO OB (4)
           MOVE "N" TO WV-MOVED
      *> compact non-zero to the left into a temp using LINE-BUF pass
           MOVE 0 TO WV-J
           PERFORM VARYING WV-I FROM 1 BY 1 UNTIL WV-I > 4
               IF LB (WV-I) NOT = 0
                   ADD 1 TO WV-J
                   MOVE LB (WV-I) TO OB (WV-J)
               END-IF
           END-PERFORM
      *> merge adjacent equals left-to-right (single pass)
           PERFORM VARYING WV-I FROM 1 BY 1 UNTIL WV-I > 3
               IF OB (WV-I) NOT = 0 AND OB (WV-I) = OB (WV-I + 1)
                   COMPUTE OB (WV-I) = OB (WV-I) * 2
                   MOVE 0 TO OB (WV-I + 1)
               END-IF
           END-PERFORM
      *> compact again
           MOVE 0 TO LB (1) MOVE 0 TO LB (2)
           MOVE 0 TO LB (3) MOVE 0 TO LB (4)
           MOVE 0 TO WV-J
           PERFORM VARYING WV-I FROM 1 BY 1 UNTIL WV-I > 4
               IF OB (WV-I) NOT = 0
                   ADD 1 TO WV-J
                   MOVE OB (WV-I) TO LB (WV-J)
               END-IF
           END-PERFORM
           MOVE LB (1) TO OB (1) MOVE LB (2) TO OB (2)
           MOVE LB (3) TO OB (3) MOVE LB (4) TO OB (4)
      *> compare against the shadow to detect a real move
           PERFORM VARYING WV-I FROM 1 BY 1 UNTIL WV-I > 4
               IF OB (WV-I) NOT = SB (WV-I)
                   MOVE "Y" TO WV-MOVED
               END-IF
           END-PERFORM.

      *> try a direction (1=left 2=right 3=up 4=down); set WV-ANY
       TRY-MOVE.
           MOVE "N" TO WV-ANY
           EVALUATE WV-DIR
               WHEN 1 PERFORM MOVE-LEFT
               WHEN 2 PERFORM MOVE-RIGHT
               WHEN 3 PERFORM MOVE-UP
               WHEN 4 PERFORM MOVE-DOWN
           END-EVALUATE.

       MOVE-LEFT.
           PERFORM VARYING WV-R FROM 1 BY 1 UNTIL WV-R > 4
               MOVE CELLV (WV-R 1) TO LB (1)
               MOVE CELLV (WV-R 2) TO LB (2)
               MOVE CELLV (WV-R 3) TO LB (3)
               MOVE CELLV (WV-R 4) TO LB (4)
               PERFORM SLIDE-LINE
               PERFORM CHECK-ROW-CHANGE
               MOVE OB (1) TO CELLV (WV-R 1)
               MOVE OB (2) TO CELLV (WV-R 2)
               MOVE OB (3) TO CELLV (WV-R 3)
               MOVE OB (4) TO CELLV (WV-R 4)
           END-PERFORM.

       MOVE-RIGHT.
           PERFORM VARYING WV-R FROM 1 BY 1 UNTIL WV-R > 4
               MOVE CELLV (WV-R 4) TO LB (1)
               MOVE CELLV (WV-R 3) TO LB (2)
               MOVE CELLV (WV-R 2) TO LB (3)
               MOVE CELLV (WV-R 1) TO LB (4)
               PERFORM SLIDE-LINE
               PERFORM CHECK-ROW-CHANGE
               MOVE OB (1) TO CELLV (WV-R 4)
               MOVE OB (2) TO CELLV (WV-R 3)
               MOVE OB (3) TO CELLV (WV-R 2)
               MOVE OB (4) TO CELLV (WV-R 1)
           END-PERFORM.

       MOVE-UP.
           PERFORM VARYING WV-C FROM 1 BY 1 UNTIL WV-C > 4
               MOVE CELLV (1 WV-C) TO LB (1)
               MOVE CELLV (2 WV-C) TO LB (2)
               MOVE CELLV (3 WV-C) TO LB (3)
               MOVE CELLV (4 WV-C) TO LB (4)
               PERFORM SLIDE-LINE
               PERFORM CHECK-ROW-CHANGE
               MOVE OB (1) TO CELLV (1 WV-C)
               MOVE OB (2) TO CELLV (2 WV-C)
               MOVE OB (3) TO CELLV (3 WV-C)
               MOVE OB (4) TO CELLV (4 WV-C)
           END-PERFORM.

       MOVE-DOWN.
           PERFORM VARYING WV-C FROM 1 BY 1 UNTIL WV-C > 4
               MOVE CELLV (4 WV-C) TO LB (1)
               MOVE CELLV (3 WV-C) TO LB (2)
               MOVE CELLV (2 WV-C) TO LB (3)
               MOVE CELLV (1 WV-C) TO LB (4)
               PERFORM SLIDE-LINE
               PERFORM CHECK-ROW-CHANGE
               MOVE OB (1) TO CELLV (4 WV-C)
               MOVE OB (2) TO CELLV (3 WV-C)
               MOVE OB (3) TO CELLV (2 WV-C)
               MOVE OB (4) TO CELLV (1 WV-C)
           END-PERFORM.

       CHECK-ROW-CHANGE.
      *> LINE-BUF was overwritten by SLIDE-LINE; compare OB vs the
      *> original captured in a shadow copy is complex, so instead
      *> SLIDE-LINE already computed WV-MOVED-free; detect via compare
      *> of pre/post here using WV-MOVED sentinel from OB vs source.
           IF WV-MOVED = "Y"
               MOVE "Y" TO WV-ANY
           END-IF.

      *> corner-stacking AI: prefer Down, then Left, Right, Up
       CHOOSE-AND-MOVE.
           MOVE 4 TO WV-DIR PERFORM TRY-MOVE
           IF WV-ANY = "Y" GO TO CHOOSE-EXIT END-IF
           MOVE 1 TO WV-DIR PERFORM TRY-MOVE
           IF WV-ANY = "Y" GO TO CHOOSE-EXIT END-IF
           MOVE 2 TO WV-DIR PERFORM TRY-MOVE
           IF WV-ANY = "Y" GO TO CHOOSE-EXIT END-IF
           MOVE 3 TO WV-DIR PERFORM TRY-MOVE.
       CHOOSE-EXIT.
           EXIT.

      *> ================= rendering ===============================
       RENDER-HOLD.
           PERFORM DRAW-BOARD
           PERFORM VARYING WV-FRAME FROM 1 BY 1 UNTIL WV-FRAME > C-HOLD
               PERFORM WRITE-PIXBUF
           END-PERFORM.

       DRAW-BOARD.
      *> background
           PERFORM VARYING D-IDX FROM 1 BY 1 UNTIL D-IDX > 67600
               MOVE 1 TO PIX (D-IDX)
           END-PERFORM
      *> tiles
           PERFORM VARYING WV-R FROM 1 BY 1 UNTIL WV-R > 4
               PERFORM VARYING WV-C FROM 1 BY 1 UNTIL WV-C > 4
                   COMPUTE D-X0 = C-GAP + (WV-C - 1) * (C-TILE + C-GAP)
                   COMPUTE D-Y0 = C-GAP + (WV-R - 1) * (C-TILE + C-GAP)
                   MOVE CELLV (WV-R WV-C) TO WV-VAL
                   PERFORM TILE-COLOR-ID
                   PERFORM FILL-TILE
                   IF WV-VAL NOT = 0
                       PERFORM DRAW-NUMBER
                   END-IF
               END-PERFORM
           END-PERFORM.

       TILE-COLOR-ID.
           IF WV-VAL = 0
               MOVE 2 TO WV-CID
           ELSE
               MOVE 0 TO WV-EXP
               MOVE WV-VAL TO WV-J
               PERFORM UNTIL WV-J < 2
                   ADD 1 TO WV-EXP
                   DIVIDE WV-J BY 2 GIVING WV-J
               END-PERFORM
               COMPUTE WV-CID = 2 + WV-EXP
               IF WV-CID > 14
                   MOVE 14 TO WV-CID
               END-IF
           END-IF.

       FILL-TILE.
           PERFORM VARYING D-PY FROM 0 BY 1 UNTIL D-PY >= C-TILE
               COMPUTE D-Y = D-Y0 + D-PY
               PERFORM VARYING D-PX FROM 0 BY 1 UNTIL D-PX >= C-TILE
                   COMPUTE D-X = D-X0 + D-PX
                   COMPUTE D-IDX = D-Y * C-W + D-X + 1
                   MOVE WV-CID TO PIX (D-IDX)
               END-PERFORM
           END-PERFORM.

      *> draw WV-VAL centred in the current tile using 3x5 font
       DRAW-NUMBER.
           MOVE WV-VAL TO D-NUMS
      *> strip leading zeros -> D-NLEN significant digits, right side
           MOVE 6 TO D-NLEN
           PERFORM VARYING WV-I FROM 1 BY 1 UNTIL WV-I > 5
               IF D-NUMS (WV-I:1) = "0"
                   SUBTRACT 1 FROM D-NLEN
               ELSE
                   MOVE 6 TO WV-I
               END-IF
           END-PERFORM
           IF WV-VAL < 10
               MOVE 1 TO D-NLEN
           END-IF
      *> choose text colour: dark for 2/4, white otherwise
           IF WV-VAL = 2 OR WV-VAL = 4
               MOVE 15 TO D-TEXTID
           ELSE
               MOVE 16 TO D-TEXTID
           END-IF
      *> scale so the number fits the tile
           MOVE 6 TO D-SCALE
           IF D-NLEN >= 3
               MOVE 4 TO D-SCALE
           END-IF
           IF D-NLEN >= 4
               MOVE 3 TO D-SCALE
           END-IF
           IF D-NLEN >= 5
               MOVE 2 TO D-SCALE
           END-IF
      *> text block width = NLEN*(3*scale) + (NLEN-1)*scale
           COMPUTE D-TXTW =
               D-NLEN * (3 * D-SCALE) + (D-NLEN - 1) * D-SCALE
           COMPUTE D-STARTX = D-X0 + (C-TILE - D-TXTW) / 2
           COMPUTE D-STARTY = D-Y0 + (C-TILE - 5 * D-SCALE) / 2
      *> render each significant digit
           COMPUTE WV-K = 6 - D-NLEN + 1
           MOVE 0 TO WV-J
           PERFORM VARYING WV-I FROM WV-K BY 1 UNTIL WV-I > 6
               MOVE D-NUMS (WV-I:1) TO D-CH
               COMPUTE D-DIG = FUNCTION NUMVAL (D-CH)
               COMPUTE D-COL = D-STARTX + WV-J * (4 * D-SCALE)
               PERFORM DRAW-DIGIT
               ADD 1 TO WV-J
           END-PERFORM.

      *> draw digit D-DIG at (D-COL, D-STARTY), scale D-SCALE
       DRAW-DIGIT.
           PERFORM VARYING D-ROW FROM 1 BY 1 UNTIL D-ROW > 5
               COMPUTE D-GI = D-DIG * 5 + D-ROW
               PERFORM VARYING D-FI FROM 1 BY 1 UNTIL D-FI > 3
                   IF FONT-ROW (D-GI) (D-FI:1) = "1"
                       PERFORM VARYING D-PY FROM 0 BY 1
                               UNTIL D-PY >= D-SCALE
                           PERFORM VARYING D-PX FROM 0 BY 1
                                   UNTIL D-PX >= D-SCALE
                               COMPUTE D-Y = D-STARTY
                                   + (D-ROW - 1) * D-SCALE + D-PY
                               COMPUTE D-X = D-COL
                                   + (D-FI - 1) * D-SCALE + D-PX
                               COMPUTE D-IDX = D-Y * C-W + D-X + 1
                               IF D-IDX >= 1 AND D-IDX <= 67600
                                   MOVE D-TEXTID TO PIX (D-IDX)
                               END-IF
                           END-PERFORM
                       END-PERFORM
                   END-IF
               END-PERFORM
           END-PERFORM.

       WRITE-PIXBUF.
           PERFORM VARYING D-Y FROM 0 BY 1 UNTIL D-Y >= C-H
               MOVE SPACES TO ROW-RECORD
               MOVE 1 TO D-POS
               PERFORM VARYING D-X FROM 0 BY 1 UNTIL D-X >= C-W
                   COMPUTE D-IDX = D-Y * C-W + D-X + 1
                   MOVE PIX (D-IDX) TO WV-CID
                   MOVE COL-R (WV-CID) TO D-BYTE PERFORM PUT-BYTE
                   MOVE COL-G (WV-CID) TO D-BYTE PERFORM PUT-BYTE
                   MOVE COL-B (WV-CID) TO D-BYTE PERFORM PUT-BYTE
               END-PERFORM
               WRITE ROW-RECORD
           END-PERFORM.

       PUT-BYTE.
           COMPUTE D-BYTE = D-BYTE + 1
           MOVE FUNCTION CHAR (D-BYTE) TO D-CHAR
           MOVE D-CHAR TO ROW-RECORD (D-POS:1)
           ADD 1 TO D-POS.

      *> ================= data: colours + font ====================
       LOAD-COLORS.
      *> 1 = board bg, 2 = empty cell, 3.. = tile by exponent
           MOVE 187 TO COL-R(01) MOVE 173 TO COL-G(01)
               MOVE 160 TO COL-B(01)
           MOVE 205 TO COL-R(02) MOVE 193 TO COL-G(02)
               MOVE 180 TO COL-B(02)
           MOVE 238 TO COL-R(03) MOVE 228 TO COL-G(03)
               MOVE 218 TO COL-B(03)
           MOVE 237 TO COL-R(04) MOVE 224 TO COL-G(04)
               MOVE 200 TO COL-B(04)
           MOVE 242 TO COL-R(05) MOVE 177 TO COL-G(05)
               MOVE 121 TO COL-B(05)
           MOVE 245 TO COL-R(06) MOVE 149 TO COL-G(06)
               MOVE 099 TO COL-B(06)
           MOVE 246 TO COL-R(07) MOVE 124 TO COL-G(07)
               MOVE 095 TO COL-B(07)
           MOVE 246 TO COL-R(08) MOVE 094 TO COL-G(08)
               MOVE 059 TO COL-B(08)
           MOVE 237 TO COL-R(09) MOVE 207 TO COL-G(09)
               MOVE 114 TO COL-B(09)
           MOVE 237 TO COL-R(10) MOVE 204 TO COL-G(10)
               MOVE 097 TO COL-B(10)
           MOVE 237 TO COL-R(11) MOVE 200 TO COL-G(11)
               MOVE 080 TO COL-B(11)
           MOVE 237 TO COL-R(12) MOVE 197 TO COL-G(12)
               MOVE 063 TO COL-B(12)
           MOVE 237 TO COL-R(13) MOVE 194 TO COL-G(13)
               MOVE 046 TO COL-B(13)
           MOVE 060 TO COL-R(14) MOVE 058 TO COL-G(14)
               MOVE 050 TO COL-B(14)
      *> 15 = dark text, 16 = light text
           MOVE 119 TO COL-R(15) MOVE 110 TO COL-G(15)
               MOVE 101 TO COL-B(15)
           MOVE 249 TO COL-R(16) MOVE 246 TO COL-G(16)
               MOVE 242 TO COL-B(16).

       LOAD-FONT.
      *> digit 0
           MOVE "111" TO FONT-ROW(01) MOVE "101" TO FONT-ROW(02)
           MOVE "101" TO FONT-ROW(03) MOVE "101" TO FONT-ROW(04)
           MOVE "111" TO FONT-ROW(05)
      *> digit 1
           MOVE "010" TO FONT-ROW(06) MOVE "110" TO FONT-ROW(07)
           MOVE "010" TO FONT-ROW(08) MOVE "010" TO FONT-ROW(09)
           MOVE "111" TO FONT-ROW(10)
      *> digit 2
           MOVE "111" TO FONT-ROW(11) MOVE "001" TO FONT-ROW(12)
           MOVE "111" TO FONT-ROW(13) MOVE "100" TO FONT-ROW(14)
           MOVE "111" TO FONT-ROW(15)
      *> digit 3
           MOVE "111" TO FONT-ROW(16) MOVE "001" TO FONT-ROW(17)
           MOVE "111" TO FONT-ROW(18) MOVE "001" TO FONT-ROW(19)
           MOVE "111" TO FONT-ROW(20)
      *> digit 4
           MOVE "101" TO FONT-ROW(21) MOVE "101" TO FONT-ROW(22)
           MOVE "111" TO FONT-ROW(23) MOVE "001" TO FONT-ROW(24)
           MOVE "001" TO FONT-ROW(25)
      *> digit 5
           MOVE "111" TO FONT-ROW(26) MOVE "100" TO FONT-ROW(27)
           MOVE "111" TO FONT-ROW(28) MOVE "001" TO FONT-ROW(29)
           MOVE "111" TO FONT-ROW(30)
      *> digit 6
           MOVE "111" TO FONT-ROW(31) MOVE "100" TO FONT-ROW(32)
           MOVE "111" TO FONT-ROW(33) MOVE "101" TO FONT-ROW(34)
           MOVE "111" TO FONT-ROW(35)
      *> digit 7
           MOVE "111" TO FONT-ROW(36) MOVE "001" TO FONT-ROW(37)
           MOVE "001" TO FONT-ROW(38) MOVE "001" TO FONT-ROW(39)
           MOVE "001" TO FONT-ROW(40)
      *> digit 8
           MOVE "111" TO FONT-ROW(41) MOVE "101" TO FONT-ROW(42)
           MOVE "111" TO FONT-ROW(43) MOVE "101" TO FONT-ROW(44)
           MOVE "111" TO FONT-ROW(45)
      *> digit 9
           MOVE "111" TO FONT-ROW(46) MOVE "101" TO FONT-ROW(47)
           MOVE "111" TO FONT-ROW(48) MOVE "001" TO FONT-ROW(49)
           MOVE "111" TO FONT-ROW(50).
