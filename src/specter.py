#!/usr/bin/env python3
"""
specter.py - an animated ASCII ghost for your terminal.

No dependencies, Python 3.8+. Looks best in a truecolor terminal
(Windows Terminal, kitty, WezTerm, Alacritty, GNOME Terminal, iTerm2, ...).

    python specter.py                      # halftone sheet ghost
    python specter.py --glyphs blocks      # chunkier pixel look
    python specter.py --glyphs ascii       # no Unicode needed
    python specter.py --form wraith        # the hooded wraith with claws
    python specter.py --palette void --name nullcaller --no-glitch
    python specter.py --list-palettes
    python specter.py --help               # see the full list of options

Ctrl+C to quit.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import shutil
import sys
import time

# --------------------------------------------------------------------------- #
# palettes
# --------------------------------------------------------------------------- #

PALETTES = {
    # white halftone sheet on midnight navy (default for --form sheet)
    "halftone": {
        "body": [(16, 21, 34), (58, 66, 86), (140, 148, 168), (218, 222, 232), (255, 255, 255)],
        "edge": (235, 238, 245), "eyes": (255, 40, 60), "glow": (120, 20, 35),
        "wisp": (225, 230, 240), "star": (120, 130, 155), "mini": (70, 78, 100),
        "glitch": (255, 40, 90), "hud": (110, 118, 140), "accent": (210, 216, 230),
        "bg": (13, 17, 28), "bar": (21, 26, 40),
    },
    # cold, pale-blue wraith with burning red eyes
    "spectral": {
        "body": [(10, 16, 38), (28, 52, 110), (62, 104, 190), (130, 180, 250), (225, 240, 255)],
        "edge": (150, 200, 255), "eyes": (255, 45, 70), "glow": (150, 20, 45),
        "wisp": (120, 200, 255), "star": (150, 160, 200), "mini": (70, 82, 128),
        "glitch": (255, 30, 150), "hud": (105, 115, 145), "accent": (110, 190, 255),
        "bg": (5, 6, 12), "bar": (14, 16, 28),
    },
    # violet void, white-hot eyes
    "void": {
        "body": [(14, 8, 30), (48, 20, 90), (100, 50, 170), (170, 120, 240), (240, 225, 255)],
        "edge": (190, 150, 255), "eyes": (235, 250, 255), "glow": (90, 110, 170),
        "wisp": (180, 130, 255), "star": (150, 140, 190), "mini": (84, 62, 124),
        "glitch": (0, 255, 200), "hud": (120, 110, 150), "accent": (180, 140, 255),
        "bg": (6, 4, 12), "bar": (16, 12, 28),
    },
    # sickly ectoplasm green, sulphur eyes
    "ecto": {
        "body": [(6, 20, 14), (20, 70, 40), (50, 150, 80), (130, 230, 140), (220, 255, 220)],
        "edge": (140, 255, 170), "eyes": (255, 240, 120), "glow": (120, 100, 20),
        "wisp": (120, 255, 150), "star": (140, 170, 150), "mini": (52, 94, 68),
        "glitch": (255, 60, 200), "hud": (100, 130, 110), "accent": (120, 255, 160),
        "bg": (4, 8, 6), "bar": (10, 18, 14),
    },
    # bone white, blood eyes
    "bone": {
        "body": [(14, 14, 16), (50, 50, 56), (105, 105, 115), (175, 175, 185), (245, 245, 250)],
        "edge": (210, 210, 220), "eyes": (255, 30, 30), "glow": (120, 10, 10),
        "wisp": (200, 200, 210), "star": (140, 140, 150), "mini": (72, 72, 80),
        "glitch": (255, 0, 60), "hud": (120, 120, 128), "accent": (220, 220, 230),
        "bg": (6, 6, 7), "bar": (16, 16, 18),
    },
}

LEVELS = 32  # colour quantisation steps (fewer escape codes per frame)


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def smoothstep(a, b, x):
    if x <= a:
        return 0.0
    if x >= b:
        return 1.0
    x = (x - a) / (b - a)
    return x * x * (3.0 - 2.0 * x)


def scale(rgb, k):
    return tuple(int(clamp(c * k, 0, 255)) for c in rgb)


def gradient(stops, t):
    t = clamp(t) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    f = t - i
    a, b = stops[i], stops[i + 1]
    return tuple(int(a[j] + (b[j] - a[j]) * f) for j in range(3))


def q(x):
    """brightness 0..1 -> palette level index"""
    i = int(x * (LEVELS - 1) + 0.5)
    return 0 if i < 0 else LEVELS - 1 if i >= LEVELS else i


class Styles:
    """Pre-built ANSI escape strings so the hot loop only does lookups."""

    def __init__(self, pal, color=True, solid_bg=True):
        self.color = color
        self.pal = pal
        fg = self.fg
        ramp = [i / (LEVELS - 1) for i in range(LEVELS)]
        self.body = [fg(gradient(pal["body"], r)) for r in ramp]
        self.edge = [fg(scale(pal["edge"], 0.12 + 0.95 * r)) for r in ramp]
        self.eyes = [fg(gradient([pal["glow"], pal["eyes"], (255, 255, 255)], r)) for r in ramp]
        self.glow = [fg(scale(pal["glow"], 0.2 + 0.9 * r)) for r in ramp]
        self.wisp = [fg(scale(pal["wisp"], 0.1 + 0.9 * r)) for r in ramp]
        self.star = [fg(scale(pal["star"], 0.15 + 0.85 * r)) for r in ramp]
        self.mini = [fg(scale(pal["mini"], 0.3 + 0.8 * r)) for r in ramp]
        self.glitch = [fg(scale(pal["glitch"], 0.4 + 0.6 * r)) for r in ramp]
        self.hud = fg(pal["hud"])
        self.hud_dim = fg(scale(pal["hud"], 0.65))
        self.accent = fg(pal["accent"])
        self.glitch_hi = fg(pal["glitch"])
        if color and solid_bg:
            self.bg = "\x1b[48;2;%d;%d;%dm" % pal["bg"]
            self.bar = "\x1b[48;2;%d;%d;%dm" % pal["bar"]
        elif color:
            self.bg = "\x1b[49m"
            self.bar = "\x1b[49m"
        else:
            self.bg = self.bar = ""

    def fg(self, rgb):
        if not self.color:
            return ""
        return "\x1b[38;2;%d;%d;%dm" % rgb


# --------------------------------------------------------------------------- #
# frame buffer
# --------------------------------------------------------------------------- #

class Buffer:
    __slots__ = ("w", "h", "ch", "st", "row_bg")

    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.ch = [[" "] * w for _ in range(h)]
        self.st = [[""] * w for _ in range(h)]
        self.row_bg = [bg] * h

    def put(self, x, y, c, s):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.ch[y][x] = c
            self.st[y][x] = s

    def text(self, x, y, s, style):
        for i, c in enumerate(s):
            self.put(x + i, y, c, style)

    def serialize(self, plain_lines=False):
        out = []
        last_row = self.h - 1
        for y in range(self.h):
            out.append("\n" if (plain_lines and y) else "" if plain_lines else "\x1b[%d;1H" % (y + 1))
            out.append(self.row_bg[y])
            cur = None
            chars, styles = self.ch[y], self.st[y]
            n = self.w - 1 if y == last_row else self.w  # avoid scroll on last cell
            parts = []
            for x in range(n):
                c = chars[x]
                if c != " ":
                    s = styles[x]
                    if s is not cur:
                        parts.append(s)
                        cur = s
                parts.append(c)
            out.append("".join(parts))
        out.append("\x1b[0m")
        return "".join(out)


# --------------------------------------------------------------------------- #
# the wraith
# --------------------------------------------------------------------------- #
# Everything is in "visual units": 1.0 == ghost height, u == horizontal offset
# from the centre line. A terminal cell is ~twice as tall as it is wide, so one
# column == 0.5 row in visual units.

V_HEAD = 0.17                    # vertical centre of the hood
R_HEAD = 0.15                    # hood radius
V_HEM = 0.50                     # where the body starts tearing into tatters
FACE_V = 0.20                    # the hollow under the hood
FACE_RU, FACE_RV = 0.078, 0.100
EYE_V, EYE_DX = 0.178, 0.042
EYE_RU, EYE_RV = 0.021, 0.012
EYE_SLANT = 0.30                 # >0: inner corners lower -> scowl
ARM_U0, ARM_U1 = 0.17, 0.42      # arms run from inside the shoulder to the wrist
ARM_V0, ARM_DROP = 0.29, 0.15    # shoulder height, how far the arm sinks

# mask codes
OUT, BODY, HOLLOW, EYE, GLOW, ARM = 0, 1, 2, 3, 4, 5

T0 = ".'`,"
T1 = ":;-~"
T2 = "=+!ir|"
T4 = "xzvnuocjt"
T5 = "%&$#?*"
T6 = "@B8QW0"
GLITCH_CHARS = "NUL0x#%$/\\|_"

MINI_SPRITES = [
    [
        "  .-\"-.  ",
        " / . . \\ ",
        " |  o  | ",
        " |     | ",
        " '^v^v^' ",
    ],
    [
        "   /\\   ",
        "  /  \\  ",
        " | -- | ",
        " |    | ",
        " /\\/\\/\\ ",
    ],
    [
        "  _..._  ",
        " /     \\ ",
        " | v v | ",
        " \\     / ",
        "  )/\\(   ",
    ],
]


def sway(v, t):
    vv = v if v > 0.0 else 0.0
    return (0.010 * math.sin(t * 0.55)
            + 0.035 * math.sin(t * 1.05 - vv * 4.2) * vv ** 1.6
            + 0.025 * math.sin(t * 2.10 - vv * 9.0) * max(0.0, vv - V_HEM) * 2.0)


def half_width(v, t):
    if v < 0.0:
        return -1.0
    if v < V_HEAD:  # pointed hood
        s = (V_HEAD - v) / V_HEAD
        return R_HEAD * max(0.0, 1.0 - s ** 1.5) ** 0.85
    shoulders = R_HEAD + 0.055 * smoothstep(V_HEAD, 0.31, v)
    taper = 1.0 - 0.82 * smoothstep(0.40, 0.97, v)
    ripple = 0.012 * math.sin(v * 23.0 - t * 2.2) * smoothstep(0.35, 0.9, v)
    breathe = 0.006 * math.sin(t * 1.7 - v * 7.0)
    return shoulders * taper + ripple + breathe


def arm_centre(tau, t, side):
    lift = 0.5 + 0.5 * math.sin(t * 0.7 + side * 1.3)
    return ARM_V0 + (ARM_DROP - 0.05 * lift) * tau ** 1.4


def arm_hit(du, v, t):
    """(fraction from top edge, tau along arm) if inside an arm, else None."""
    ad = du if du > 0.0 else -du
    if ad < ARM_U0 or ad > ARM_U1:
        return None
    side = 1.0 if du > 0.0 else -1.0
    tau = (ad - ARM_U0) / (ARM_U1 - ARM_U0)
    vc = arm_centre(tau, t, side)
    top = vc - (0.034 - 0.006 * tau)
    p = tau * 6.0
    f = p - int(p)
    tri = 1.0 - abs(f - 0.5) * 2.0
    bot = vc + 0.028 + 0.050 * tau ** 1.3 + 0.035 * tri ** 0.8 * tau
    if top < v < bot:
        return (v - top) / (bot - top), tau
    return None


def stroke_glyph(dx, dy):
    """glyph for a line segment going (dx cols, dy rows)."""
    if dy < 0:
        dx, dy = -dx, -dy
    if dy < 0.35 * abs(dx):
        return "_"
    r = dx / dy
    if r > 0.55:
        return "\\"
    if r < -0.55:
        return "/"
    return "|"


def stroke(buf, pts, styles, bmax=0.9, bmin=0.15, tip=None, cells=None):
    """Rasterise a polyline (cell coords) with slope-matched glyphs."""
    seen = set()
    n = len(pts) - 1
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        dx, dy = x1 - x0, y1 - y0
        g = stroke_glyph(dx, dy)
        steps = int(max(abs(dx), abs(dy))) + 1
        for s in range(steps):
            f = s / steps
            cx_, cy_ = int(math.floor(x0 + dx * f)), int(math.floor(y0 + dy * f))
            if (cx_, cy_) in seen:
                continue
            seen.add((cx_, cy_))
            a = (i + f) / n
            ch = tip if (tip and i == n - 1 and s == steps - 1) else g
            b = bmax + (bmin - bmax) * a
            buf.put(cx_, cy_, ch, styles[q(b)])
            if cells is not None:
                cells.append((cx_, cy_))
    return seen


# --------------------------------------------------------------------------- #
# the sheet ghost (default form)
# --------------------------------------------------------------------------- #

SHEET_R = 0.27                   # dome radius
SHEET_HEAD_V = 0.28              # where the dome meets the straight sides
SHEET_TOP = 0.02
SHEET_FLARE = 0.15               # how far the "arms" flare out
SHEET_EYE_V, SHEET_EYE_DX = 0.31, 0.122
SHEET_EYE_RU, SHEET_EYE_RV = 0.058, 0.082
SHEET_HW_REF = SHEET_R + 0.035 + SHEET_FLARE
NOISE_CHARS = "..::-=_'`,"

GLYPHS = {
    "dots": [" ", "\u00b7", "\u2022", "\u25cf"],
    "ascii": [" ", ".", ":", "o", "O", "@"],
    "blocks": [" ", "\u2591", "\u2592", "\u2593", "\u2588"],
}

BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]

SHEET_MINIS = [
    [
        " .-\"\"\"-. ",
        "/  O O  \\",
        "|       |",
        "|       |",
        "'^-^-^-^'",
    ],
    [
        "  .-~-.  ",
        " ( O O ) ",
        " |     | ",
        " |_/\\_/\\",
    ],
    [
        "  .---.  ",
        " / o o \\ ",
        " |     | ",
        " | ,'. | ",
        " '/ \\ \\' ",
    ],
]


def sheet_sway(v, t):
    vv = v if v > 0.0 else 0.0
    return 0.012 * math.sin(t * 0.6) + 0.022 * math.sin(t * 1.2 - vv * 4.0) * vv * vv


def sheet_half_width(v, t):
    if v < SHEET_TOP:
        return -1.0
    if v < SHEET_HEAD_V:
        s = (SHEET_HEAD_V - v) / (SHEET_HEAD_V - SHEET_TOP)
        return SHEET_R * math.sqrt(max(0.0, 1.0 - s * s))
    w = SHEET_R + 0.035 * smoothstep(SHEET_HEAD_V, 0.55, v)
    flare = SHEET_FLARE * smoothstep(0.50, 0.76, v) ** 1.4
    flap = 0.018 * math.sin(t * 1.6 - v * 8.0) * smoothstep(0.5, 0.8, v)
    return w + flare + flap


def cell_hash(a, b, c=0):
    h = (a * 374761393 + b * 668265263 + c * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h ^ (h >> 16)) & 0xFFFF


class Specter:
    def __init__(self, args, styles):
        self.st = styles
        self.rng = random.Random(args.seed)
        rng = self.rng
        self.name = args.name
        self.form = args.form
        self.glitch_enabled = not args.no_glitch
        g = args.glyphs if (UNICODE or args.glyphs == "ascii") else "ascii"
        self.ramp = GLYPHS[g]
        self.drip_chars = ("\u2022", "\u00b7") if g == "dots" else ("|", ":")
        self.mini_sprites = SHEET_MINIS if self.form == "sheet" else MINI_SPRITES
        n = self.n_tendrils = max(3, args.tendrils)
        self.t_len = []
        for i in range(n):
            off = abs((i + 0.5) / n * 2.0 - 1.0)  # 0 centre .. 1 sides
            self.t_len.append(rng.uniform(0.70, 1.0) * (1.0 - 0.30 * off * off))
        self.t_phase = [rng.uniform(0, math.tau) for _ in range(n)]
        self.strands = []
        for k in range(max(2, args.strands)):
            a = (k + 0.5) / max(2, args.strands) * 2.0 - 1.0
            self.strands.append({
                "u0": a * 0.11 + rng.uniform(-0.015, 0.015),
                "v0": rng.uniform(0.60, 0.74),
                "len": rng.uniform(0.24, 0.40) * (1.0 - 0.35 * abs(a)),
                "amp": rng.uniform(0.02, 0.05),
                "ph": rng.uniform(0, math.tau),
            })
        words = []
        for w in (args.name, "specter", "nullcaller", "0x00"):
            if w and w.lower() not in [x.lower() for x in words]:
                words.append(w.lower())
        self.word = ":".join(words) + ":"

        self.stars = []
        for _ in range(170):
            self.stars.append((rng.random(), rng.random(), rng.uniform(0.4, 2.4),
                               rng.uniform(0, math.tau), rng.choice(".....''+++*")))
        self.minis = []
        for i in range(3):
            m = self._new_mini(initial=True, lane=i % 2)
            m["y"] = 0.15 + 0.33 * i + rng.uniform(-0.05, 0.05)
            self.minis.append(m)
        self.particles = []
        self.hem_tips = []
        self.glitch_until = -1.0
        self.next_glitch = rng.uniform(3.0, 6.0)
        self.glitch_count = 0
        self.letters = 0
        self.pulses = 0

    # ---- background ------------------------------------------------------ #

    def _new_mini(self, initial=False, lane=None):
        rng = self.rng
        if lane is None:
            lane = rng.randrange(2)
        x = rng.uniform(0.02, 0.14) if lane == 0 else rng.uniform(0.84, 0.93)
        return {
            "lane": lane,
            "x": x,
            "y": rng.uniform(0.1, 0.9) if initial else rng.uniform(1.05, 1.25),
            "vy": rng.uniform(0.010, 0.022),
            "amp": rng.uniform(0.004, 0.012),
            "ph": rng.uniform(0, math.tau),
            "spr": rng.randrange(len(SHEET_MINIS if self.form == "sheet" else MINI_SPRITES)),
        }

    def draw_stars(self, buf, t, top, h):
        st = self.st.star
        for sx, sy, sp, ph, c in self.stars:
            x = int(sx * buf.w)
            y = top + int(sy * h)
            tw = math.sin(t * sp + ph)
            b = 0.18 + 0.55 * (tw * tw) ** 2
            buf.put(x, y, c if tw > -0.2 else ".", st[q(b)])

    def draw_minis(self, buf, t, dt, top, h):
        st = self.st.mini
        for m in self.minis:
            m["y"] -= m["vy"] * dt
            if m["y"] < -0.15:
                m.update(self._new_mini(lane=m["lane"]))
            spr = self.mini_sprites[m["spr"] % len(self.mini_sprites)]
            x0 = int((m["x"] + m["amp"] * math.sin(t * 0.9 + m["ph"])) * buf.w)
            y0 = top + int(m["y"] * h)
            b = 0.45 + 0.35 * math.sin(t * 1.3 + m["ph"])
            for dy, line in enumerate(spr):
                y = y0 + dy
                if y < top or y >= top + h:
                    continue
                wob = int(round(math.sin(t * 2.0 + m["ph"] + dy) * (dy / 4.0)))
                for dx, c in enumerate(line):
                    if c != " ":
                        buf.put(x0 + dx + wob, y, c, st[q(b * (1.0 - 0.12 * dy))])

    # ---- main ghost ------------------------------------------------------- #

    def draw_ghost(self, buf, t, top, scene_h):
        S = self.st
        W = buf.w
        gh = max(12.0, min(scene_h * 0.94, W * 0.48, 90.0))
        cx = W / 2.0
        bob = math.sin(t * 0.7) * 0.025 * gh
        gtop = top + (scene_h - gh) * 0.5 + bob

        r0 = max(top, int(gtop) - 1)
        r1 = min(top + scene_h, int(gtop + gh) + 2)
        half_cols = int(gh) + 2
        c0 = max(0, int(cx) - half_cols)
        c1 = min(W, int(cx) + half_cols + 1)
        rows, cols = r1 - r0, c1 - c0
        if rows <= 0 or cols <= 0:
            return []

        M = [[OUT] * cols for _ in range(rows)]
        B = [[0.0] * cols for _ in range(rows)]
        V = [0.0] * rows
        inv = 0.5 / gh

        # eyes: flicker + an occasional slow "dim"
        eye_i = 0.82 + 0.18 * math.sin(t * 17.0) * math.sin(t * 5.3)
        ph = t % 6.7
        if ph < 0.35:
            eye_i *= 0.15 + 0.85 * abs(ph - 0.175) / 0.175
        glitching = t < self.glitch_until

        # a bright band that sweeps down the body
        pcyc = t * 0.30
        self.pulses = int(pcyc / 1.5)
        pv = (pcyc % 1.5) - 0.25

        n = self.n_tendrils
        t_len, t_phase = self.t_len, self.t_phase
        hem_span = 1.0 - V_HEM - 0.04
        sin, exp, cos = math.sin, math.exp, math.cos
        arm_rows = (ARM_V0 - 0.05, ARM_V0 + ARM_DROP + 0.12)

        for ry in range(rows):
            v = (r0 + ry + 0.5 - gtop) / gh
            V[ry] = v
            if v < -0.01 or v > 1.0:
                continue
            c = sway(v, t)
            hw = half_width(v, t)
            if hw <= 0.0:
                continue
            in_tendrils = v >= V_HEM
            tz = (v - V_HEM) / (1.0 - V_HEM) if in_tendrils else 0.0
            head = 1.0 - smoothstep(0.05, 0.6, v)
            fade = 1.0 - 0.62 * smoothstep(V_HEM - 0.08, 1.0, v)
            pulse = exp(-((v - pv) / 0.035) ** 2)
            fold_ph = 0.6 * sin(t * 0.8 + v * 3.0)
            in_face_rows = v < FACE_V + FACE_RV + 0.06
            check_arms = arm_rows[0] < v < arm_rows[1]
            Mrow, Brow = M[ry], B[ry]

            for rx in range(cols):
                u = (c0 + rx + 0.5 - cx) * inv
                du = u - c

                if check_arms:  # arms sit in front of the body
                    hit = arm_hit(du, v, t)
                    if hit is not None:
                        ft, tau = hit
                        b = (0.34 + 0.14 * sin(v * 41.0 + t * 2.5 + u * 17.0)
                             + 0.40 * exp(-ft * 4.0) + 0.30 * pulse - 0.12 * tau)
                        Mrow[rx] = ARM
                        Brow[rx] = b
                        continue

                ur = du / hw
                if ur <= -1.0 or ur >= 1.0:
                    continue

                if in_tendrils:
                    p = (ur + 1.0) * 0.5 * n
                    i = int(p)
                    if i >= n:
                        i = n - 1
                    # each tatter wiggles on its own
                    du2 = du + 0.05 * sin(t * 2.4 + t_phase[i] - v * 12.0) * tz
                    ur = du2 / hw
                    if ur <= -1.0 or ur >= 1.0:
                        continue
                    p = (ur + 1.0) * 0.5 * n
                    i = int(p)
                    if i >= n:
                        i = n - 1
                    f = p - i
                    tri = 1.0 - abs(f - 0.5) * 2.0
                    ln = t_len[i] * (0.86 + 0.14 * sin(t * 1.3 + t_phase[i]))
                    if v > V_HEM + 0.02 + hem_span * ln * tri ** 0.75:
                        continue

                lip = 0.0
                if in_face_rows:
                    fx = du / FACE_RU
                    fy = (v - FACE_V) / FACE_RV
                    fe = fx * fx + fy * fy
                    if fe < 1.0:
                        best = 99.0
                        for side in (-1.0, 1.0):
                            ex = du - side * EYE_DX
                            ey = v - (EYE_V - side * EYE_SLANT * ex)
                            e = (ex / EYE_RU) ** 2 + (ey / EYE_RV) ** 2
                            if e < best:
                                best = e
                        if best < 1.0:
                            Mrow[rx] = EYE
                            Brow[rx] = eye_i * (1.0 - 0.35 * best)
                        elif best < 2.6:
                            Mrow[rx] = GLOW
                            Brow[rx] = eye_i * (1.0 - (best - 1.0) / 1.6)
                        else:
                            Mrow[rx] = HOLLOW
                        continue
                    if fe < 2.6:
                        lip = exp(-(fe - 1.0) * 2.2)

                ar = ur if ur > 0 else -ur
                rim = exp(-(1.0 - ar) * 6.0)
                fog = (sin(u * 13.0 + v * 6.0 - t * 0.9) * 0.45
                       + sin(u * 29.0 - v * 15.0 + t * 1.5) * 0.30
                       + sin(v * 37.0 + t * 2.8 + sin(u * 11.0 + t) * 1.5) * 0.25)
                fold = 0.0
                if v > V_HEAD:
                    fold = (0.5 + 0.5 * cos(ur * 9.42 + fold_ph)) * smoothstep(V_HEAD, 0.4, v)
                b = (0.24 + 0.16 * fog + 0.15 * fold + 0.30 * rim
                     + 0.28 * head + 0.35 * pulse + 0.45 * lip)
                Mrow[rx] = BODY
                Brow[rx] = b * fade

        ghost_cells = []
        hem_tips = []

        # ---- trailing strands (drawn first: the body covers their roots) -- #
        for sd in self.strands:
            pts = []
            v0, ln = sd["v0"], sd["len"]
            steps = max(4, int(ln * gh * 2))
            for j in range(steps + 1):
                a = j / steps
                v = v0 + ln * a
                u = (sd["u0"] * (1.0 - 0.35 * a) + sway(v, t)
                     + sd["amp"] * sin(t * 1.9 + sd["ph"] - v * 11.0) * a)
                pts.append((cx + u * 2.0 * gh, gtop + v * gh))
            pb = exp(-((v0 + ln * 0.5 - pv) / 0.08) ** 2) * 0.3
            stroke(buf, pts, S.edge, bmax=0.75 + pb, bmin=0.10, tip="'", cells=ghost_cells)
            hem_tips.append((int(pts[-1][0]), int(pts[-1][1])))

        # ---- glyph pass --------------------------------------------------- #
        word = self.word
        wl = len(word)
        k_word = int(t * 3.0)
        letters = 0
        put = buf.put
        solid = (BODY, ARM)

        def inside(yy, xx):
            if 0 <= yy < rows and 0 <= xx < cols:
                return M[yy][xx] in solid
            return False

        for ry in range(rows):
            row = r0 + ry
            Mrow, Brow = M[ry], B[ry]
            for rx in range(cols):
                m = Mrow[rx]
                if m == OUT:
                    continue
                col = c0 + rx
                b = Brow[rx]
                if m == HOLLOW:  # darkness, the odd mote
                    h = (col * 7919 + row * 104729 + int(t * 2.0) * 1299709) & 1023
                    if h < 12:
                        put(col, row, ".", S.glow[q(0.25)])
                    else:
                        put(col, row, " ", "")
                    continue
                if m == EYE:
                    if glitching:
                        put(col, row, "#", S.glitch[q(1.0)])
                    else:
                        put(col, row, "@" if b > 0.75 else "#" if b > 0.45 else "*", S.eyes[q(b)])
                    continue
                if m == GLOW:
                    put(col, row, "*" if b > 0.55 else ":" if b > 0.25 else ".", S.glow[q(b)])
                    continue

                L = inside(ry, rx - 1)
                R = inside(ry, rx + 1)
                U = inside(ry - 1, rx)
                D = inside(ry + 1, rx)
                ch = None
                if not L and not R:
                    if inside(ry + 1, rx - 1) and not inside(ry + 1, rx + 1):
                        ch = "/"
                    elif inside(ry + 1, rx + 1) and not inside(ry + 1, rx - 1):
                        ch = "\\"
                    else:
                        ch = "|"
                elif not L:
                    ch = "/" if inside(ry + 1, rx - 1) else "\\" if not D else "|"
                elif not R:
                    ch = "\\" if inside(ry + 1, rx + 1) else "/" if not D else "|"
                elif not U:
                    if inside(ry - 1, rx - 1) and not inside(ry - 1, rx + 1):
                        ch = "\\"
                    elif inside(ry - 1, rx + 1) and not inside(ry - 1, rx - 1):
                        ch = "/"
                    else:
                        ch = "-" if (ry > 0 and M[ry - 1][rx] == OUT) else "_"
                elif not D:
                    below = M[ry + 1][rx] if ry + 1 < rows else OUT
                    if below in (HOLLOW, EYE, GLOW):
                        ch = "_"
                    elif inside(ry + 1, rx + 1) and not inside(ry + 1, rx - 1):
                        ch = "\\"
                    elif inside(ry + 1, rx - 1) and not inside(ry + 1, rx + 1):
                        ch = "/"
                    else:
                        ch = "'" if V[ry] > V_HEM - 0.05 or m == ARM else "_"

                if not D and (V[ry] > V_HEM or m == ARM):
                    hem_tips.append((col, row))

                if ch is not None:
                    put(col, row, ch, S.edge[q(clamp(0.35 + b * 0.8))])
                else:
                    if b < 0.14:
                        pool = T0
                    elif b < 0.26:
                        pool = T1
                    elif b < 0.40:
                        pool = T2
                    elif b < 0.55:
                        # the handle, woven into the cloth in drifting patches
                        pool = None if sin(col * 0.21 + row * 0.47 - t * 0.6) > 0.15 else T2
                    elif b < 0.68:
                        pool = T4
                    elif b < 0.82:
                        pool = T5
                    else:
                        pool = T6
                    if pool is None:
                        ch = word[(col + row * 5 - k_word) % wl]
                    else:
                        h = ((col * 92837111) ^ (row * 689287499)
                             ^ (int(t * 4.0 + ((col * 31 + row * 17) % 97) / 24.0) * 283923481))
                        ch = pool[(h >> 7) % len(pool)]
                    put(col, row, ch, S.body[q(b)])
                letters += 1
                ghost_cells.append((col, row))

        letters += self.draw_claws(buf, t, gh, cx, gtop, ghost_cells)
        self.letters = letters + sum(1 for _ in self.strands)
        self.hem_tips = hem_tips
        return ghost_cells

    def draw_claws(self, buf, t, gh, cx, gtop, ghost_cells):
        """Bony fingers fanning out of each sleeve, slowly clenching."""
        before = len(ghost_cells)
        for side in (-1.0, 1.0):
            vw = arm_centre(1.0, t, side) + 0.030
            uw = side * (ARM_U1 - 0.004)
            flex = 0.5 + 0.5 * math.sin(t * 0.8 + side * 2.0)
            for k in range(4):
                ang = math.radians(-12.0 + k * 24.0)     # fan: outward .. downward
                curl = math.radians(35.0 + 55.0 * flex)  # how hard the tip hooks
                ln = 0.085 - 0.008 * abs(k - 1.2)
                u, v = uw, vw + k * 0.006
                pts = [(cx + (u + sway(v, t)) * 2.0 * gh, gtop + v * gh)]
                steps = 12
                for j in range(1, steps + 1):
                    a = j / steps
                    th = ang + curl * a ** 2.2
                    u += side * math.cos(th) * ln / steps
                    v += math.sin(th) * ln / steps
                    wob = 0.002 * math.sin(t * 3.1 + k * 1.7 + j * 0.5)
                    pts.append((cx + (u + sway(v, t) + wob) * 2.0 * gh, gtop + v * gh))
                stroke(buf, pts, self.st.edge, bmax=1.0, bmin=0.55,
                       tip="," if side > 0 else ".", cells=ghost_cells)
        return len(ghost_cells) - before

    # ---- sheet ghost ------------------------------------------------------- #

    def sheet_bottom(self, urh, t, col):
        """Lower edge of the sheet for a column: deeper in the middle, torn into
        tatters, plus a per-column stair-step so it reads as pixel-ragged."""
        n = self.n_tendrils
        urh = clamp(urh, -1.0, 1.0)
        ar = urh if urh > 0 else -urh
        base = 0.74 + 0.19 * (1.0 - ar ** 1.7)
        p = (urh + 1.0) * 0.5 * n
        i = min(n - 1, int(p))
        f = p - i
        tri = 1.0 - abs(f - 0.5) * 2.0
        tat = (0.02 + 0.10 * self.t_len[i] * (0.8 + 0.2 * math.sin(t * 1.5 + self.t_phase[i]))) * tri ** 0.8
        jag = (cell_hash(col, 7, int(t * 1.5)) & 7) * 0.0045
        wave = 0.012 * math.sin(t * 2.0 + urh * 5.0)
        return base + tat - 0.02 + jag + wave

    def draw_sheet(self, buf, t, top, scene_h):
        S = self.st
        W = buf.w
        gh = max(12.0, min(scene_h * 0.92, W * 0.50, 90.0))
        cx = W / 2.0
        bob = math.sin(t * 0.8) * 0.03 * gh
        gtop = top + (scene_h - gh) * 0.45 + bob
        r0 = max(top, int(gtop) - 1)
        r1 = min(top + scene_h, int(gtop + gh * 1.06) + 1)
        half_cols = int(gh) + 3
        c0 = max(0, int(cx) - half_cols)
        c1 = min(W, int(cx) + half_cols + 1)
        inv = 0.5 / gh
        sin, exp = math.sin, math.exp

        ramp = self.ramp
        nr = len(ramp) - 1
        body = S.body
        glitching = t < self.glitch_until

        # hollow eyes that slowly breathe and drift
        erv = SHEET_EYE_RV * (1.0 + 0.06 * sin(t * 1.1))
        eru = SHEET_EYE_RU * (1.0 - 0.03 * sin(t * 1.1))
        look = 0.010 * sin(t * 0.37) + 0.004 * sin(t * 1.9)

        pcyc = t * 0.30
        self.pulses = int(pcyc / 1.5)
        pv = (pcyc % 1.5) - 0.25

        word = self.word
        wl = len(word)
        k_word = int(t * 6.0)
        tslow = int(t * 3.0)
        tnoise = int(t * 9.0)

        cells, tips = [], []
        dots = 0
        put = buf.put
        step_v = 1.0 / gh

        for row in range(r0, r1):
            v = (row + 0.5 - gtop) / gh
            if v < -0.05 or v > 1.1:
                continue
            c = sheet_sway(v, t)
            hw = sheet_half_width(v, t)
            pulse = exp(-((v - pv) / 0.028) ** 2)
            fold_amt = smoothstep(0.42, 0.9, v)
            fold_ph = 0.6 * sin(t * 0.9 + v * 4.0)
            head = 1.0 - smoothstep(0.0, 0.5, v)
            low = smoothstep(0.78, 1.02, v)
            near_eyes = abs(v - SHEET_EYE_V) < erv * 1.5
            b_row = BAYER4[row & 3]

            for col in range(c0, c1):
                u = (col + 0.5 - cx) * inv
                du = u - c
                adu = du if du > 0 else -du

                inside = hw > 0.0 and adu < hw
                bottom = 9.0
                if inside and v > 0.55:
                    bottom = self.sheet_bottom(du / SHEET_HW_REF, t, col)
                    inside = v < bottom

                if not inside:
                    # data-noise crackling off the silhouette (mostly the right)
                    if hw > 0.0 and adu >= hw and v < 0.86:
                        od = adu - hw
                        if od < 0.11:
                            bias = 0.75 if du > 0 else 0.35
                            prob = (1.0 - od / 0.11) ** 1.5 * bias
                            run = cell_hash(row // 2, (col + (tnoise if du > 0 else -tnoise)) // 5, tnoise)
                            if (run & 1023) < prob * 520 and (cell_hash(col, row, tnoise) & 3):
                                hb = cell_hash(col, row, tnoise)
                                put(col, row, NOISE_CHARS[hb % len(NOISE_CHARS)],
                                    body[q(0.22 + 0.30 * ((hb >> 4) & 15) / 15.0)])
                    continue

                # hem tips: where the cloth ends in this column -> drips
                if v > 0.70 and v + step_v >= bottom:
                    tips.append((col, row))

                nz = (cell_hash(col, row, tslow) & 255) / 127.5 - 1.0

                # eyes
                best = 99.0
                if near_eyes:
                    ey = (v - SHEET_EYE_V) / erv
                    for side in (-1.0, 1.0):
                        ex = (du - side * SHEET_EYE_DX - look) / eru + side * 0.22 * ey
                        e = ex * ex + ey * ey
                        if e < best:
                            best = e
                    if best < 1.0:
                        if glitching and (cell_hash(col, row, tnoise) & 3) == 0:
                            put(col, row, ramp[-1], S.glitch[q(0.9)])
                        else:
                            put(col, row, " ", "")
                        cells.append((col, row))
                        continue

                urh = du / SHEET_HW_REF
                b = (0.97
                     + 0.03 * sin(u * 55.0)                      # fine vertical streaks
                     + 0.03 * sin(u * 13.0 + v * 7.0 - t * 0.8)
                     - 0.12 * fold_amt * (0.5 + 0.5 * math.cos(urh * 9.4 + fold_ph))
                     + 0.05 * head
                     - 0.05 * (du / hw)                           # light from the left
                     - 0.10 * low)

                # dots shrink towards the silhouette, with jitter
                e = hw - adu
                if bottom < 9.0:
                    be = (bottom - v) * 1.6
                    if be < e:
                        e = be
                if v < SHEET_HEAD_V:
                    te = (v - SHEET_TOP) * 0.6
                    if te < e:
                        e = te
                b *= smoothstep(-0.010, 0.040, e + 0.014 * nz)
                if best < 1.9:
                    b *= 0.15 + 0.85 * smoothstep(1.0, 1.9, best + 0.18 * nz)
                b += 0.35 * pulse
                if b > 1.0:
                    b = 1.0

                # ordered dither between neighbouring dot sizes -> halftone
                x = b * nr
                lvl = int(x)
                if b_row[col & 3] < (x - lvl) * 16.0:
                    lvl += 1
                if lvl > nr:
                    lvl = nr
                cells.append((col, row))
                if lvl <= 0:
                    put(col, row, " ", "")
                    continue
                dots += 1
                if pulse > 0.75 and lvl >= nr - 1:
                    # the scan line exposes what the ghost is made of
                    put(col, row, word[(col + row * 3 - k_word) % wl], S.edge[q(0.7 + 0.3 * pulse)])
                else:
                    put(col, row, ramp[lvl], body[q(b)])

        self.letters = dots
        self.hem_tips = tips
        return cells

    # ---- ectoplasm drips --------------------------------------------------- #

    def update_particles(self, buf, t, dt, top, h):
        rng = self.rng
        tips = getattr(self, "hem_tips", [])
        if self.form == "sheet":
            return self.update_drips(buf, t, dt, top, h, tips)
        if tips:
            spawn = 2.5 * dt
            while spawn > 0:
                if rng.random() < spawn:
                    x, y = rng.choice(tips)
                    self.particles.append({
                        "x": x + rng.uniform(-0.5, 0.5), "y": y + 1.0,
                        "vx": rng.uniform(-1.2, 1.2), "vy": rng.uniform(1.5, 4.5),
                        "age": 0.0, "life": rng.uniform(1.2, 3.2),
                        "ph": rng.uniform(0, math.tau),
                    })
                spawn -= 1.0
        alive = []
        S = self.st.wisp
        for p in self.particles:
            p["age"] += dt
            if p["age"] >= p["life"]:
                continue
            p["vy"] *= (1.0 - 0.6 * dt)
            p["x"] += (p["vx"] + 1.5 * math.sin(t * 2.0 + p["ph"])) * dt
            p["y"] += p["vy"] * dt
            x, y = int(p["x"]), int(p["y"])
            if not (top <= y < top + h and 0 <= x < buf.w):
                continue
            alive.append(p)
            if buf.ch[y][x] != " " and buf.st[y][x] not in S:
                continue
            a = 1.0 - p["age"] / p["life"]
            c = "*" if a > 0.75 else "+" if a > 0.5 else "." if a > 0.25 else "'"
            buf.put(x, y, c, S[q(a * 0.9)])
        self.particles = alive

    def update_drips(self, buf, t, dt, top, h, tips):
        """Slow vertical drips peeling off the hem, like the sheet is leaking."""
        rng = self.rng
        if tips and rng.random() < 1.6 * dt:
            x, y = rng.choice(tips)
            self.particles.append({"x": x, "y": y + 1.0, "vy": rng.uniform(0.6, 1.6),
                                   "age": 0.0, "life": rng.uniform(1.8, 4.0),
                                   "len": rng.randint(2, 4)})
        head_c, tail_c = self.drip_chars
        S = self.st.wisp
        alive = []
        for p in self.particles:
            p["age"] += dt
            if p["age"] >= p["life"]:
                continue
            p["vy"] += 2.5 * dt
            p["y"] += p["vy"] * dt
            x, y = int(p["x"]), int(p["y"])
            if not (top <= y < top + h + 4 and 0 <= x < buf.w):
                continue
            alive.append(p)
            a = 1.0 - p["age"] / p["life"]
            for k in range(p["len"]):
                yy = y - k * 2  # dotted: every other row, like the reference drips
                if top <= yy < top + h and buf.ch[yy][x] == " ":
                    buf.put(x, yy, head_c if k == 0 else tail_c, S[q(a * (0.9 - 0.25 * k))])
        self.particles = alive

    # ---- glitch ----------------------------------------------------------- #

    def maybe_glitch(self, buf, t, top, h, ghost_cells):
        if not self.glitch_enabled:
            return False
        rng = self.rng
        if t >= self.next_glitch:
            self.glitch_until = t + rng.uniform(0.12, 0.38)
            self.next_glitch = t + rng.uniform(4.0, 9.0)
            self.glitch_count += 1
        if t >= self.glitch_until:
            return False
        G = self.st.glitch
        for x, y in ghost_cells:
            if rng.random() < 0.05:
                buf.put(x, y, rng.choice(GLITCH_CHARS), G[q(rng.uniform(0.4, 1.0))])
        for _ in range(rng.randint(2, 5)):
            y0 = rng.randrange(top, top + h)
            off = rng.choice((-1, 1)) * rng.randint(1, 7)
            for y in range(y0, min(top + h, y0 + rng.randint(1, 3))):
                buf.ch[y] = buf.ch[y][-off:] + buf.ch[y][:-off]
                buf.st[y] = buf.st[y][-off:] + buf.st[y][:-off]
        return True

    # ---- frame ------------------------------------------------------------ #

    def render(self, t, dt, W, H, fps):
        S = self.st
        buf = Buffer(W, H, S.bg)
        uni = UNICODE
        dot = "●" if uni else "*"
        mid = "·" if uni else "-"

        if W < 40 or H < 18:
            msg = "terminal too small (%dx%d, need 40x18)" % (W, H)
            buf.text(max(0, (W - len(msg)) // 2), H // 2, msg[:W], S.hud)
            return buf

        top, scene_h = 1, H - 6
        self.draw_stars(buf, t, top, scene_h)
        self.draw_minis(buf, t, dt, top, scene_h)
        if self.form == "sheet":
            cells = self.draw_sheet(buf, t, top, scene_h)
        else:
            cells = self.draw_ghost(buf, t, top, scene_h)
        self.update_particles(buf, t, dt, top, scene_h)
        glitching = self.maybe_glitch(buf, t, top, scene_h, cells)

        # top-right clock
        clock = "%s t %05.2fs" % (dot, t % 100.0)
        buf.text(W - len(clock) - 2, 0, clock, S.accent if not glitching else S.glitch_hi)

        # stats block
        y = H - 5
        buf.text(2, y, "@" + self.name, S.hud)
        if self.form == "sheet":
            stats = [("souls", "%d" % len(self.minis)), ("tatters", "%d" % self.n_tendrils),
                     ("pulses", "%d" % self.pulses), ("glitches", "%d" % self.glitch_count)]
            count_label, part_label = "dots", "drips"
        else:
            stats = [("souls", "%d" % len(self.minis)), ("strands", "%d" % len(self.strands)),
                     ("pulses", "%d" % self.pulses), ("glitches", "%d" % self.glitch_count)]
            count_label, part_label = "letters", "wisps"
        x = 2
        for k, v in stats:
            buf.text(x, y + 2, k, S.hud_dim)
            buf.text(x + len(k) + 2, y + 2, v, S.hud)
            x += max(16, len(k) + len(v) + 6)
        buf.text(2, y + 3, count_label, S.hud_dim)
        buf.text(4 + len(count_label), y + 3, "{:,}".format(self.letters), S.hud)
        buf.text(x, y + 3, part_label, S.hud_dim)
        buf.text(x + len(part_label) + 2, y + 3, "%d" % len(self.particles), S.hud)

        # status bar
        by = H - 1
        buf.row_bg[by] = S.bar
        buf.text(2, by, "%s.py" % self.name, S.hud)
        if glitching:
            right = "%s no carrier %s %d fps" % (dot, mid, round(fps))
            style = S.glitch_hi
        else:
            right = "%s haunting %s %d fps" % (dot, mid, round(fps))
            style = S.accent
        buf.text(W - len(right) - 3, by, right, style)
        return buf


# --------------------------------------------------------------------------- #
# terminal plumbing
# --------------------------------------------------------------------------- #

UNICODE = True


def setup_stdout():
    global UNICODE
    if os.name == "nt":
        os.system("")  # enables ANSI/VT processing in classic Windows consoles
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    UNICODE = enc.startswith("utf")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="An animated ASCII ghost for your terminal.")
    ap.add_argument("--form", "-f", default="sheet", choices=("sheet", "wraith"),
                    help="sheet: halftone sheet ghost (default); wraith: hooded wraith with claws")
    ap.add_argument("--palette", "-p", default=None, choices=sorted(PALETTES),
                    help="default: halftone for sheet, spectral for wraith")
    ap.add_argument("--glyphs", "-g", default="dots", choices=sorted(GLYPHS),
                    help="dot shapes for the sheet's halftone (dots needs a UTF-8 terminal)")
    ap.add_argument("--name", "-n", default="specter", help="handle shown in the HUD and woven into the body")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--tendrils", type=int, default=None, help="tatters in the hem (sheet 11, wraith 7)")
    ap.add_argument("--strands", type=int, default=8, help="trailing wisps below the body")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-glitch", action="store_true", help="disable the nullcaller glitch bursts")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--transparent", action="store_true", help="keep the terminal's own background")
    ap.add_argument("--list-palettes", action="store_true")
    ap.add_argument("--snapshot", type=float, metavar="T", help="print a single frame at time T and exit")
    return ap.parse_args(argv)


def finalize_args(args):
    if args.palette is None:
        args.palette = "halftone" if args.form == "sheet" else "spectral"
    if args.tendrils is None:
        args.tendrils = 11 if args.form == "sheet" else 7
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.list_palettes:
        print("\n".join(sorted(PALETTES)))
        return
    setup_stdout()
    color = not args.no_color and os.environ.get("NO_COLOR") is None
    finalize_args(args)
    styles = Styles(PALETTES[args.palette], color=color, solid_bg=not args.transparent)
    ghost = Specter(args, styles)

    if args.snapshot is not None:
        W, H = shutil.get_terminal_size((110, 48))
        # warm up particles so the snapshot isn't empty
        step = 1.0 / 30.0
        t = max(0.0, args.snapshot - 3.0)
        while t < args.snapshot:
            ghost.render(t, step, W, H, 30.0)
            t += step
        sys.stdout.write(ghost.render(args.snapshot, step, W, H, 30.0).serialize(plain_lines=True) + "\n")
        return

    out = sys.stdout
    out.write("\x1b[?1049h\x1b[?25l\x1b[2J")
    out.flush()
    frame = 1.0 / max(1.0, args.fps)
    t0 = last = time.perf_counter()
    fps = args.fps
    try:
        while True:
            now = time.perf_counter()
            dt = min(0.1, now - last)
            last = now
            if dt > 0:
                fps = fps * 0.9 + (1.0 / dt) * 0.1
            W, H = shutil.get_terminal_size((100, 40))
            out.write(ghost.render(now - t0, dt, W, H, fps).serialize())
            out.flush()
            spare = frame - (time.perf_counter() - now)
            if spare > 0:
                time.sleep(spare)
    except KeyboardInterrupt:
        pass
    finally:
        out.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        out.flush()


if __name__ == "__main__":
    main()
