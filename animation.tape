# VHS tape — records src/specter.py to assets/specter.gif
# Run from the repo root:   mkdir -p assets && vhs animation.tape
# Needs: vhs, ttyd, ffmpeg on PATH, and the FontFamily below installed
#
# Values taken from src/specter.py:
#   --seed 7       same layout as the README snapshot; first glitch at t=3.19s
#                  (wraith: t=4.95s), so an 8s recording always catches one
#   --fps 30       script default; Framerate below matches it so no frames are
#                  dropped or duplicated. Lower both (e.g. 20) for a smaller GIF.
#   size           the script fills the whole terminal and needs ≥ 40×18 cells.
#                  1000×820 px at FontSize 14 gives roughly 110×44 cells, close
#                  to the 110×48 the --snapshot fallback uses.
#   exit           runs until Ctrl+C, then restores the screen itself.
#
# For the wraith: change the Output name and add "--form wraith" to the command.

Output assets/specter.gif

Require python3

# ── Look ─────────────────────────────────────────────────────────────
Set Shell "bash"
Set FontSize 14
Set FontFamily "Courier Prime"
Set Width 800
Set Height 800
Set Padding 6
#Set Theme "Catppuccin Mocha"
# Set WindowBar Colorful
Set CursorBlink false
Set Framerate 30
Set PlaybackSpeed 1.0
Set LoopOffset 0%

# ── Start off-camera; the pause lets Python start and draw the first frame
Hide
Type "clear && python3 src/specter.py --palette spectral --name Stranger-Scripts --seed 7 --fps 30"
Enter
Sleep 500ms
Show

# ── Record (covers the first glitch at 3.19s)
Sleep 8s

# ── Quit off-camera; specter.py restores the screen on Ctrl+C
Hide
Ctrl+C
Sleep 200ms
