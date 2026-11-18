"""Live 2-D view of the simulated robot (for demos and video recording).

    python -m teleop.server --backend mock --transport tcp --port 9000 --gui

The robot server keeps running in a background thread; this window only
*reads* its state about 20 times per second and draws:

* the room (walls, box, cylinder) and a 1 m grid;
* the robot as a circle with a heading line, coloured by state
  (IDLE grey, MOVING blue, OBSTACLE orange, LINK_LOST red);
* the 16 sonar rays (front rays turn orange/red as obstacles get close);
* the path driven so far and the current goal (goto / move target);
* a side panel with pose, speeds, state and a log of the latest commands.

Closing the window stops the server.  Works with the mock backend; with
CoppeliaSim it shows the robot and sonars without the room geometry.
"""

from __future__ import annotations

import math
import time
from collections import deque

import matplotlib

try:  # Tk ships with Python on Windows/macOS and as python3-tk on Linux
    import tkinter  # noqa: F401
    matplotlib.use("TkAgg")
except ImportError:  # pragma: no cover - fall back to whatever GUI backend matplotlib finds
    pass
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.animation import FuncAnimation  # noqa: E402
from matplotlib.patches import Circle, Polygon  # noqa: E402

STATE_COLOURS = {"IDLE": "#7d8590", "MOVING": "#2a78d6", "OBSTACLE": "#eb6834", "LINK_LOST": "#e34948"}
INK, INK2, GRID = "#1b1b1b", "#55595f", "#e4e3df"
SONAR_ANGLES_DEG = [90, 50, 30, 10, -10, -30, -50, -90, -90, -130, -150, -170, 170, 150, 130, 90]


class SimViewer:
    def __init__(self, server, title_extra: str = "", fps: int = 20, trail: int = 4000):
        self.server = server
        self.backend = server.backend
        self.fps = fps
        self.trail = deque(maxlen=trail)
        self.title_extra = title_extra
        self.t0 = time.monotonic()

        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
        self.fig = plt.figure(figsize=(12.5, 7.0), facecolor="white")
        try:
            self.fig.canvas.manager.set_window_title("Teleoperated P3-DX - live simulation")
        except Exception:
            pass
        self.ax = self.fig.add_axes([0.04, 0.07, 0.60, 0.84])
        self.panel = self.fig.add_axes([0.67, 0.07, 0.31, 0.84])
        self.panel.axis("off")
        self._draw_static()
        self._make_artists()

    # ------------------------------------------------------------------ static scene
    def _draw_static(self):
        ax = self.ax
        world = getattr(self.backend, "world", None)
        if world is None:            # CoppeliaSim: scenes/build_scene.py builds this same room
            from .backends.mock import World
            world = World.default()
        xs, ys = [0.0], [0.0]
        if world is not None:
            for x1, y1, x2, y2 in world.segments:
                ax.plot([x1, x2], [y1, y2], color=INK, linewidth=2.2, solid_capstyle="round", zorder=3)
                xs += [x1, x2]
                ys += [y1, y2]
            # fill the box (any closed 4-segment group inside the walls)
            inner = world.segments[4:]
            for k in range(0, len(inner) - 3, 4):
                pts = [(s[0], s[1]) for s in inner[k:k + 4]]
                ax.add_patch(Polygon(pts, closed=True, facecolor="#c9c6bd", edgecolor=INK, linewidth=1.5,
                                     zorder=2))
            for cx, cy, r in world.circles:
                ax.add_patch(Circle((cx, cy), r, facecolor="#c9c6bd", edgecolor=INK, linewidth=1.5, zorder=2))
        pad = 0.3
        ax.set_xlim(min(xs) - pad, max(xs) + pad)
        ax.set_ylim(min(ys) - pad, max(ys) + pad)
        ax.set_aspect("equal")
        ax.set_xticks(range(math.floor(min(xs)), math.ceil(max(xs)) + 1))
        ax.set_yticks(range(math.floor(min(ys)), math.ceil(max(ys)) + 1))
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        for s in ax.spines.values():
            s.set_color(INK2)
        sx, sy, _ = getattr(self.backend, "start_pose", (0.0, 0.0, 0.0))
        ax.plot([sx], [sy], marker="+", color=INK2, markersize=12, zorder=1)
        ax.text(sx + 0.08, sy - 0.25, "start", color=INK2, fontsize=8)

    def _make_artists(self):
        ax = self.ax
        self.trail_line, = ax.plot([], [], color="#2a78d6", linewidth=1.6, alpha=0.55, zorder=4)
        self.rays = [ax.plot([], [], linewidth=1.0, zorder=5)[0] for _ in range(16)]
        r = getattr(getattr(self.backend, "p", None), "body_radius", 0.26)
        self.body = Circle((0, 0), r, facecolor="#2a78d6", edgecolor=INK, linewidth=1.5, alpha=0.9, zorder=6)
        ax.add_patch(self.body)
        self.heading, = ax.plot([], [], color="white", linewidth=2.5, zorder=7)
        self.goal, = ax.plot([], [], marker="x", color="#1baf7a", markersize=14, markeredgewidth=3,
                             linestyle="none", zorder=8)
        self.goal_label = ax.text(0, 0, "", color="#13805a", fontsize=9, zorder=8)
        self.title = self.fig.suptitle("", fontsize=13, fontweight="bold", color=INK, x=0.04, ha="left")
        self.panel_text = self.panel.text(0.0, 1.0, "", va="top", ha="left", family="DejaVu Sans Mono",
                                          fontsize=10.5, color=INK, transform=self.panel.transAxes)
        self.state_badge = self.panel.text(0.0, 0.40, "", va="top", ha="left", fontsize=15,
                                           fontweight="bold", transform=self.panel.transAxes,
                                           bbox=dict(boxstyle="round,pad=0.4", facecolor="#7d8590",
                                                     edgecolor="none"), color="white")
        self.log_text = self.panel.text(0.0, 0.31, "", va="top", ha="left", family="DejaVu Sans Mono",
                                        fontsize=9.5, color=INK2, transform=self.panel.transAxes)

    # ------------------------------------------------------------------ per frame
    def _update(self, _frame):
        srv, be = self.server, self.backend
        if srv._stop.is_set():           # Ctrl+C in the terminal: close the window too
            plt.close(self.fig)
            return []
        x, y, th = be.get_pose()
        if not self.trail or math.hypot(x - self.trail[-1][0], y - self.trail[-1][1]) > 0.005:
            self.trail.append((x, y))
        tx, ty = zip(*self.trail)
        self.trail_line.set_data(tx, ty)

        state = srv.state
        colour = STATE_COLOURS.get(state, "#2a78d6")
        self.body.center = (x, y)
        self.body.set_facecolor(colour)
        r = self.body.radius
        self.heading.set_data([x, x + r * math.cos(th)], [y, y + r * math.sin(th)])

        sonar = be.get_sonar()
        stop, slow = srv.p.safety.stop_distance, srv.p.safety.slow_distance
        for i, (line, ang) in enumerate(zip(self.rays, SONAR_ANGLES_DEG)):
            a = th + math.radians(ang)
            d = sonar[i]
            sx, sy = x + r * math.cos(a), y + r * math.sin(a)
            line.set_data([sx, sx + d * math.cos(a)], [sy, sy + d * math.sin(a)])
            if d <= stop:
                line.set_color("#e34948"); line.set_alpha(0.95); line.set_linewidth(2.0)
            elif d < slow:
                line.set_color("#eb6834"); line.set_alpha(0.85); line.set_linewidth(1.6)
            elif d < 1.0:
                line.set_color("#eda100"); line.set_alpha(0.6); line.set_linewidth(1.0)
            else:
                line.set_color("#9aa3ad"); line.set_alpha(0.25); line.set_linewidth(0.8)

        # goal marker
        c = srv.controller
        tgt = dict(c._target) if c._target else {}
        gx = gy = None
        if c.mode == "goto":
            gx, gy, label = tgt.get("x"), tgt.get("y"), f"goal ({tgt.get('x'):.1f}, {tgt.get('y'):.1f})"
        elif c.mode == "move" and tgt:
            gx = tgt["x0"] + tgt["dist"] * math.cos(tgt["th"])
            gy = tgt["y0"] + tgt["dist"] * math.sin(tgt["th"])
            label = f"move {tgt['dist']:+.2f} m"
        if gx is not None:
            self.goal.set_data([gx], [gy])
            self.goal_label.set_position((gx + 0.12, gy + 0.12))
            self.goal_label.set_text(label)
        else:
            self.goal.set_data([], [])
            self.goal_label.set_text("")

        # side panel
        silent = time.monotonic() - srv.last_rx
        front = min(sonar[i] for i in (2, 3, 4, 5))
        self.title.set_text(f"Teleoperated Pioneer P3-DX  -  live simulation ({be.name} backend)"
                            + (f"  -  {self.title_extra}" if self.title_extra else ""))
        self.panel_text.set_text(
            "ROBOT\n"
            f"  x      {x:+7.3f} m\n"
            f"  y      {y:+7.3f} m\n"
            f"  theta  {math.degrees(th):+7.1f} deg\n"
            f"  v      {srv.v:+7.2f} m/s\n"
            f"  w      {math.degrees(srv.w):+7.1f} deg/s\n"
            f"  mode   {c.mode}\n"
            f"  front obstacle {front:4.2f} m\n\n"
            "LINK\n"
            f"  last message  {silent:4.1f} s ago\n"
            f"  commands {srv.stats['cmds']:4d}  stale {srv.stats['stale']:3d}\n"
            f"  watchdog trips {srv.stats['link_lost']:3d}\n"
            f"  sim time {srv.sim_time:7.1f} s")
        self.state_badge.set_text(f" {state} ")
        self.state_badge.get_bbox_patch().set_facecolor(colour)
        self.log_text.set_text("RECENT EVENTS\n" + "\n".join(
            f"  {line}" for line in list(srv.event_log)[-9:]))
        return []

    def show(self):
        self.anim = FuncAnimation(self.fig, self._update, interval=1000 // self.fps, cache_frame_data=False)
        plt.show()
