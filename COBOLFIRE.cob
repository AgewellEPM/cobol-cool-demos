      *> ============================================================
      *> DOOMFIRE.cob  --  The PSX DOOM fire effect, in COBOL.
      *>
      *> Yes, COBOL. The 1959 language that still runs the world's
      *> banks. It computes Fabien Sanglard's fire propagation and
      *> renders every frame as raw 24-bit RGB, which ffmpeg turns
      *> into video. No graphics library -- just MOVE, PERFORM, and
      *> a 37-colour fire palette.
      *> ============================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COBOLFIRE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RGB-FILE ASSIGN TO "cobolfire.raw"
               ORGANIZATION IS SEQUENTIAL.
           SELECT MASK-FILE ASSIGN TO "mask.txt"
               ORGANIZATION IS SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  RGB-FILE
           RECORD CONTAINS 600 CHARACTERS.
       01  ROW-RECORD          PIC X(600).
       FD  MASK-FILE.
       01  MASK-LINE           PIC X(200).

       WORKING-STORAGE SECTION.
       01  CONSTS.
           05  C-W             PIC 9(4) VALUE 200.
           05  C-H             PIC 9(4) VALUE 120.
           05  C-CELLS         PIC 9(6) VALUE 24000.
           05  C-FRAMES        PIC 9(4) VALUE 320.

       01  FIRE-AREA.
           05  FIRE-CELL       OCCURS 24000 TIMES PIC 9(2) COMP.

       01  SOURCE-AREA.
           05  SOURCE-CELL     OCCURS 24000 TIMES PIC 9 COMP.
       01  MASK-EOF            PIC X VALUE "N".
       01  MASK-COL            PIC 9(4).
       01  MASK-ROW            PIC 9(4).
       01  MASK-CH             PIC X.

       01  PALETTE.
           05  PAL-R           OCCURS 37 TIMES PIC 9(3) COMP.
           05  PAL-G           OCCURS 37 TIMES PIC 9(3) COMP.
           05  PAL-B           OCCURS 37 TIMES PIC 9(3) COMP.

       01  WORK-VARS.
           05  WV-FRAME        PIC 9(4).
           05  WV-X            PIC 9(4).
           05  WV-Y            PIC 9(4).
           05  WV-SRC          PIC 9(6).
           05  WV-DST          PIC 9(6).
           05  WV-ABOVE        PIC 9(6).
           05  WV-PIXEL        PIC 9(2).
           05  WV-RND          PIC 9(2).
           05  WV-RND2         PIC 9(2).
           05  WV-DECAY        PIC 9(2).
           05  WV-NEWVAL       PIC S9(4).
           05  WV-IDX          PIC 9(6).
           05  WV-POS          PIC 9(6).
           05  WV-VAL          PIC 9(2).
           05  WV-BYTE         PIC 9(3).
           05  WV-CHAR         PIC X.
           05  WV-RANDF        PIC 9V9(6).
           05  WV-SEED         PIC 9(8).

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WV-SEED
           COMPUTE WV-RANDF = FUNCTION RANDOM(WV-SEED)
           PERFORM LOAD-PALETTE
           PERFORM INIT-FIRE
           PERFORM LOAD-MASK
           OPEN OUTPUT RGB-FILE
           PERFORM VARYING WV-FRAME FROM 1 BY 1
                   UNTIL WV-FRAME > C-FRAMES
               PERFORM APPLY-SOURCE
               PERFORM DO-FIRE
               PERFORM RENDER-FRAME
           END-PERFORM
           CLOSE RGB-FILE
           DISPLAY "Rendered " C-FRAMES " frames of burning COBOL"
           STOP RUN.

      *> ---- read mask.txt: letters become permanent flame sources ----
       LOAD-MASK.
           PERFORM VARYING WV-IDX FROM 1 BY 1 UNTIL WV-IDX > C-CELLS
               MOVE 0 TO SOURCE-CELL (WV-IDX)
           END-PERFORM
           OPEN INPUT MASK-FILE
           MOVE 0 TO MASK-ROW
           PERFORM UNTIL MASK-EOF = "Y"
               READ MASK-FILE
                   AT END MOVE "Y" TO MASK-EOF
                   NOT AT END
                       ADD 1 TO MASK-ROW
                       PERFORM VARYING MASK-COL FROM 1 BY 1
                               UNTIL MASK-COL > C-W
                           MOVE MASK-LINE (MASK-COL:1) TO MASK-CH
                           IF MASK-CH = "1"
                               COMPUTE WV-IDX =
                                   (MASK-ROW - 1) * C-W + MASK-COL
                               MOVE 1 TO SOURCE-CELL (WV-IDX)
                           END-IF
                       END-PERFORM
               END-READ
           END-PERFORM
           CLOSE MASK-FILE.

      *> ---- re-light the letter sources every frame (fire eats them) ----
       APPLY-SOURCE.
           PERFORM VARYING WV-IDX FROM 1 BY 1 UNTIL WV-IDX > C-CELLS
               IF SOURCE-CELL (WV-IDX) = 1
                   MOVE 36 TO FIRE-CELL (WV-IDX)
               END-IF
           END-PERFORM.

      *> ---- seed the grid: bottom row white-hot (36), rest cold ----
       INIT-FIRE.
           PERFORM VARYING WV-IDX FROM 1 BY 1 UNTIL WV-IDX > C-CELLS
               MOVE 0 TO FIRE-CELL (WV-IDX)
           END-PERFORM
           CONTINUE.

      *> ---- one propagation step (Sanglard's spreadFire) ----
       DO-FIRE.
           PERFORM VARYING WV-Y FROM 2 BY 1 UNTIL WV-Y > C-H
               PERFORM VARYING WV-X FROM 1 BY 1 UNTIL WV-X > C-W
                   COMPUTE WV-SRC = (WV-Y - 1) * C-W + WV-X
                   MOVE FIRE-CELL (WV-SRC) TO WV-PIXEL
                   COMPUTE WV-ABOVE = WV-SRC - C-W
                   IF WV-PIXEL = 0
                       MOVE 0 TO FIRE-CELL (WV-ABOVE)
                   ELSE
                       COMPUTE WV-RANDF = FUNCTION RANDOM
                       COMPUTE WV-RND = FUNCTION INTEGER (WV-RANDF * 3)
                       COMPUTE WV-RANDF = FUNCTION RANDOM
                       COMPUTE WV-RND2 = FUNCTION INTEGER (WV-RANDF * 3)
                       COMPUTE WV-DECAY = WV-RND2 + 2
                       COMPUTE WV-DST = WV-SRC - WV-RND + 1 - C-W
                       IF WV-DST < 1
                           MOVE 1 TO WV-DST
                       END-IF
                       IF WV-DST > C-CELLS
                           MOVE C-CELLS TO WV-DST
                       END-IF
                       COMPUTE WV-NEWVAL = WV-PIXEL - WV-DECAY
                       IF WV-NEWVAL < 0
                           MOVE 0 TO WV-NEWVAL
                       END-IF
                       MOVE WV-NEWVAL TO FIRE-CELL (WV-DST)
                   END-IF
               END-PERFORM
           END-PERFORM.

      *> ---- render current grid: top row first, RGB per pixel ----
       RENDER-FRAME.
           PERFORM VARYING WV-Y FROM 1 BY 1 UNTIL WV-Y > C-H
               MOVE SPACES TO ROW-RECORD
               MOVE 1 TO WV-POS
               PERFORM VARYING WV-X FROM 1 BY 1 UNTIL WV-X > C-W
                   COMPUTE WV-IDX = (WV-Y - 1) * C-W + WV-X
                   IF SOURCE-CELL (WV-IDX) = 1
                       MOVE 120 TO WV-BYTE
                       PERFORM PUT-BYTE
                       MOVE 220 TO WV-BYTE
                       PERFORM PUT-BYTE
                       MOVE 255 TO WV-BYTE
                       PERFORM PUT-BYTE
                   ELSE
                       MOVE FIRE-CELL (WV-IDX) TO WV-VAL
                       ADD 1 TO WV-VAL
                       MOVE PAL-R (WV-VAL) TO WV-BYTE
                       PERFORM PUT-BYTE
                       MOVE PAL-G (WV-VAL) TO WV-BYTE
                       PERFORM PUT-BYTE
                       MOVE PAL-B (WV-VAL) TO WV-BYTE
                       PERFORM PUT-BYTE
                   END-IF
               END-PERFORM
               WRITE ROW-RECORD
           END-PERFORM.

       PUT-BYTE.
           COMPUTE WV-BYTE = WV-BYTE + 1
           MOVE FUNCTION CHAR (WV-BYTE) TO WV-CHAR
           MOVE WV-CHAR TO ROW-RECORD (WV-POS:1)
           ADD 1 TO WV-POS.

      *> ---- the 37-colour DOOM fire palette (black->white) ----
       LOAD-PALETTE.
           PERFORM SET-PAL.

       SET-PAL.
           MOVE 007 TO PAL-R(01) MOVE 007 TO PAL-G(01) MOVE 007 TO
               PAL-B(01)
           MOVE 031 TO PAL-R(02) MOVE 007 TO PAL-G(02) MOVE 007 TO
               PAL-B(02)
           MOVE 047 TO PAL-R(03) MOVE 015 TO PAL-G(03) MOVE 007 TO
               PAL-B(03)
           MOVE 071 TO PAL-R(04) MOVE 015 TO PAL-G(04) MOVE 007 TO
               PAL-B(04)
           MOVE 087 TO PAL-R(05) MOVE 023 TO PAL-G(05) MOVE 007 TO
               PAL-B(05)
           MOVE 103 TO PAL-R(06) MOVE 031 TO PAL-G(06) MOVE 007 TO
               PAL-B(06)
           MOVE 119 TO PAL-R(07) MOVE 031 TO PAL-G(07) MOVE 007 TO
               PAL-B(07)
           MOVE 143 TO PAL-R(08) MOVE 039 TO PAL-G(08) MOVE 007 TO
               PAL-B(08)
           MOVE 159 TO PAL-R(09) MOVE 047 TO PAL-G(09) MOVE 007 TO
               PAL-B(09)
           MOVE 175 TO PAL-R(10) MOVE 063 TO PAL-G(10) MOVE 007 TO
               PAL-B(10)
           MOVE 191 TO PAL-R(11) MOVE 071 TO PAL-G(11) MOVE 007 TO
               PAL-B(11)
           MOVE 199 TO PAL-R(12) MOVE 071 TO PAL-G(12) MOVE 007 TO
               PAL-B(12)
           MOVE 223 TO PAL-R(13) MOVE 079 TO PAL-G(13) MOVE 007 TO
               PAL-B(13)
           MOVE 223 TO PAL-R(14) MOVE 087 TO PAL-G(14) MOVE 007 TO
               PAL-B(14)
           MOVE 223 TO PAL-R(15) MOVE 087 TO PAL-G(15) MOVE 007 TO
               PAL-B(15)
           MOVE 215 TO PAL-R(16) MOVE 095 TO PAL-G(16) MOVE 007 TO
               PAL-B(16)
           MOVE 215 TO PAL-R(17) MOVE 095 TO PAL-G(17) MOVE 007 TO
               PAL-B(17)
           MOVE 215 TO PAL-R(18) MOVE 103 TO PAL-G(18) MOVE 015 TO
               PAL-B(18)
           MOVE 207 TO PAL-R(19) MOVE 111 TO PAL-G(19) MOVE 015 TO
               PAL-B(19)
           MOVE 207 TO PAL-R(20) MOVE 119 TO PAL-G(20) MOVE 015 TO
               PAL-B(20)
           MOVE 207 TO PAL-R(21) MOVE 127 TO PAL-G(21) MOVE 015 TO
               PAL-B(21)
           MOVE 207 TO PAL-R(22) MOVE 135 TO PAL-G(22) MOVE 023 TO
               PAL-B(22)
           MOVE 199 TO PAL-R(23) MOVE 135 TO PAL-G(23) MOVE 023 TO
               PAL-B(23)
           MOVE 199 TO PAL-R(24) MOVE 143 TO PAL-G(24) MOVE 023 TO
               PAL-B(24)
           MOVE 199 TO PAL-R(25) MOVE 151 TO PAL-G(25) MOVE 031 TO
               PAL-B(25)
           MOVE 191 TO PAL-R(26) MOVE 159 TO PAL-G(26) MOVE 031 TO
               PAL-B(26)
           MOVE 191 TO PAL-R(27) MOVE 159 TO PAL-G(27) MOVE 031 TO
               PAL-B(27)
           MOVE 191 TO PAL-R(28) MOVE 167 TO PAL-G(28) MOVE 039 TO
               PAL-B(28)
           MOVE 191 TO PAL-R(29) MOVE 167 TO PAL-G(29) MOVE 039 TO
               PAL-B(29)
           MOVE 191 TO PAL-R(30) MOVE 175 TO PAL-G(30) MOVE 047 TO
               PAL-B(30)
           MOVE 183 TO PAL-R(31) MOVE 175 TO PAL-G(31) MOVE 047 TO
               PAL-B(31)
           MOVE 183 TO PAL-R(32) MOVE 183 TO PAL-G(32) MOVE 047 TO
               PAL-B(32)
           MOVE 183 TO PAL-R(33) MOVE 183 TO PAL-G(33) MOVE 055 TO
               PAL-B(33)
           MOVE 207 TO PAL-R(34) MOVE 207 TO PAL-G(34) MOVE 111 TO
               PAL-B(34)
           MOVE 223 TO PAL-R(35) MOVE 223 TO PAL-G(35) MOVE 159 TO
               PAL-B(35)
           MOVE 239 TO PAL-R(36) MOVE 239 TO PAL-G(36) MOVE 199 TO
               PAL-B(36)
           MOVE 255 TO PAL-R(37) MOVE 255 TO PAL-G(37) MOVE 255 TO
               PAL-B(37).
