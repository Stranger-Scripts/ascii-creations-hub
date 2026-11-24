# How `dragonfly.py` works

A walkthrough of the math and logic behind the dragonfly short. Every section points at the function in [`src/dragonfly.py`](../src/dragonfly.py) where the idea lives, so you can read the two side by side.

The fastest way to see the ideas below in action:

```bash
python3 src/dragonfly.py --debug --speed 0.4
```

`--debug` draws the flight path, the waypoints (red digits) and a HUD with the current phase, wing-beat frequency, speed, heading and branch angle. `--speed 0.4` is slow motion.

---

## 0. The big picture: one frame is a function of time

Every frame, the main loop asks *"what does the scene look like at time `t`?"* and draws it from scratch. Almost everything is a pure function of `t`:

```
t  ──►  where is the dragonfly?        (spline + keyframes)        Scene.position
   ──►  how far is the branch bent?    (damped spring)             Scene.branch_angle
   ──►  what does the water look like? (sum of sine waves)         Scene.draw_water
   ──►  which ripples exist?           (list of start times)       Scene.ripples
```

Only two things can't be computed from `t` alone and are *integrated* frame by frame instead, in `Scene.update`:

- the **wing phase** (because the beat frequency changes over time, see §4)
- the **heading** (the dragonfly turns round at a limited rate, see §3)

Because nearly everything is a function of `t`, `--snapshot 12` can jump straight to second 12. It only has to fast-forward those two integrated values (`simulate()`), which is cheap.

The frame is drawn with the **painter's algorithm**, back to front:

```
sky gradient → stars → sun → tree line → water (+ background reflection, glints, ripples)
   → reflection of the branch and dragonfly → branch → dragonfly → reeds → debug overlay
```

---

## 1. Terminal cells are not square

A terminal cell is about twice as tall as it is wide. If you rotate or measure distances directly in (column, row) coordinates, circles come out as tall ovals and a 45° line looks like 63°.

The fix used everywhere in the script is to switch to **visual units** for any geometry and switch back only to place a character:

$$X = x_\text{col}, \qquad Y = -2\,y_\text{row}$$

(the minus sign makes "up" positive, as in maths class). `ASPECT = 2.0` is that factor of 2. The helper `rotate_vis()` shows the pattern:

```python
X, Y = dx, -dy * ASPECT            # cells  -> visual units
X, Y = X*c - Y*s, X*s + Y*c        # ordinary 2-D rotation
return X, -Y / ASPECT              # visual -> cells
```

The sun is round on screen for the same reason: its distance test is `hypot(dx, dy * ASPECT) < R`.

---

## 2. The flight path

### 2.1 Waypoints and a Catmull-Rom spline

The route is nine waypoints `P0 … P8` (`Scene.waypoints` / `Scene.points`). Run `--debug` to see them as red digits. A smooth curve through them comes from a **Catmull-Rom spline** (`catmull_rom()`). For the segment between $P_1$ and $P_2$, with neighbours $P_0$ and $P_3$, and $s \in [0, 1]$:

$$
p(s) = \tfrac12\Big[\,2P_1 + (-P_0 + P_2)\,s + (2P_0 - 5P_1 + 4P_2 - P_3)\,s^2 + (-P_0 + 3P_1 - 3P_2 + P_3)\,s^3\Big]
$$

Two properties make it ideal for animation paths:

- it passes **exactly through** every waypoint ($p(0) = P_1$, $p(1) = P_2$), unlike a Bézier curve, whose control points pull the curve without being on it;
- the direction at each waypoint is $\tfrac12(P_{i+1} - P_{i-1})$, i.e. "from the previous point towards the next", so consecutive segments join without a kink.

A global path parameter `u` picks the segment and the position inside it: `i = int(u)`, `s = u - i`.

### 2.2 Keyframes: when to be where

The spline says *where* the path goes, not *when*. That is the job of `KEYS`, a list of `(time, u)` pairs:

```python
(2.7, 2), (3.5, 2),    # arrive at P2 at 2.7 s, still at P2 at 3.5 s -> hover
(4.5, 3), (4.95, 3),   # drop to P3, hover there while dipping
```

Between two keys, `u_at()` does not move linearly but with **smoothstep**:

$$\operatorname{smoothstep}(x) = 3x^2 - 2x^3, \qquad \frac{d}{dx}\operatorname{smoothstep}(x) = 6x(1-x)$$

The derivative is **zero at both ends**, so the dragonfly starts every leg from rest, accelerates, and brakes into the next key. Strung together that gives *dash, stop, dash, stop*, which is exactly how dragonflies fly. Real dragonflies hover and then dart, so the "ease in / ease out" here is behaviour, not just polish. Two keys with the same `u` in a row are a hover.

Want a different flight? Edit `KEYS` and the waypoints; nothing else needs to change.

### 2.3 A real bug worth knowing about: the hook

The first version made the dragonfly swing *past* the branch tip and come back. The cause: at the perch $P_7$, Catmull-Rom set the tangent to $\tfrac12(P_8 - P_6)$, and $P_8$ (the exit, far to the right) pulled the curve into a hook. The fix in `base_path()` is to clamp the neighbours at the perch so its tangent is zero:

```python
if i + 1 == PERCH: p3 = pts[PERCH]     # arriving: P3 := P2
if i == PERCH:     p0 = pts[PERCH]     # leaving:  P0 := P1
```

General lesson: **a spline's shape near a point depends on the points either side of it**, so a full stop needs special treatment.

### 2.4 A moving target

The perch is on the branch, and the branch sways (§6), so `points(t)` recomputes $P_6$ and $P_7$ from the branch tip every frame. The spline smoothly tracks a moving end point, and after landing the dragonfly simply rides the branch as it bobs.

### 2.5 Hover jitter

A hovering insect is never perfectly still. `position()` adds a small wobble to the spline:

$$\Delta x = 0.6\sin(2.1t) + 0.3\sin(5.3t + 1), \qquad \Delta y = 0.35\sin(2.9t + 0.5) + 0.2\sin(7.1t)$$

The frequencies are **incommensurate** (no simple ratio), so the sum never visibly repeats and reads as organic. The jitter is multiplied by the flight factor, so it fades out on landing.

---

## 3. Facing and turning round

The dragonfly faces left or right. Which way is decided in `update()` by **looking ahead**: compare the x-position now with the x-position 0.45 s from now. Looking ahead (instead of using the current velocity) makes it turn *before* it sets off, which reads as intent. A dead zone (`|ahead| > 0.4`) stops it flipping back and forth while hovering.

The turn itself is a rotation about the vertical axis. Projected onto the screen, that only scales the x-axis by $\cos(\text{yaw})$:

```python
face = math.cos(self.yaw)        # +1 = right, -1 = left, ~0 = side-on mid-turn
x = px + face * xr
```

So mid-turn the body foreshortens to a few characters and then unfolds mirrored. That is the cheapest possible 3-D turn. Yaw moves towards its target at most $\pi$ per 0.35 s, so the turn takes about a third of a second.

Two more bugs hid in here: the branch bobbing after landing moved the look-ahead point by a few columns and turned the perched dragonfly round, and a turn interrupted half-way left it side-on forever. Hence the two rules: *while perched, never turn*, and *if there is no target, finish the turn you are in*.

### Pitch

Nose up when climbing, down when diving:

$$\text{pitch} = 0.3\cdot\operatorname{atan2}(-v_y \cdot 2,\; |v_x| + 6)$$

`atan2` gives the angle of the velocity. The `+6` keeps slow movements from producing big angles, and the result is clamped to ±0.22 rad (about 13°). Just before touchdown a `bump()` blends the pitch towards nose-up: the **landing flare**, as birds and aircraft do it.

---

## 4. Wings

### 4.1 Angle as a sine

Each wing is a straight line from its root, at angle

$$\theta_\text{fore} = \bar\theta + A\sin\varphi, \qquad \theta_\text{hind} = \pi - \big(\bar\theta + A\sin(\varphi - 0.6)\big)$$

- the fore wing swings about the horizontal ($\bar\theta = 0$) and the hind wing about $\pi$, mirrored, so the up-stroke is a **V above** the body and the down-stroke a **V below** it;
- the hind wing **lags by 0.6 rad**. Real dragonflies beat their fore and hind wings out of phase, and here it also stops all four wings lining up at once;
- when $|\sin\theta| < 0.3$ the wing is skipped: mid-stroke it is edge-on to the camera and almost invisible, and skipping it avoids a horizontal line through the body.

Perched, $A \to 0$ and $\bar\theta \to 35°$: wings held in a resting V. `TWITCHES` adds a quick `bump()` to $\bar\theta$ twice while perched.

### 4.2 Why the phase is integrated

The beat frequency $f$ drops from 5.5 Hz to 0 on landing. The tempting `sin(2π · f(t) · t)` is wrong: the instantaneous frequency of $\sin(g(t))$ is $g'(t)/2\pi$, and

$$\frac{d}{dt}\big(2\pi f(t)\,t\big) = 2\pi\big(f(t) + f'(t)\,t\big)$$

The $f'(t)\,t$ term grows with $t$, so at second 11 a smooth slow-down would turn into a wild burst of flapping. The correct phase is the integral of the frequency,

$$\varphi(t) = \int_0^t 2\pi f(\tau)\,d\tau$$

which `update()` accumulates frame by frame: `phase += 2π · f · dt`. This is the reason the script has any state at all.

### 4.3 Nyquist: why 5.5 Hz and not 30

Real dragonflies beat their wings around 30–40 times a second. The animation runs at 30 frames per second, and a sampled signal can only show frequencies up to **half** the sample rate (the *Nyquist frequency*, 15 Hz here). Anything faster *aliases*: it shows up as a slower or even backwards motion, the same effect as the wagon wheels that spin backwards in old films. At 5.5 Hz each beat gets about 5–6 frames, enough to read as flapping.

### 4.4 Motion blur and glint

- **Ghost wing:** the wing is also drawn faintly at phase $\varphi - 0.7$, i.e. where it was a moment ago. That is a two-sample approximation of motion blur.
- **Glint:** $\text{brightness} \propto \max(0, \cos(\theta - \theta_\text{light}))^8$. A high power turns a broad cosine into a narrow flash, so the wing only lights up for the instant it lines up with the light. This is the same trick as the specular term in Phong shading.

### 4.5 Choosing a character for a line

`slope_glyph()` picks `-`, `/`, `|` or `\` from a line's direction. Measured in **visual units**, the four characters cover four 45°-wide sectors, so the boundaries sit at 22.5°: $\tan 22.5° \approx 0.414$, which is the `0.42` in the code. This one function draws the wings, the abdomen when it bends, the legs, the branch, the reeds and the reflections.

---

## 5. The body

The body is built in a **local frame**: $X$ forward along the body, $Y$ up, origin at the thorax. Everything is defined there and pushed through one function, `to_cell()`, which applies pitch (rotation), facing/turn (x-scale by $\cos(\text{yaw})$), translation, and the visual-to-cell conversion. The abdomen is the curve

$$Y = -\text{curl}\cdot s^2 \cdot 2, \qquad s \in [0, 1] \text{ along the abdomen}$$

a parabola, so it droops more towards the tip. At the dip, `curl` gets a `bump()` centred on `T_DAP` and the tip curls down into the water. Alternate segments switch colour (`int(s*7) % 2`) for the banded look.

---

## 6. The branch

### 6.1 Thick, tapered lines

The branch is four segments, each with a start and end half-width. `thick_segment()` decides per cell whether it is covered:

1. **Project** the cell centre $p$ onto the segment $a \to b$: $s = \operatorname{clamp}\big(\frac{(p-a)\cdot(b-a)}{|b-a|^2}\big)$. Clamping to $[0,1]$ makes the nearest point stay on the segment (that's what gives round end caps).
2. The **distance** from $p$ to that nearest point is compared with the half-width $w(s) = \operatorname{lerp}(w_0, w_1, s)$, which tapers the branch.
3. A cell is a 1 × 2 box, not a point, so the test is widened by the box's **support function** in the direction of the offset: $0.5\,|o_x| + 1.0\,|o_y|$ for a unit offset $o$. Without it, thin near-horizontal twigs fall between row centres and break into dashes.

Another bug that taught something: the first version used only the *perpendicular* distance, which ignores how far past the end of the segment you are, so the stick poked three rows above its own tip.

The sign of the perpendicular distance says which side of the branch a cell is on; that side gets the lighter colour (lit by the sun).

### 6.2 Swaying and the landing bob

The whole branch rotates about its base by an angle $\alpha(t)$ (`branch_angle()`):

- **wind:** $0.012\sin(0.8t) + 0.006\sin(1.9t + 1)$, two incommensurate sines again;
- **landing:** an impulse makes it ring like a **damped harmonic oscillator**

$$\alpha(\tau) = A\,e^{-\zeta\omega_0\tau}\sin(\omega_d\,\tau), \qquad \omega_d = \omega_0\sqrt{1-\zeta^2}, \qquad \tau = t - t_\text{land}$$

with $\omega_0 = 2\pi \cdot 1.4$ rad/s (it swings 1.4 times a second) and damping ratio $\zeta = 0.12$ (lightly damped: several visible wobbles). The exponential is the decay envelope; the sine is the oscillation. Take-off adds a smaller impulse the other way. Because the perch is computed from the rotated tip (§2.4), the dragonfly rides the bob for free.

---

## 7. The pond

### 7.1 A pinhole camera for the water

The water is not drawn as flat stripes. It is a **ground plane** seen through a pinhole camera, so things further away look smaller and flatter. For a camera at height $h$ with focal length $f$, a point on the ground at depth $Z$ appears $f\,h/Z$ below the horizon. Turn that around and every water row tells you how far away it is:

$$Z_\text{world} = f \cdot \frac{r_s}{r}, \qquad X_\text{world} = (x - W/2)\cdot\frac{r_s}{r}$$

where $r$ is the number of rows below the horizon and $r_s$ is the number of rows down to the "stage" (where the branch stands), which is placed at depth $Z = f$ so that one column there equals one world unit. `layout()` precomputes $X$ and $Z$ for every water cell once per terminal size.

```
          horizon  ─────────────────────────────   r → 0,  Z → ∞   (far)
                    ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
                     ~   ~   ~   ~   ~   ~
  stage waterline  ───────────────|──────────   r = r_s, Z = f
                      ~     ~     ~     ~
                   ~        ~        ~        r large, Z small (near)
```

Everything defined on the ground plane — waves, ripple rings — gets perspective automatically: rows near the horizon each cover a lot of depth, so rings come out as flat ellipses there and rounder up close. No special case for the ellipses is needed.

### 7.2 Waves

The surface height is a sum of six travelling sine waves:

$$h(X, Z, t) = \sum_i a_i \sin\big(k_{x,i} X + k_{z,i} Z - \omega_i t + \phi_i\big)$$

- $\vec k_i$ points in the wave's direction, with length $|\vec k_i| = 2\pi/\lambda_i$;
- $\omega_i = \sqrt{g\,k_i}$ is the **deep-water dispersion relation**: long waves travel faster than short ones. That's why the pattern keeps changing shape instead of sliding along as a block. (The code scales $g$ down by 0.35 because a pond in a terminal looks better slightly slowed down.);
- wavelengths 11.3, 7.1, 4.7, 3.3, 2.3, 1.7 are deliberately *not* nice ratios of each other. The first version used 4 waves with ratios close to whole numbers and the water looked like a repeating grid.

The slope (surface tilt) is the derivative, computed alongside the height for almost nothing:

$$\frac{\partial h}{\partial X} = \sum_i a_i k_{x,i}\cos(\ldots), \qquad \frac{\partial h}{\partial Z} = \sum_i a_i k_{z,i}\cos(\ldots)$$

Height picks the glyph (`-`, `~`, `≈`), tilt picks the brightness. A per-cell random threshold (`0.34 + 0.32 · hash`) keeps the texture sparse and irregular.

### 7.3 Anti-aliasing the waves (Nyquist again, in space)

Near the horizon one row covers a lot of depth. A 1.7-unit wave there would be sampled far less than twice per wavelength and alias into noise. The fix is the spatial version of §4.3: for every row and every wave, `layout()` estimates how much ground one cell covers in that wave's direction,

$$d = |\hat k_x|\,\Delta X_\text{per column} + |\hat k_z|\,\Delta Z_\text{per row}, \qquad \Delta Z_\text{per row} = \frac{Z^2}{f\,r_s}$$

and fades the wave out with `smoothstep(2, 4, λ/d)`: fully visible with 4+ samples per wavelength, gone below 2. This is the idea behind **mip-mapping** in 3-D graphics. It's also why far water looks calm and glassy, which happens to be what real water looks like at a grazing angle.

### 7.4 Reflections

**Fresnel:** water reflects more at grazing angles. Near the horizon it's almost a mirror; looking down at your feet you see into it. The row colour is `mix(deep water, reflected sky, fresnel)` with fresnel decaying exponentially from the horizon.

**Background reflection:** for a water row $y$ the mirrored sky row is $y_m = 2y_h - 1 - y$. The cell there (sun, tree, star) is copied down, shifted sideways by `round(∂h/∂X · 0.9)`: tilted facets bend the reflected ray, which is what makes reflections wobble.

**Foreground reflection** (`draw_reflection()`): the branch and dragonfly are mirrored about **their own waterline** $y_s$, not the horizon. An object reflects about the point where it meets the water, and for the stage that point is $y_s$. Mirroring everything about the horizon is a common mistake and makes foreground reflections float. Characters are mirrored too (`/` ↔ `\`, `▲` ↔ `▼`, via `MIRROR_V`), each row is wobbled with a sine that grows with depth, and a few cells are randomly dropped where the surface is choppy.

### 7.5 Sun glints

A wave facet sparkles when its tilt bounces the sun exactly into your eye. The code approximates that in two parts: the facet has to sit roughly below the sun, *offset sideways by its own slope* ($x \approx x_\text{sun} + 1.5\, r\, \partial h/\partial X$), and it has to tilt towards the viewer ($\partial h/\partial Z$ large). Facets that pass both tests become `*`, `+` or `·`. Because the allowed offset grows with $r$, the glitter path widens towards you, as a real sun path on water does.

### 7.6 Ripples

Each ripple is `(x, z, start time, strength)` on the ground plane (`ripples()`): one where the abdomen dips (`T_DAP`), one at the branch base on landing and take-off, and two random "fish rising" per loop (`--seed` decides where). For a cell at distance $d$ from the centre:

- the ring radius grows linearly, $R(t) = 0.6 + 4\,(t - t_0)$;
- a cell is on a ring if $|d - R| < \text{width}$, for the leading ring and a fainter one 3.2 units behind it;
- **width** is at least one cell's footprint in the radial direction. A thin ring would otherwise fall between rows near the horizon and break into dots: the same sampling problem as §7.3, solved the same way;
- strength decays as $e^{-(t-t_0)/1.4}$.

The ring character depends on where the cell sits on the circle (`ring_glyph()`): `(` and `)` on the sides, `/` and `\` on the shoulders, `-` on the far edge and `_` on the near edge. Because the circle lives on the ground plane, the projection flattens it into an ellipse by itself.

---

## 8. Scenery

**Tree line.** A gentle hill made of 1-D **value noise** (random values at integer points, smoothly interpolated, several octaves at half amplitude and double frequency: *fractal Brownian motion*), topped with pine **cones**:

$$h(x) = \max\Big(\text{hill}(x),\; \max_i \big(h_i - 0.9\,|x - x_i|\big)\Big)$$

The max of a lot of triangles is a forest silhouette. The top cell of each column is only partly covered, so its glyph is chosen from the slope (`◢` rising, `◣` falling, `▲` at a peak). That's anti-aliasing with characters instead of grey levels.

**Reeds.** Each stem is $x(s) = x_0 + \text{bend}\cdot s^2$, with $s$ from root to tip. A thin rod fixed at the bottom and pushed sideways bends like this, approximately: no bend at the root, most at the tip. `bend` is a lean plus two sines, so the reeds sway in the wind.

**Stars.** A hash of the cell coordinates decides whether a cell has a star (about 1 in 80); a sine with a per-star speed makes it twinkle. Hashing instead of storing a list means the stars stay put when you resize the terminal.

---

## 9. Getting it onto the terminal

- `Buffer` stores a character, a foreground colour and an optional background colour per cell; rows also have a default background (the sky and water gradients).
- `serialize()` walks each row, emitting a truecolour escape (`ESC[38;2;r;g;bm`) only when the colour changes. Colours are quantised to steps of 4 (`>> 2`) so near-identical colours share one cached escape string, which keeps frames around 20 KB.
- The program switches to the **alternate screen** (`ESC[?1049h`), hides the cursor, and restores both on Ctrl+C, so your scrollback is untouched.
- Frame pacing: render, write, then `sleep` whatever is left of the 1/fps budget. `dt` is clamped to 0.1 s so a stall (a resize, say) doesn't make the wings jump.

---

## 10. Things to try

| Change | Where | What you'll learn |
|---|---|---|
| Replace `smoothstep` in `u_at()` with plain linear interpolation | `u_at` | Without easing, motion looks robotic and stops become jolts. |
| Set the wing frequency to 25 Hz | `update` (`beat = …`) | Aliasing: the wings appear to beat slowly or backwards. |
| Replace the integrated phase with `sin(2π·f·t)` | `draw_dragonfly` | The flapping burst around the landing from §4.2. |
| Set `zeta` to 0.02 or 0.7 | `branch_angle` | Underdamped (rings for ages) vs. nearly critically damped (one soft dip). |
| Remove the `fades` factor | `draw_water` | Spatial aliasing near the horizon. |
| Mirror the stage about `self.yh` instead of `self.ys` | `draw_reflection` | Why reflections have to be mirrored about each object's own waterline. |
| Add a waypoint and two keys | `waypoints`, `KEYS` | A new manoeuvre, without touching any other code. |
