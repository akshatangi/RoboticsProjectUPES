"""Draw the explanatory diagrams used in the report and docs (matplotlib only).

    python report/diagrams.py     -> results/figures/diag_*.png

These are drawings of the design, not measurements.
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.path.join(ROOT, "results", "figures")
INK, INK2 = "#0b0b0b", "#52514e"
FILL = {"op": "#dbe8f8", "net": "#fde3d7", "robot": "#d3f0e4", "sim": "#f3f2ee"}

plt.rcParams.update({"font.family": "serif",
                     "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
                     "font.size": 9, "savefig.dpi": 220, "savefig.bbox": "tight"})


def box(ax, x, y, w, h, text, fill="#ffffff", bold=False, size=7.0):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                facecolor=fill, edgecolor=INK2, linewidth=0.9))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color=INK,
            fontweight="bold" if bold else "normal")


def arrow(ax, x1, y1, x2, y2, text="", both=False, style="-", offset=(0, 0.08), size=6.5):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="<|-|>" if both else "-|>",
                                 mutation_scale=9, color=INK2, linewidth=1.0, linestyle=style,
                                 shrinkA=1, shrinkB=1))
    if text:
        ax.text((x1 + x2) / 2 + offset[0], (y1 + y2) / 2 + offset[1], text, ha="center",
                va="bottom", fontsize=size, color=INK2)


def canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w * 2)
    ax.set_ylim(0, h * 2)
    ax.axis("off")
    return fig, ax


def architecture():
    fig, ax = canvas(6.6, 3.6)
    # zones
    for x, w, lab, f in ((0.1, 3.4, "Operator PC", "op"), (3.7, 2.9, "Network", "net"),
                         (6.8, 6.3, "Robot side", "robot")):
        ax.add_patch(FancyBboxPatch((x, 0.15), w, 6.9, boxstyle="round,pad=0.02,rounding_size=0.15",
                                    facecolor=FILL[f], edgecolor="none", alpha=0.55))
        ax.text(x + w / 2, 6.8, lab, ha="center", va="top", fontsize=9.5, fontweight="bold", color=INK)
    box(ax, 0.35, 5.0, 2.9, 1.1, "Operator shell\ncli.py (history, macros,\nwait, watch, log)")
    box(ax, 0.35, 3.3, 2.9, 1.1, "OperatorClient\nclient.py (seq, acks,\nresults, heartbeat 4 Hz)")
    box(ax, 0.35, 1.6, 2.9, 1.1, "protocol.py\ncommand parser +\nJSON messages")
    arrow(ax, 1.8, 5.0, 1.8, 4.4)
    arrow(ax, 1.8, 3.3, 1.8, 2.7)
    box(ax, 3.9, 4.5, 2.5, 1.2, "Impairment proxy\nnetem.py: delay, jitter,\nloss, outage", fill="#ffffff")
    box(ax, 3.9, 2.0, 2.5, 1.3, "Mosquitto broker\n(MQTT QoS 0 / 1,\nretained status, LWT)", fill="#ffffff")
    arrow(ax, 3.25, 3.85, 3.9, 5.0, "", both=True)
    arrow(ax, 5.15, 4.5, 5.15, 3.3, "mqtt", both=True, offset=(0.45, 0.15))
    box(ax, 7.0, 5.0, 2.8, 1.1, "Transport server\nTcpServer / MqttServer")
    arrow(ax, 6.4, 5.3, 7.0, 5.5, "tcp", both=True, offset=(0, 0.02))
    arrow(ax, 6.4, 2.7, 7.3, 5.0, "", both=True)
    box(ax, 7.0, 3.3, 2.8, 1.1, "RobotServer loop\nserver.py, 20 Hz\n(watchdog, stale guard)", bold=False)
    arrow(ax, 8.4, 5.0, 8.4, 4.4, "commands", offset=(0.55, -0.15))
    box(ax, 10.1, 5.0, 2.8, 1.1, "MotionController\ncontroller.py\nmove·turn·goto·vel + PID")
    box(ax, 10.1, 3.3, 2.8, 1.1, "SafetyLayer\nsafety.py\nobstacle stop / slow-down")
    arrow(ax, 9.8, 3.95, 10.1, 5.3)
    arrow(ax, 11.5, 5.0, 11.5, 4.4, "(v, ω)", offset=(0.3, -0.15))
    box(ax, 7.0, 0.5, 5.9, 1.3, "Robot backend (backends/)\nMockBackend: pure-Python P3-DX + room\nCoppeliaBackend: CoppeliaSim ZMQ Remote API", fill=FILL["sim"])
    arrow(ax, 11.5, 3.3, 11.5, 1.8, "wheel speeds", offset=(0.75, -0.2))
    arrow(ax, 8.4, 1.8, 8.4, 3.3, "pose, 16 sonars", offset=(-0.8, -0.2))
    arrow(ax, 7.0, 3.6, 3.25, 3.6, "", style="--")
    ax.text(5.15, 3.5, "ack · pong · result · telem 10 Hz", fontsize=6.3, color=INK2, ha="center",
            va="top")
    fig.savefig(os.path.join(FIG, "diag_architecture.png"))
    plt.close(fig)


def sequence():
    fig, ax = canvas(6.4, 3.9)
    cols = {"Operator": 1.3, "Proxy / broker": 4.9, "Robot server": 8.5, "Robot": 11.4}
    for name, x in cols.items():
        box(ax, x - 1.0, 7.0, 2.0, 0.6, name, fill="#ffffff", bold=True)
        ax.plot([x, x], [0.2, 7.0], color=INK2, linewidth=0.8, linestyle=(0, (3, 3)))
    y = 6.5

    def msg(a, b, text, dy=0.55, dashed=False):
        nonlocal y
        arrow(ax, cols[a], y, cols[b], y, text, style="--" if dashed else "-", offset=(0, 0.04))
        y -= dy

    msg("Operator", "Proxy / broker", 'cmd {"seq":7,"cmd":"goto","t":...}')
    msg("Proxy / broker", "Robot server", "+ delay / jitter / RTO")
    ax.text(cols["Robot server"] + 0.15, y + 0.1, "validate · stale? · start", fontsize=7, color=INK2)
    msg("Robot server", "Proxy / broker", 'ack {"seq":7,"ok":true}', dashed=True)
    msg("Proxy / broker", "Operator", "ack  (RTT measured here)", dashed=True)
    for _ in range(2):
        msg("Robot server", "Robot", "wheel speeds", dy=0.4)
        msg("Robot", "Robot server", "pose, sonars", dy=0.4, dashed=True)
    msg("Robot server", "Operator", "telem 10 Hz: pose, state, obstacle", dashed=True)
    msg("Operator", "Robot server", "hb every 0.25 s (watchdog)", dy=0.5)
    msg("Robot server", "Operator", 'result {"seq":7,"outcome":"reached"}', dashed=True)
    fig.savefig(os.path.join(FIG, "diag_sequence.png"))
    plt.close(fig)


def control_flow():
    fig, ax = canvas(4.6, 5.4)
    steps = ["Take queued commands → validate → stale? → ack",
             "Watchdog: silent > 1 s ?  → stop, LINK_LOST",
             "Read pose (x, y, θ) and 16 sonars",
             "Controller: mode → (v, ω)   [PID on heading]",
             "Safety: slow < 0.8 m, block forward < 0.3 m",
             "Ramp v, ω; convert to wheel speeds; saturate",
             "Backend step (mock physics / sim.step())",
             "Every 2nd tick: send telemetry; send results"]
    y = 9.9
    for i, s in enumerate(steps):
        box(ax, 0.3, y - 0.85, 7.0, 0.85, f"{i + 1}. {s}", fill=FILL["robot"] if i in (1, 4) else "#ffffff",
            size=7.5)
        if i < len(steps) - 1:
            arrow(ax, 3.8, y - 0.85, 3.8, y - 1.2)
        y -= 1.2
    xr = 8.0
    ax.plot([7.3, xr, xr], [y + 0.78, y + 0.78, 9.47], color=INK2, linewidth=1.0)
    arrow(ax, xr, 9.47, 7.3, 9.47)
    ax.text(xr + 0.15, 5.5, "next tick\nevery 50 ms\n(20 Hz)", fontsize=7.5, color=INK2, ha="left", va="center")
    fig.savefig(os.path.join(FIG, "diag_control_loop.png"))
    plt.close(fig)


def state_machine():
    fig, ax = canvas(6.0, 2.9)
    pos = {"IDLE": (0.4, 2.4), "MOVING": (4.6, 2.4), "OBSTACLE": (9.0, 4.4), "LINK_LOST": (9.0, 0.4)}
    for s_, (x, y) in pos.items():
        box(ax, x, y, 2.3, 0.9, s_, fill=FILL["robot"] if s_ != "LINK_LOST" else FILL["net"], bold=True)
    arrow(ax, 2.7, 3.05, 4.6, 3.05, "move/turn/goto/vel", offset=(0, 0.05))
    arrow(ax, 4.6, 2.65, 2.7, 2.65, "reached / stop", offset=(0, -0.42))
    arrow(ax, 6.9, 3.2, 9.0, 4.75, "front < 0.30 m", offset=(-0.75, 0.15))
    arrow(ax, 9.0, 4.5, 6.9, 3.0, "clear / turn away", offset=(0.95, -0.55))
    arrow(ax, 6.9, 2.5, 9.0, 0.95, "no message > 1 s\nor operator LWT", offset=(0.95, 0.05))
    ax.plot([9.0, 1.55], [0.6, 0.6], color=INK2, linewidth=1.0, linestyle="--")
    arrow(ax, 1.55, 0.6, 1.55, 2.4, style="--")
    ax.text(5.0, 0.45, "messages flow again → IDLE (robot stays stopped until a new command)",
            fontsize=6.5, color=INK2, ha="center", va="top")
    ax.text(10.15, 5.45, "blocked > 2 s: goal aborted", fontsize=6.5, color=INK2, ha="center")
    fig.savefig(os.path.join(FIG, "diag_states.png"))
    plt.close(fig)


def main():
    os.makedirs(FIG, exist_ok=True)
    architecture()
    sequence()
    control_flow()
    state_machine()
    print("diagrams written to", FIG)


if __name__ == "__main__":
    main()
