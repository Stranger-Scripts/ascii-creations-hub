#!/usr/bin/env python3
"""
dragonfly.py - a dragonfly skims a pond and lands on a branch sticking out of the water.

A short, looping ASCII film for your terminal. No dependencies, Python 3.8+.
Looks best in a truecolor terminal (Windows Terminal, kitty, WezTerm, Alacritty,
GNOME Terminal, iTerm2, ...).

    python dragonfly.py                    # dusk, loops forever
    python dragonfly.py --palette night    # moonlit pond
    python dragonfly.py --speed 0.4        # slow motion, good for studying the motion
    python dragonfly.py --debug            # draw the flight path, waypoints and a HUD
    python dragonfly.py --once             # play once and stay perched
    python dragonfly.py --snapshot 12      # print the frame at t=12s and exit
    python dragonfly.py --help

Ctrl+C to quit.

How it works, in one paragraph (docs/dragonfly-math.md has the long version):
the flight path is a Catmull-Rom spline through waypoints, and time is mapped
onto it with smoothstep between keyframes, which is what makes the dragonfly
dart and stop. The wings are ellipses rotating about their roots with
sin(phase), where the phase is the integral of a beat frequency that drops to
zero on landing. The water is a sum of travelling sine waves evaluated on the
pond's ground plane, projected through a pinhole camera, so the waves and the
ripple rings flatten towards the horizon. Reflections are the scene mirrored
about the waterline and shifted sideways by the local wave slope. The branch
is a rotated polyline that rings like a damped spring when the dragonfly lands.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import shutil
import sys
import time

TAU = 2.0 * math.pi
ASPECT = 2.0  # a terminal cell is ~2x as tall as it is wide: 1 row == 2 "visual" units

# --------------------------------------------------------------------------- #
# palettes
# --------------------------------------------------------------------------- #

PALETTES = {
    # warm sunset, the default
    "dusk": {
        "sky": [(14, 14, 40), (52, 34, 84), (138, 62, 98), (232, 120, 74)],
        "sun": (255, 206, 128), "sun_core": (255, 244, 214), "star": (200, 190, 225),
        "trees": (26, 16, 34), "water_deep": (8, 12, 30), "water_hi": (150, 120, 170),
        "glint": (255, 214, 150), "branch": (78, 54, 44), "branch_lit": (168, 112, 78),
        "body": (40, 196, 220), "band": (16, 70, 104), "thorax": (60, 150, 110),
        "eyes": (130, 255, 160), "wing": (210, 228, 255), "reed": (36, 58, 40),
        "reed_head": (110, 66, 40), "hud": (170, 150, 180),
    },
    # bright midday
    "day": {
        "sky": [(46, 104, 190), (86, 150, 222), (150, 196, 238), (214, 232, 246)],
        "sun": (255, 246, 200), "sun_core": (255, 255, 255), "star": (0, 0, 0),
        "trees": (28, 70, 44), "water_deep": (12, 44, 70), "water_hi": (160, 205, 235),
        "glint": (255, 255, 235), "branch": (84, 62, 46), "branch_lit": (176, 136, 98),
        "body": (30, 150, 210), "band": (10, 50, 90), "thorax": (50, 120, 90),
        "eyes": (90, 230, 130), "wing": (240, 248, 255), "reed": (52, 96, 48),
        "reed_head": (120, 76, 44), "hud": (230, 240, 250),
    },
    # moonlit, cold
    "night": {
        "sky": [(2, 3, 12), (8, 12, 32), (18, 28, 58), (40, 56, 92)],
        "sun": (200, 210, 235), "sun_core": (240, 244, 255), "star": (190, 200, 235),
        "trees": (6, 8, 16), "water_deep": (2, 4, 12), "water_hi": (90, 110, 160),
        "glint": (210, 222, 255), "branch": (44, 40, 46), "branch_lit": (110, 108, 130),
        "body": (60, 170, 210), "band": (16, 50, 80), "thorax": (40, 100, 100),
        "eyes": (140, 255, 190), "wing": (180, 200, 240), "reed": (18, 28, 28),
        "reed_head": (50, 40, 40), "hud": (120, 130, 170),
    },
}

# --------------------------------------------------------------------------- #
# small maths helpers
# --------------------------------------------------------------------------- #


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(a, b, x):
    """0 below a, 1 above b, and an S-curve 3x^2 - 2x^3 in between (zero slope at both ends)."""
    if x <= a:
        return 0.0
    if x >= b:
        return 1.0
    x = (x - a) / (b - a)
    return x * x * (3.0 - 2.0 * x)


def bump(t, centre, width):
    """A smooth 0 -> 1 -> 0 pulse centred on `centre`."""
    return math.exp(-((t - centre) / width) ** 2)


def mix(a, b, t):
    t = clamp(t)
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def scale(rgb, k):
    return (rgb[0] * k, rgb[1] * k, rgb[2] * k)


def gradient(stops, t):
    t = clamp(t) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return mix(stops[i], stops[i + 1], t - i)


def hash01(*ints):
    """Deterministic pseudo-random number in [0, 1) from a few integers."""
    h = 0x9E3779B1
    for v in ints:
        h = ((h ^ (v & 0xFFFFFFFF)) * 0x85EBCA6B) & 0xFFFFFFFF
        h ^= h >> 13
        h = (h * 0xC2B2AE35) & 0xFFFFFFFF
        h ^= h >> 16
    return h / 4294967296.0


def rotate_vis(dx, dy, a):
    """Rotate a cell-space offset by angle a (radians, counter-clockwise on screen).

    Rows point down and are twice as tall as columns, so convert to visual units
    (x right, y up, equal scale), rotate, and convert back."""
    X, Y = dx, -dy * ASPECT
    c, s = math.cos(a), math.sin(a)
    X, Y = X * c - Y * s, X * s + Y * c
    return X, -Y / ASPECT


def slope_glyph(dx, dy):
    """Glyph for a line going (dx columns, dy rows). dy is measured in rows (down = +)."""
    vx, vy = dx, dy * ASPECT  # compare angles in visual space
    if vy < 0:
        vx, vy = -vx, -vy
    if vy < 0.42 * abs(vx):
        return "-"
    r = vx / vy
    if r > 0.42:
        return "\\"
    if r < -0.42:
        return "/"
    return "|"


MIRROR_V = {"/": "\\", "\\": "/", "^": "v", "v": "^", "_": "‾", "‾": "_",
            "▀": "▄", "▄": "▀", "▲": "▼", "▼": "▲", "◢": "◥", "◣": "◤", ",": "'", "'": ",", ".": "'", "`": ","}

# --------------------------------------------------------------------------- #
# glyphs (Unicode with an ASCII fallback)
# --------------------------------------------------------------------------- #

UNICODE = True
GLYPHS_U = {
    "head": "●", "thorax": "◆", "abdomen": "=", "tip": "-",
    "tree": "█", "tree_top": "▲", "tree_cap": "▄", "tree_up": "◢", "tree_down": "◣", "tree_refl": "█",
    "sun": "█", "halo1": "▓", "halo2": "▒", "halo3": "░",
    "star": "·", "glint_hi": "*", "glint_mid": "+", "glint_lo": "·",
    "water": ["·", "-", "~", "≈"], "reed_head": "█", "path": "·",
}
GLYPHS_A = {
    "head": "O", "thorax": "#", "abdomen": "=", "tip": "-",
    "tree": "#", "tree_top": "^", "tree_cap": "_", "tree_up": "/", "tree_down": "\\", "tree_refl": ":",
    "sun": "@", "halo1": "O", "halo2": "o", "halo3": ".",
    "star": ".", "glint_hi": "*", "glint_mid": "+", "glint_lo": ".",
    "water": [".", "-", "~", "="], "reed_head": "#", "path": ".",
}
G = GLYPHS_U

# --------------------------------------------------------------------------- #
# frame buffer
# --------------------------------------------------------------------------- #


class Buffer:
    """A grid of characters, each with an RGB foreground; one background colour per row."""

    __slots__ = ("w", "h", "ch", "fg", "bg", "row_bg")

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.ch = [[" "] * w for _ in range(h)]
        self.fg = [[None] * w for _ in range(h)]
        self.bg = [[None] * w for _ in range(h)]   # None = use the row's background
        self.row_bg = [(0, 0, 0)] * h

    def put(self, x, y, c, rgb, bg=None):
        x, y = int(math.floor(x)), int(math.floor(y))
        if 0 <= x < self.w and 0 <= y < self.h:
            self.ch[y][x] = c
            self.fg[y][x] = rgb
            if bg is not None:
                self.bg[y][x] = bg

    def bg_at(self, x, y):
        b = self.bg[y][x]
        return self.row_bg[y] if b is None else b

    def get(self, x, y):
        x, y = int(math.floor(x)), int(math.floor(y))
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.ch[y][x], self.fg[y][x]
        return " ", None

    def text(self, x, y, s, rgb):
        for i, c in enumerate(s):
            self.put(x + i, y, c, rgb)

    def serialize(self, color=True, solid_bg=True, plain_lines=False):
        cache = {}

        def esc(rgb, base):
            k = (base, int(rgb[0]) >> 2, int(rgb[1]) >> 2, int(rgb[2]) >> 2)
            s = cache.get(k)
            if s is None:
                s = "\x1b[%d;2;%d;%d;%dm" % (base, k[1] << 2, k[2] << 2, k[3] << 2)
                cache[k] = s
            return s

        out = []
        last = self.h - 1
        for y in range(self.h):
            if plain_lines:
                out.append("\n" if y else "")
            else:
                out.append("\x1b[%d;1H" % (y + 1))
            row_bg = esc(self.row_bg[y], 48) if solid_bg else "\x1b[49m"
            if color:
                out.append(row_bg)
            cur = None
            cur_bg = row_bg
            chars, fgs, bgs = self.ch[y], self.fg[y], self.bg[y]
            n = self.w - 1 if (y == last and not plain_lines) else self.w  # don't scroll
            parts = []
            for x in range(n):
                c = chars[x]
                if color:
                    b = bgs[x]
                    sb = row_bg if (b is None or not solid_bg) else esc(b, 48)
                    if sb is not cur_bg:
                        parts.append(sb)
                        cur_bg = sb
                    if c != " ":
                        s = esc(fgs[x] or (255, 255, 255), 38)
                        if s is not cur:
                            parts.append(s)
                            cur = s
                parts.append(c)
            out.append("".join(parts))
        if color:
            out.append("\x1b[0m")
        return "".join(out)


class Layer:
    """Records cells instead of drawing them, so they can be drawn twice: mirrored, then upright."""

    def __init__(self):
        self.cells = {}

    def put(self, x, y, c, rgb):
        self.cells[(int(math.floor(x)), int(math.floor(y)))] = (c, rgb)

    def flush(self, buf):
        for (x, y), (c, rgb) in self.cells.items():
            buf.put(x, y, c, rgb)


# --------------------------------------------------------------------------- #
# the film's timeline
# --------------------------------------------------------------------------- #
# Waypoints are numbered 0..8 (see Scene.waypoints). Each key says "at time t the
# dragonfly is at path parameter u". Between keys the parameter moves with a
# smoothstep, so the dragonfly accelerates out of every key and brakes into the
# next one: that stop-and-go is what reads as darting. Two keys with the same u
# in a row are a hover.

KEYS = [
    (0.0, 0), (1.6, 1),          # enter from the left
    (2.7, 2), (3.5, 2),          # dash, hover
    (4.5, 3), (4.95, 3),         # drop and dip the abdomen into the water
    (6.0, 4),                    # climb
    (7.5, 5), (8.6, 5),          # dash past the branch, hover and turn round
    (9.8, 6), (10.5, 6),         # dash back, hover above the twig
    (11.4, 7),                   # touch down
    (17.0, 7),                   # perched
    (19.4, 8),                   # take off and leave to the right
    (21.5, 8),                   # empty pond for a moment, then loop
]
PERIOD = KEYS[-1][0]
PERCH = 7                        # index of the waypoint on the branch tip
T_DAP = 4.72                     # abdomen touches the water
T_LAND = 11.4
T_TAKEOFF = 17.0
TWITCHES = (13.4, 15.5)          # perched wing twitches

PHASES = [
    (0.0, "enter"), (1.6, "dash"), (2.7, "hover"), (3.5, "drop"), (4.5, "dap"),
    (4.95, "climb"), (6.0, "dash"), (7.5, "hover + turn"), (8.6, "dash back"),
    (9.8, "hover"), (10.5, "land"), (11.4, "perched"), (17.0, "take-off"),
    (19.4, "empty pond"),
]


def u_at(t):
    """Path parameter at time t (piecewise smoothstep through KEYS)."""
    if t <= KEYS[0][0]:
        return float(KEYS[0][1])
    for (t0, u0), (t1, u1) in zip(KEYS, KEYS[1:]):
        if t < t1:
            return u0 + (u1 - u0) * smoothstep(t0, t1, t)
    return float(KEYS[-1][1])


def phase_name(t):
    name = PHASES[0][1]
    for t0, n in PHASES:
        if t >= t0:
            name = n
    return name


def catmull_rom(p0, p1, p2, p3, s):
    """Uniform Catmull-Rom: passes through p1 (s=0) and p2 (s=1); tangents from the neighbours."""
    s2, s3 = s * s, s * s * s
    return tuple(
        0.5 * (2 * b + (-a + c) * s + (2 * a - 5 * b + 4 * c - d) * s2 + (-a + 3 * b - 3 * c + d) * s3)
        for a, b, c, d in zip(p0, p1, p2, p3)
    )


def flight_factor(t):
    """1 while flying, 0 while perched, with soft ramps at landing and take-off."""
    return 1.0 - smoothstep(T_LAND - 0.55, T_LAND + 0.05, t) + smoothstep(T_TAKEOFF - 0.15, T_TAKEOFF + 0.2, t)


# --------------------------------------------------------------------------- #
# the scene
# --------------------------------------------------------------------------- #

class Scene:
    def __init__(self, args, pal):
        self.args = args
        self.pal = pal
        self.rng = random.Random(args.seed)
        r = self.rng
        # water: 4 travelling waves on the ground plane, (amplitude, wavelength, direction, phase)
        self.waves = []
        for amp, lam, ang in ((1.0, 11.3, 0.3), (0.75, 7.1, -0.6), (0.55, 4.7, 1.0),
                              (0.4, 3.3, -1.2), (0.3, 2.3, 0.5), (0.22, 1.7, -0.2)):
            ang += r.uniform(-0.2, 0.2)
            k = TAU / lam
            omega = math.sqrt(9.81 * k * 0.35)  # deep-water dispersion (g scaled to taste)
            self.waves.append((amp, k, math.cos(ang) * k, math.sin(ang) * k, omega, r.uniform(0, TAU), lam))
        self.wave_amp = sum(w[0] for w in self.waves)
        # fish rising: two random ripples per loop
        self.plips = [(r.uniform(1.0, PERIOD - 3.0), r.uniform(0.15, 0.85), r.uniform(0.12, 0.9)) for _ in range(2)]
        self.tree_seed = r.randrange(1 << 30)
        self.reeds_seed = r.randrange(1 << 30)
        self.star_seed = r.randrange(1 << 30)
        # animation state that has to be integrated over time
        self.wing_phase = 0.0
        self.yaw = 0.0            # 0 = facing right, pi = facing left
        self.size = None

    # ----------------------------------------------------------------- layout
    def layout(self, W, H):
        if self.size == (W, H):
            return
        self.size = (W, H)
        self.W, self.H = W, H
        self.yh = int(H * 0.5)                      # horizon: first row of water
        self.ys = H * 0.8                           # waterline of the "stage" (branch + dragonfly)
        self.rs = self.ys - self.yh                 # rows from horizon down to the stage
        self.focal = 0.6 * W                        # pinhole focal length, in columns
        self.body_len = clamp(W * 0.095, 8.0, 15.0)  # dragonfly length in columns

        # pinhole camera: a water cell r rows below the horizon is at depth Z = rs / r
        # (in "stage units": Z = 1 on the stage, 2 = twice as far away ...)
        self.water = []
        for y in range(self.yh, H):
            r = y - self.yh + 0.5
            Z = self.rs / r
            zw = Z * self.focal                     # depth in world units (columns at the stage)
            step_x = Z                              # world units covered by one column at this row
            step_z = zw * zw / (self.focal * self.rs)  # world units covered by one row at this row
            fades = []
            for amp, k, kx, kz, om, ph, lam in self.waves:
                # anti-aliasing: a wave shorter than ~3 samples can't be drawn, so fade it out
                d = abs(kx / k) * step_x + abs(kz / k) * step_z
                fades.append(smoothstep(2.0, 4.0, lam / d))
            xs = [(x + 0.5 - W / 2.0) * Z for x in range(W)]
            self.water.append((y, r, Z, zw, fades, xs, step_x, step_z))

        # distant tree line: a hilly base (1-D fractal value noise) with pine cones on top.
        # Height of the silhouette = max(hill, every cone), a cone being h_i - slope * |x - x_i|.
        def hill(x):
            v, amp, freq, tot = 0.0, 1.0, 1.0 / 26.0, 0.0
            for octave in range(3):
                xf = x * freq
                i = int(math.floor(xf))
                f = xf - i
                f = f * f * (3 - 2 * f)
                v += amp * lerp(hash01(self.tree_seed, octave, i), hash01(self.tree_seed, octave, i + 1), f)
                tot += amp
                amp *= 0.5
                freq *= 2.0
            return v / tot

        trng = random.Random(self.tree_seed)
        cones = []
        x = -2.0
        while x < W + 2:
            x += trng.uniform(1.2, 3.2)
            cones.append((x, 0.8 + hill(x) * H * 0.06 + trng.uniform(0.3, 1.0) * H * 0.045))
        self.tree_h = []
        for x in range(W):
            xc = x + 0.5
            h = 0.5 + hill(xc) * H * 0.05
            for cx, ch in cones:
                h = max(h, ch - 0.9 * abs(xc - cx))     # 0.9 rows per column: a steep pine
            self.tree_h.append(h)

        # the branch (rest pose), in cell coordinates relative to the base
        bx = 0.66 * W
        self.branch_base = (bx, self.ys + 0.2)
        tip = (-0.035 * W, -0.47 * H)
        fork_a = (tip[0] * 0.42, tip[1] * 0.42)
        fork_b = (tip[0] * 0.68, tip[1] * 0.68)
        twig_a = (fork_a[0] + 0.075 * W, fork_a[1] - 0.13 * H)
        twig_a_mid = lerp(fork_a[0], twig_a[0], 0.6), lerp(fork_a[1], twig_a[1], 0.6)
        twig_a2 = (twig_a_mid[0] + 0.02 * W, twig_a_mid[1] - 0.06 * H)
        twig_b = (fork_b[0] - 0.05 * W, fork_b[1] - 0.07 * H)
        # segments: (start, end, half-width at start, half-width at end) in visual units
        self.branch_segs = [
            ((0.0, 1.5), tip, 1.3, 0.35),
            (fork_a, twig_a, 0.55, 0.15),
            (twig_a_mid, twig_a2, 0.25, 0.1),
            (fork_b, twig_b, 0.35, 0.1),
        ]
        self.branch_tip = tip

        # flight waypoints (cells). fy: 0 = waterline, 1 = top of the screen
        def P(fx, fy):
            return (fx * W, self.ys - fy * (self.ys - 2.0))

        self.waypoints = [
            P(-0.14, 0.55), P(0.14, 0.66), P(0.27, 0.48),
            (0.40 * W, self.ys - 2.2),               # 3: the dip
            P(0.52, 0.42), P(0.86, 0.62),
            None, None,                             # 6, 7: follow the (moving) branch tip
            P(1.18, 0.85),
        ]
        self.sun = (0.27 * W, self.yh - 5.2)        # low sun, just above the trees

    # ----------------------------------------------------------------- branch
    def branch_angle(self, t):
        """Sway from the wind + a damped oscillation when the dragonfly lands / takes off."""
        a = 0.012 * math.sin(0.8 * t) + 0.006 * math.sin(1.9 * t + 1.0)
        for t0, amp in ((T_LAND, 0.05), (T_TAKEOFF, -0.03)):
            tau = t - t0
            if tau > 0:
                w0, zeta = TAU * 1.4, 0.12                    # natural frequency, damping ratio
                wd = w0 * math.sqrt(1 - zeta * zeta)          # damped frequency
                a += amp * math.exp(-zeta * w0 * tau) * math.sin(wd * tau)
        return a

    def branch_point(self, p, alpha):
        bx, by = self.branch_base
        dx, dy = rotate_vis(p[0], p[1], alpha)
        return bx + dx, by + dy

    def perch(self, t):
        tip = self.branch_point(self.branch_tip, self.branch_angle(t))
        return tip[0], tip[1] - 0.7

    # ----------------------------------------------------------------- flight
    def points(self, t):
        pts = list(self.waypoints)
        px, py = self.perch(t)
        pts[7] = (px, py)
        pts[6] = (px + 0.06 * self.W, py - 0.12 * self.H)
        return pts

    def base_path(self, t):
        """Position on the spline (no jitter)."""
        pts = self.points(t)
        u = u_at(t)
        i = min(int(u), len(pts) - 2)
        s = u - i
        p0 = pts[max(i - 1, 0)]
        p3 = pts[min(i + 2, len(pts) - 1)]
        # The perch is a full stop: give it a zero tangent (neighbour = itself) so the curve
        # comes straight down onto the twig instead of hooking past it.
        if i + 1 == PERCH:
            p3 = pts[PERCH]
        if i == PERCH:
            p0 = pts[PERCH]
        return catmull_rom(p0, pts[i], pts[i + 1], p3, s)

    def position(self, t):
        """Spline position + a little hover jitter (two incommensurate sines per axis)."""
        x, y = self.base_path(t)
        j = flight_factor(t) * (1.0 - smoothstep(T_LAND - 1.0, T_LAND - 0.3, t) * (t < T_TAKEOFF))
        x += j * (0.6 * math.sin(2.1 * t) + 0.3 * math.sin(5.3 * t + 1.0))
        y += j * (0.35 * math.sin(2.9 * t + 0.5) + 0.2 * math.sin(7.1 * t))
        return x, y

    def velocity(self, t, h=1.0 / 60.0):
        a = self.base_path(t - h)
        b = self.base_path(t + h)
        return (b[0] - a[0]) / (2 * h), (b[1] - a[1]) / (2 * h)

    # ----------------------------------------------------------------- state
    def update(self, t, dt):
        """Integrate the bits of state that can't be computed from t alone."""
        fl = flight_factor(t)
        beat = 5.5 * fl                                       # wing beats per second
        self.wing_phase = (self.wing_phase + TAU * beat * dt) % TAU
        # turn to face where the path goes next (look ahead, with a dead zone)
        ahead = self.base_path(t + 0.45)[0] - self.base_path(t)[0]
        if fl < 0.5:
            ahead = 0.0                      # perched: the branch bobbing must not turn it round
        if ahead > 0.4:
            target = 0.0
        elif ahead < -0.4:
            target = math.pi
        else:
            target = 0.0 if self.yaw < math.pi / 2 else math.pi   # finish any turn in progress
        rate = math.pi / 0.35 * dt                            # half a turn in 0.35 s
        self.yaw += clamp(target - self.yaw, -rate, rate)

    # ----------------------------------------------------------------- render
    def render(self, t_real, W, H, fps=0.0):
        self.layout(W, H)
        t = min(t_real, T_TAKEOFF - 0.5) if self.args.once else t_real % PERIOD
        buf = Buffer(W, H)
        pal = self.pal
        if W < 40 or H < 18:
            buf.text(0, 0, "terminal too small (need 40x18)", pal["hud"])
            return buf
        self.draw_sky(buf, t)
        self.draw_water(buf, t)
        fg = Layer()
        self.draw_branch(fg, t)
        self.draw_dragonfly(fg, t)
        self.draw_reflection(buf, fg, t)
        fg.flush(buf)
        if not self.args.no_reeds:
            self.draw_reeds(buf, t)
        if self.args.debug:
            self.draw_debug(buf, t, fps)
        return buf

    # sky, stars, sun, trees ------------------------------------------------
    def draw_sky(self, buf, t):
        pal, W, yh = self.pal, self.W, self.yh
        for y in range(yh):
            buf.row_bg[y] = gradient(pal["sky"], (y + 0.5) / yh)
        # stars: a fixed hash per cell decides if there is one, a sine makes it twinkle
        if sum(pal["star"]) > 0:
            for y in range(int(yh * 0.55)):
                for x in range(W):
                    if hash01(self.star_seed, x, y) < 0.012:
                        tw = 0.5 + 0.5 * math.sin(t * (1.5 + 3 * hash01(x, y, 7)) + 10 * hash01(y, x))
                        fade = 1.0 - y / (yh * 0.55)
                        buf.put(x, y, G["star"], mix(buf.row_bg[y], pal["star"], 0.25 + 0.75 * tw * fade))
        # sun (or moon): distance from the centre in visual units picks the glyph
        sx, sy = self.sun
        R = 3.2
        for y in range(max(0, int(sy - 7)), min(yh, int(sy + 7))):
            for x in range(int(sx - 14), int(sx + 15)):
                d = math.hypot(x + 0.5 - sx, (y + 0.5 - sy) * ASPECT)
                if d < R:
                    c = mix(pal["sun"], pal["sun_core"], 1 - d / R)
                    buf.put(x, y, G["sun"], c, bg=c)
                elif d < R + 6.0:
                    k = (d - R) / 6.0
                    g = G["halo1"] if k < 0.15 else G["halo2"] if k < 0.4 else G["halo3"]
                    buf.put(x, y, g, mix(pal["sun"], buf.row_bg[y], 0.35 + 0.6 * k))
        # trees: solid cells inside the silhouette; the partly covered top cell gets a glyph
        # that matches the local slope, which is a cheap form of anti-aliasing
        th = self.tree_h
        for x in range(W):
            h = th[x]
            top = yh - h
            ty = int(math.floor(top))
            cover = 1.0 - (top - ty)                       # how much of the top cell is tree
            left, right = th[max(x - 1, 0)], th[min(x + 1, W - 1)]
            for y in range(max(0, ty), yh):
                if y == ty and cover < 0.75:
                    if cover < 0.2:
                        continue
                    if h >= left and h >= right:
                        g = G["tree_top"]
                    elif left < h < right:
                        g = G["tree_up"]
                    elif left > h > right:
                        g = G["tree_down"]
                    else:
                        g = G["tree_cap"]
                    buf.put(x, y, g, pal["trees"])
                else:
                    buf.put(x, y, G["tree"], pal["trees"], bg=pal["trees"])

    # water -----------------------------------------------------------------
    def ripples(self, t):
        """(world x, world z, start time, strength) for every ripple source."""
        out = []
        f = self.focal
        tip = self.tip_world_at_dap
        out.append((tip[0], tip[1], T_DAP, 1.0))
        bx, by = self.branch_base
        bz = f * self.rs / (by - self.yh + 0.5)
        bwx = (bx - self.W / 2.0) * bz / f
        out.append((bwx, bz, T_LAND, 0.6))
        out.append((bwx, bz, T_TAKEOFF, 0.4))
        for t0, fx, fy in self.plips:
            y = self.yh + 2 + fy * (self.H - self.yh - 3)
            z = f * self.rs / (y - self.yh + 0.5)
            out.append(((fx - 0.5) * self.W * z / f, z, t0, 0.7))
        return [r for r in out if 0.0 <= t - r[2] < 6.0]

    @property
    def tip_world_at_dap(self):
        """Where the abdomen tip touches the water at the dip, as a point on the ground plane."""
        x, _ = self.waypoints[3]
        x -= self.body_len * 0.85          # facing right at the dip, so the tip trails to the left
        z = self.focal                     # on the stage
        return ((x - self.W / 2.0) * z / self.focal, z)

    def draw_water(self, buf, t):
        pal, W, yh, H = self.pal, self.W, self.yh, self.H
        deep, hi = pal["water_deep"], pal["water_hi"]
        waves, A = self.waves, self.wave_amp
        rip = self.ripples(t)
        sx_sun, sy_sun = self.sun
        wl = G["water"]
        for (y, r, Z, zw, fades, xs, step_x, step_z) in self.water:
            mrow = 2 * yh - 1 - y                     # sky row mirrored about the horizon
            sky_c = buf.row_bg[mrow] if 0 <= mrow < yh else pal["sky"][0]
            fres = 0.25 + 0.7 * math.exp(-(r - 0.5) / (0.18 * (H - yh)))  # grazing angle -> mirror
            base = mix(deep, sky_c, fres * 0.85)
            buf.row_bg[y] = scale(base, 0.8)
            near = clamp(r / (H - yh))
            comps = [(a * fd, kx, kz, om, ph) for (a, k, kx, kz, om, ph, lam), fd in zip(waves, fades) if fd > 0.01]
            for x in range(W):
                X = xs[x]
                h = sx = sz = 0.0
                for a, kx, kz, om, ph in comps:
                    arg = kx * X + kz * zw - om * t + ph
                    c = math.cos(arg)
                    h += a * math.sin(arg)
                    sx += a * kx * c
                    sz += a * kz * c
                ring = 0.0
                ring_glyph = None
                for rx, rz, t0, strength in rip:
                    age = t - t0
                    dx, dz = X - rx, zw - rz
                    dist = math.sqrt(dx * dx + dz * dz) + 1e-6
                    front = 0.6 + 4.0 * age                  # ring radius grows linearly
                    u = dist - front
                    if -6.5 < u < 2.0:
                        # how much ground one cell covers in the radial direction: a ring thinner
                        # than that would fall between samples, so widen it to at least one cell
                        foot = (abs(dx) * step_x + abs(dz) * step_z) / dist
                        width = max(0.7, 0.55 * foot)
                        env = strength * math.exp(-age / 1.4)       # rings fade as they spread
                        for crest, k in ((0.0, 1.0), (-3.2, 0.55)):     # leading ring + one behind it
                            if abs(u - crest) < width:
                                val = env * k
                                h += 1.5 * val
                                if val > ring:
                                    ring = val
                                    ring_glyph = self.ring_glyph(dx, dz, dist)
                n = h / A
                # specular glint: a facet sparkles when its tilt bounces the sun into the eye
                g = 0.0
                if abs(x - sx_sun) < 3 + r * 0.6:
                    lateral = (x + 0.5 - sx_sun - 1.5 * r * sx / A) / (0.7 + 0.12 * r)
                    g = math.exp(-lateral * lateral) * smoothstep(0.15, 0.6, sz / A + 0.25 * near)
                if g > 0.12:
                    gl = G["glint_hi"] if g > 0.6 else G["glint_mid"] if g > 0.35 else G["glint_lo"]
                    buf.put(x, y, gl, mix(base, pal["glint"], 0.4 + 0.6 * g))
                    continue
                if ring > 0.12:
                    buf.put(x, y, ring_glyph, mix(base, hi, 0.45 + 0.5 * clamp(ring)))
                    continue
                # mirrored sky / trees / sun just below the horizon, pushed sideways by the wave slope
                if 0 <= mrow < yh:
                    wob = int(round(clamp(sx * 0.9, -2.0, 2.0)))
                    xm = min(max(x + wob, 0), W - 1)
                    c, rgb = buf.get(xm, mrow)
                    src_bg = buf.bg[mrow][xm]
                    if src_bg is not None:
                        col = mix(src_bg, base, 0.12 + 0.3 * (1 - fres))
                        c2 = G["tree_refl"] if c == G["tree"] else MIRROR_V.get(c, c)
                        buf.put(x, y, c2, col, bg=col)
                        continue
                    if c != " " and rgb is not None:
                        buf.put(x, y, MIRROR_V.get(c, c), mix(rgb, base, 0.35 + 0.4 * (1 - fres)))
                        continue
                # plain water texture: crest height picks the glyph, tilt picks the brightness.
                # A per-cell random threshold keeps it sparse and stops it looking like a grid.
                thr = 0.34 + 0.32 * hash01(x, y, 5)
                if n > thr:
                    lvl = 1 if n < thr + 0.2 else 2 if n < thr + 0.42 else 3
                    shade = clamp(0.3 + 0.5 * n + 0.3 * sz / A, 0.1, 1.0)
                    buf.put(x, y, wl[lvl], mix(base, hi, shade * (0.3 + 0.6 * near)))
                elif n < -0.55 and hash01(x, y, 9) < 0.25:
                    buf.put(x, y, wl[0], mix(base, hi, 0.18))

    @staticmethod
    def ring_glyph(dx, dz, dist):
        """Glyph for a point on a ripple ring, from where it sits on the (flattened) circle."""
        c = dx / dist                     # cos of the angle around the ring
        if c > 0.93:
            return ")"
        if c < -0.93:
            return "("
        if c > 0.6:
            return "\\" if dz > 0 else "/"
        if c < -0.6:
            return "/" if dz > 0 else "\\"
        return "-" if dz > 0 else "_"

    # branch ----------------------------------------------------------------
    def draw_branch(self, layer, t):
        pal = self.pal
        alpha = self.branch_angle(t)
        for (a, b, w0, w1) in self.branch_segs:
            pa = self.branch_point(a, alpha)
            pb = self.branch_point(b, alpha)
            self.thick_segment(layer, pa, pb, w0, w1, pal["branch"], pal["branch_lit"])

    def thick_segment(self, layer, pa, pb, w0, w1, dark, lit):
        """Tapered line: a cell is drawn if the line, fattened by its width, overlaps the cell box."""
        ax, ay = pa
        bx, by = pb
        vx, vy = bx - ax, (by - ay) * ASPECT               # visual units
        L = math.hypot(vx, vy) or 1e-6
        ux, uy = vx / L, vy / L
        nx, ny = -uy, ux                                    # unit normal
        g = slope_glyph(bx - ax, by - ay)
        wmax = max(w0, w1) + 2
        for y in range(int(min(ay, by) - wmax), int(max(ay, by) + wmax) + 1):
            for x in range(int(min(ax, bx) - wmax), int(max(ax, bx) + wmax) + 1):
                px, py = x + 0.5 - ax, (y + 0.5 - ay) * ASPECT
                s = clamp((px * ux + py * uy) / L)            # nearest point on the segment
                ox, oy = px - s * vx, py - s * vy
                dist = math.hypot(ox, oy) + 1e-9
                d = ox * nx + oy * ny                          # signed: which side of the line
                w = lerp(w0, w1, s)
                # a cell is 1 wide and 2 tall (visual units); its half-extent in the direction
                # of the offset is the box's support function. Overlap test = distance <= both.
                box = 0.5 * abs(ox / dist) + 1.0 * abs(oy / dist)
                if dist <= w + box * 0.85:
                    # side facing the sun is lighter; a hash adds bark texture
                    side = clamp(0.5 - 0.5 * d / (w + 0.5))
                    k = clamp(0.25 + 0.6 * side + 0.25 * (hash01(x, y, 3) - 0.5))
                    ch = g
                    if w > 0.9 and abs(d) < w * 0.4 and hash01(x, y, 11) < 0.25:
                        ch = ":"
                    layer.put(x, y, ch, mix(dark, lit, k))

    # dragonfly -------------------------------------------------------------
    def draw_dragonfly(self, layer, t):
        if t > 19.6 or t < 0.05:
            return
        pal = self.pal
        px, py = self.position(t)
        fl = flight_factor(t)
        vx, vy = self.velocity(t)
        # pitch the nose up when climbing (dy < 0 is up on screen), flat when perched
        pitch = clamp(math.atan2(-vy * ASPECT, abs(vx) + 6.0) * 0.3, -0.22, 0.22)
        flare = bump(t, T_LAND - 0.35, 0.3)                 # nose up just before touching down
        pitch = lerp(pitch, 0.25, flare) * fl
        face = math.cos(self.yaw)                           # +1 right, -1 left, ~0 mid-turn
        L = self.body_len
        curl = 0.25 + 0.35 * fl + 2.2 * bump(t, T_DAP, 0.22) + 0.12 * (1 - fl) * math.sin(1.3 * t)
        legs = smoothstep(T_LAND - 1.2, T_LAND - 0.6, t) * (1 - smoothstep(T_TAKEOFF + 0.2, T_TAKEOFF + 0.6, t))
        cp, sp = math.cos(pitch), math.sin(pitch)

        def to_cell(X, Y):
            # local frame: X forward along the body, Y up, visual units. Rotate by the pitch,
            # squash X by cos(yaw) (that's the turn), then rows = -Y / 2.
            xr = X * cp - Y * sp
            yr = X * sp + Y * cp
            return px + face * xr, py - yr / ASPECT

        # wings first, so the body is drawn over their roots.
        # Angles are in the body's frame: 0 = pointing forward, 90 deg = straight up.
        # The fore wing beats about the horizontal (0 deg), the hind wing about 180 deg and
        # mirrored, so on the up-stroke they form a "V" above the body and on the
        # down-stroke a "V" below it. The hind wing lags a little behind the fore wing.
        wing_len = 0.55 * L
        flap = math.radians(68) * fl
        twitch = sum(0.35 * bump(t, tw, 0.12) for tw in TWITCHES)
        mean_f = lerp(math.radians(35), 0.0, fl) + twitch      # perched: wings held up in a V
        ph = self.wing_phase
        for lag, k in ((0.7, 0.4), (0.0, 1.0)):                 # faint earlier copy = motion blur
            if lag and fl < 0.3:
                continue
            th_f = mean_f + flap * math.sin(ph - lag)
            th_h = math.pi - (mean_f + flap * math.sin(ph - lag - 0.6))
            self.wing(layer, to_cell, (0.2, 0.5), th_f, wing_len, face, k)
            self.wing(layer, to_cell, (-1.0, 0.5), th_h, wing_len * 0.92, face, k)

        # legs: landing gear
        if legs > 0.5:
            for X0, dxl in ((-0.6, -0.8), (0.4, 0.8)):
                x0, y0 = to_cell(X0, -0.6)
                x1, y1 = to_cell(X0 + dxl, -2.2)
                layer.put(x1, y1, slope_glyph(x1 - x0, y1 - y0), scale(pal["band"], 1.3))

        # abdomen: a slightly drooping curve behind the thorax, in coloured bands
        seen = set()
        n = int(L * 3)
        prev = to_cell(-1.0, 0.0)
        for i in range(1, n + 1):
            s = i / n
            X = -1.0 - s * (L - 2.0)
            Y = -curl * s * s * 2.0
            c = to_cell(X, Y)
            cell = (int(math.floor(c[0])), int(math.floor(c[1])))
            if cell not in seen:
                seen.add(cell)
                g = slope_glyph(c[0] - prev[0], c[1] - prev[1])
                if g == "-":
                    g = G["abdomen"] if s < 0.92 else G["tip"]
                band = (int(s * 7) % 2 == 1)
                rgb = pal["band"] if band else mix(pal["body"], pal["band"], s * 0.4)
                layer.put(c[0], c[1], g, rgb)
            prev = c
        # thorax and head
        for X in (0.6, 0.0, -0.6):
            x, y = to_cell(X, 0.0)
            layer.put(x, y, G["thorax"], pal["thorax"])
        x, y = to_cell(1.3, 0.1)
        layer.put(x, y, G["head"], pal["eyes"])

    def wing(self, layer, to_cell, root, theta, length, face, k):
        """One wing: a line from the root at angle theta (local frame), two cells wide when steep.

        k < 1 draws a faint "ghost" of the wing a moment earlier in the beat (motion blur)."""
        pal = self.pal
        rx, ry = root
        ct, st = math.cos(theta), math.sin(theta)
        if abs(st) < 0.3:
            return                            # mid-stroke the wing is edge-on: almost invisible
        # glint: a wing flashes when its angle on screen lines up with the light
        world_theta = math.atan2(st, ct * face)
        glint = max(0.0, math.cos(world_theta - 1.1)) ** 8
        col = mix(pal["band"], pal["wing"], (0.55 + 0.45 * glint) * k)
        x0, y0 = to_cell(rx, ry)
        x1, y1 = to_cell(rx + ct * length, ry + st * length)
        g = slope_glyph(x1 - x0, y1 - y0)
        back = -1 if face > 0 else 1          # the trailing edge is behind the leading edge
        n = int(length * 2) + 2
        for i in range(1, n + 1):
            s = i / n
            if s < 0.2:
                continue                      # the root is hidden by the thorax
            if k < 1.0 and s < 0.6:
                continue                      # ghosts only show the outer half
            cx, cy = to_cell(rx + ct * length * s, ry + st * length * s)
            layer.put(cx, cy, g, col)
            if g != "-" and 0.25 < s < 0.9 and k == 1.0:
                layer.put(cx + back, cy, g, scale(col, 0.75))

    # reflection ------------------------------------------------------------
    def draw_reflection(self, buf, layer, t):
        """Mirror the stage about its waterline; shift each row sideways by a wobble."""
        ys = self.ys
        for (x, y), (c, rgb) in layer.cells.items():
            if y >= ys - 0.5:
                continue
            yr = int(math.floor(2 * ys - y - 1))
            if yr >= self.H:
                continue
            depth = yr - ys
            wob = 0.9 * math.sin(0.9 * yr + 2.3 * t) * min(1.0, depth / 3.0)
            xr = int(round(x + wob))
            if not (0 <= xr < self.W):
                continue
            under = buf.row_bg[yr]
            # break the reflection up where the surface is choppy
            if hash01(xr, yr, int(t * 6)) < 0.1 + 0.03 * depth:
                continue
            buf.put(xr, yr, MIRROR_V.get(c, c), mix(rgb, under, 0.55 + 0.02 * depth))

    # reeds -----------------------------------------------------------------
    def draw_reeds(self, buf, t):
        """Foreground reeds: each stem is x(s) = x0 + bend * s^2 (a cantilever under wind)."""
        pal, W, H = self.pal, self.W, self.H
        rng = random.Random(self.reeds_seed)
        clusters = ((0.04, 3), (0.95, 2))
        for cx, count in clusters:
            for i in range(count):
                x0 = cx * W + rng.uniform(-3.5, 3.5)
                height = H * rng.uniform(0.18, 0.32)
                lean = rng.uniform(-0.6, 0.6)
                ph = rng.uniform(0, TAU)
                bend = lean * height * 0.3 + 1.2 * math.sin(0.9 * t + ph) + 0.4 * math.sin(2.3 * t + ph)
                prev = (x0, H)
                n = int(height * 2)
                for j in range(1, n + 1):
                    s = j / n
                    x = x0 + bend * s * s
                    y = H - height * s
                    g = slope_glyph(x - prev[0], y - prev[1])
                    buf.put(x, y, g, mix(pal["reed"], pal["reed_head"], 0.15 * s))
                    prev = (x, y)
                if i % 2 == 0:  # cattail head
                    hx = x0 + bend
                    for dy in range(2):
                        buf.put(hx, H - height - 1 + dy, G["reed_head"], pal["reed_head"])

    # debug -----------------------------------------------------------------
    def draw_debug(self, buf, t, fps):
        pal = self.pal
        hud = pal["hud"]
        tt = 0.0
        while tt < PERIOD:
            x, y = self.base_path(tt)
            c, _ = buf.get(x, y)
            if c == " " or c in G["water"]:
                buf.put(x, y, G["path"], hud)
            tt += 0.04
        for i, p in enumerate(self.points(t)):
            buf.put(p[0], p[1], str(i), (255, 90, 90))
        fl = flight_factor(t)
        vx, vy = self.velocity(t)
        info = " t=%5.2fs  %-12s  wings %.1f Hz  speed %4.1f cells/s  yaw %3d deg  branch %+.1f deg  %4.1f fps " % (
            t, phase_name(t), 5.5 * fl, math.hypot(vx, vy), math.degrees(self.yaw),
            math.degrees(self.branch_angle(t)), fps)
        buf.text(0, self.H - 1, info[: self.W], hud)


# --------------------------------------------------------------------------- #
# terminal plumbing
# --------------------------------------------------------------------------- #

def setup_stdout():
    global UNICODE, G
    if os.name == "nt":
        os.system("")  # enables ANSI/VT processing in classic Windows consoles
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    UNICODE = enc.startswith("utf")
    G = GLYPHS_U if UNICODE else GLYPHS_A


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="A dragonfly skims a pond and lands on a branch.")
    ap.add_argument("--palette", "-p", default="dusk", choices=sorted(PALETTES))
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed (0.5 = half speed)")
    ap.add_argument("--seed", type=int, default=None, help="seed for waves, tree line, reeds and fish ripples")
    ap.add_argument("--once", action="store_true", help="play once and stay perched instead of looping")
    ap.add_argument("--debug", action="store_true", help="draw the flight path, waypoints and a HUD")
    ap.add_argument("--ascii", action="store_true", help="plain ASCII glyphs even on a UTF-8 terminal")
    ap.add_argument("--no-reeds", action="store_true", help="hide the foreground reeds")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--transparent", action="store_true", help="keep the terminal's own background")
    ap.add_argument("--list-palettes", action="store_true")
    ap.add_argument("--snapshot", type=float, metavar="T", help="print a single frame at time T and exit")
    return ap.parse_args(argv)


def simulate(scene, t_end, W, H, step=1.0 / 30.0):
    """Advance the integrated state (wing phase, yaw) from 0 to t_end without drawing."""
    scene.layout(W, H)
    t = 0.0
    while t < t_end:
        tl = min(t, T_TAKEOFF - 0.5) if scene.args.once else t % PERIOD
        scene.update(tl, step)
        t += step


def main(argv=None):
    global G
    args = parse_args(argv)
    if args.list_palettes:
        print("\n".join(sorted(PALETTES)))
        return
    setup_stdout()
    if args.ascii:
        G = GLYPHS_A
    if G is GLYPHS_A:
        MIRROR_V["_"] = "-"          # no overline in plain ASCII
    color = not args.no_color and os.environ.get("NO_COLOR") is None
    solid = not args.transparent
    scene = Scene(args, PALETTES[args.palette])

    if args.snapshot is not None:
        W, H = shutil.get_terminal_size((110, 48))
        simulate(scene, args.snapshot, W, H)
        buf = scene.render(args.snapshot, W, H)
        sys.stdout.write(buf.serialize(color, solid, plain_lines=True) + "\n")
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
            t = (now - t0) * args.speed
            tl = min(t, T_TAKEOFF - 0.5) if args.once else t % PERIOD
            W, H = shutil.get_terminal_size((100, 40))
            scene.layout(W, H)
            scene.update(tl, dt * args.speed)
            out.write(scene.render(t, W, H, fps).serialize(color, solid))
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
