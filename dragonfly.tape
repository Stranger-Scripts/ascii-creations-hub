# VHS tape — records src/dragonfly.py to assets/dragonfly.gif
# Run from the repo root:   mkdir -p assets && vhs dragonfly.tape
# Needs: vhs, ttyd, ffmpeg on PATH, and the FontFamily below installed
#
# Values taken from src/dragonfly.py:
#   --seed 7       fixes the waves, tree line, reeds and the two fish ripples
#   --fps 30       script default; Framerate below matches it
#   length         one loop is 21.5 s (PERIOD), so the 21.5 s Sleep records exactly
#                  one loop and the GIF loops seamlessly. For a shorter clip, Sleep
#                  less: 0–11.5 s is the flight and landing.
#   size           the script fills the terminal and needs ≥ 40×18 cells. It also
#                  works in a tall terminal (e.g. Width 720 / Height 1280 for a
#                  9:16 vertical video), the branch just gets fewer twigs.
#   exit           runs until Ctrl+C, then restores the screen itself.

Output assets/dragonfly.gif

Require python3

# ── Look ─────────────────────────────────────────────────────────────
Set Shell "bash"
Set FontSize 14
Set FontFamily "Courier Prime"
Set Width 800
Set Height 800
Set Padding 6
Set CursorBlink false
Set Framerate 30
Set PlaybackSpeed 1.0
Set LoopOffset 0%

# ── Start off-camera; the pause lets Python start and draw the first frame
Hide
Type "clear && python3 src/dragonfly.py --seed 7 --fps 30"
Enter
Sleep 500ms
Show

# ── Record one full loop
Sleep 21.5s

# ── Quit off-camera; dragonfly.py restores the screen on Ctrl+C
Hide
Ctrl+C
Sleep 200ms
