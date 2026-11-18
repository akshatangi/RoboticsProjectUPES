# How to run (step by step)

Owner: **Harsh Varma**. Every command here was run on Linux (Ubuntu 24.04, Python 3.12). The outputs
pasted below are real. Windows and macOS use the same Python commands; only the setup lines differ,
as marked.

Contents
1. Install (Windows / Linux / macOS)
2. Demo A: mock robot over TCP (two terminals)
3. Demo B: mock robot over MQTT (broker + two terminals)
4. Demo C: through the impairment proxy (delay / loss)
5. Demo D: CoppeliaSim (to be verified by the team)
6. Tests
7. Experiments, tables and figures
8. Where every output is saved

---

## 1. Install

You need **Python 3.10 or newer**. Check with `python --version` (Windows) or `python3 --version`.

**Linux / macOS**
```bash
cd <project folder>
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
cd <project folder>
py -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
```

All later commands assume the virtual environment is active (your prompt starts with `(.venv)`).
On Windows, type `python` wherever this guide says `python`.

> **ROS users:** if `pytest` fails with `No module named 'lark'`, your shell has ROS on `PYTHONPATH`.
> Run `unset PYTHONPATH` (Linux) first, or open a terminal without ROS sourced.

---

## 2. Demo A: mock robot over TCP (two terminals)

**Terminal 1: robot**
```bash
python -m teleop.server --backend mock --transport tcp --port 9000
```
Expected:
```
Robot server ready: backend=mock transport=tcp (listening on 0.0.0.0:9000). Ctrl+C to stop.
```

**Terminal 2: operator**
```bash
python -m teleop.cli --transport tcp --host 127.0.0.1 --port 9000
```
Type the commands at the `teleop>` prompt. The same session can be run non-interactively with `-c`.
This is the real output of
`python -m teleop.cli --transport tcp --host 127.0.0.1 --port 9000 -c "ping; move 1 0.3; wait; turn 90; wait; goto 1 1; wait; status"`:
```
Connected via tcp to 127.0.0.1:9000
teleop> ping
  <- pong #1 rtt=0.3 ms
teleop> move 1 0.3
  <- ack #2 move ok (40.1 ms)
teleop> wait
  <- result #2 move: reached after 4.45 s, final error 0.025 m
teleop> turn 90
  <- ack #3 turn ok (50.2 ms)
teleop> wait
  <- result #3 turn: reached after 2.30 s, final error 0.950 deg
teleop> goto 1 1
  <- ack #4 goto ok (49.5 ms)
teleop> wait
  <- result #4 goto: reached after 4.45 s, final error 0.027 m
teleop> status
  pose x=+0.999 m  y=+0.974 m  th= +88.64 deg | v=+0.00 m/s w=+0.00 rad/s | IDLE      mode=idle  obstacle=1.00 m
```
Notes:
* The `ack` time (~40-50 ms) includes waiting for the next 50 ms control tick. `ping` is answered
  at once, so it shows the pure network round trip.
* **Ctrl+C in the shell is an emergency stop**, not exit. Leave with `quit`.
* When the operator leaves, the robot stops by itself within 1 s (watchdog).

**Safety demo** (same two terminals): `teleop> macro macros/safety_demo.tlm` drives at the box in front
of the start pose without ever sending `stop`. Real output (rows of `watch` shortened):
```
teleop> reset
  <- ack #1 reset ok (9.4 ms)
teleop> vel 0.5 0
  <- ack #2 vel ok (50.1 ms)
teleop> watch 12
  pose x=+2.883 m ... v=+0.48 m/s ... MOVING    mode=vel   obstacle=0.78 m
  pose x=+3.077 m ... v=+0.28 m/s ... MOVING    mode=vel   obstacle=0.58 m
  pose x=+3.254 m ... v=+0.09 m/s ... MOVING    mode=vel   obstacle=0.39 m
  pose x=+3.341 m ... v=+0.05 m/s ... MOVING    mode=vel   obstacle=0.30 m
  pose x=+3.344 m ... v=+0.00 m/s ... OBSTACLE  mode=vel   obstacle=0.30 m
  pose x=+3.344 m ... v=+0.00 m/s ... OBSTACLE  mode=vel   obstacle=0.31 m
teleop> status
  pose x=+3.344 m  y=+0.000 m  th=  +0.00 deg | v=+0.00 m/s w=+0.00 rad/s | OBSTACLE  mode=vel   obstacle=0.29 m
```
The robot slows down from 0.8 m and stops at the 0.30 m line, and it stays stopped even though `vel 0.5`
is still active.

### Live simulation window (for the demo video)

Add `--gui` to the robot command to open a window that shows the robot moving in the room. It shows the
sonar rays, the path driven so far, the current goal, the robot's state colour (grey IDLE, blue MOVING,
orange OBSTACLE, red LINK_LOST) and a log of the commands received:
```bash
python -m teleop.server --backend mock --transport tcp --port 9000 --gui      # terminal 1
python -m teleop.cli --port 9000 --script macros/video_demo.tlm              # terminal 2 (about 1.5 min)
```
`--gui` works with `--transport mqtt` too. Closing the window stops the robot server. Record the screen
with any recorder: Ubuntu/GNOME **Ctrl+Shift+Alt+R** (saved in ~/Videos/Screencasts), Windows
**Win+Alt+R** (Xbox Game Bar), macOS **Cmd+Shift+5**, or OBS Studio. In the team video meeting you simply
share this window.

---

## 3. Demo B: mock robot over MQTT

### 3.1 Start a Mosquitto broker
Full instructions are in [MQTT_SETUP.md](MQTT_SETUP.md). In short:

| OS | Install | Start (from the project folder) |
|---|---|---|
| Ubuntu/Debian | `sudo apt install mosquitto` | `mosquitto -c config/mosquitto.conf -v` |
| Linux, no sudo | `tools/mosquitto/` helper (see MQTT_SETUP.md) | `tools/mosquitto/run_mosquitto.sh 1883` |
| macOS | `brew install mosquitto` | `mosquitto -c config/mosquitto.conf -v` |
| Windows | installer from mosquitto.org (`C:\Program Files\mosquitto`) | `"C:\Program Files\mosquitto\mosquitto.exe" -c config\mosquitto.conf -v` |

On Ubuntu the apt package also starts a system broker on port 1883. Stop it first
(`sudo systemctl stop mosquitto`), or use another port in both the config and the commands.

### 3.2 Robot and operator
```bash
# terminal 2: robot
python -m teleop.server --backend mock --transport mqtt --host 127.0.0.1 --port 1883 --qos 1
# terminal 3: operator
python -m teleop.cli --transport mqtt --host 127.0.0.1 --port 1883 --qos 1
```
Expected robot line:
```
Robot server ready: backend=mock transport=mqtt (broker 127.0.0.1:1883, topics teleop/p3dx/#, QoS 1). Ctrl+C to stop.
```
Real output of `python -m teleop.cli --transport mqtt --host 127.0.0.1 --port 1883 --qos 1 -c "ping; move 1 0.3; wait; status; rtt 10"`:
```
Connected via mqtt to 127.0.0.1:1883 (robot 'p3dx', QoS 1)
teleop> ping
  <- pong #1 rtt=0.9 ms
teleop> move 1 0.3
  <- ack #2 move ok (51.7 ms)
teleop> wait
  <- result #2 move: reached after 4.45 s, final error 0.025 m
teleop> status
  pose x=+0.977 m  y=+0.000 m  th=  +0.00 deg | v=+0.00 m/s w=+0.00 rad/s | IDLE      mode=idle  obstacle=1.00 m
teleop> rtt 10
  10/10 replies  min 1.3  mean 1.4  max 1.6 ms
```
Use `--qos 0` on **both** sides to compare. Use `--robot-id NAME` on both sides to drive one of several robots.
Watch the raw traffic with `mosquitto_sub -h 127.0.0.1 -t 'teleop/#' -v`.

---

## 4. Demo C: through the impairment proxy

The proxy sits between operator and robot (TCP) or between operator and broker (MQTT):
```bash
# TCP: robot on 9000 (Demo A), proxy on 9001 adding 100 ms each way, 25 ms jitter, 1 % loss
python -m teleop.netem --listen 9001 --target 127.0.0.1:9000 --delay 100 --jitter 25 --loss 0.01
python -m teleop.cli --transport tcp --port 9001
teleop> rtt 20

# MQTT: proxy in front of the broker
python -m teleop.netem --listen 1890 --target 127.0.0.1:1883 --delay 100 --jitter 25 --loss 0.01
python -m teleop.cli --transport mqtt --port 1890 --qos 1
```
Real output (TCP case):
```
Impairment proxy 127.0.0.1:9001 -> 127.0.0.1:9000  [100ms+-25 loss 1%]  Ctrl+C to stop
Connected via tcp to 127.0.0.1:9001
teleop> rtt 20
  20/20 replies  min 172.2  mean 219.3  max 271.6 ms
```
The RTT is about twice the one-way delay, plus occasional retransmission timeouts.

---

## 5. Demo D: CoppeliaSim (the real simulator, for the video)

Run on CoppeliaSim Edu 4.10 (Ubuntu 24.04): move, turn, goto, the sonar safety stop, reset, the watchdog
and `macros/video_demo.tlm` all work.

**1. Install CoppeliaSim Edu** (free for students) from https://www.coppeliarobotics.com/downloads
* Linux: download the `.tar.xz` for your Ubuntu version and unpack it, for example into `~/CoppeliaSim`:
  `mkdir -p ~/CoppeliaSim && tar xJf CoppeliaSim_Edu_*_Ubuntu24_04.tar.xz -C ~/CoppeliaSim`
* Windows: run the installer. macOS: open the `.dmg` and drag the app to Applications.

**2. Start CoppeliaSim** and leave it open. Do **not** press Play; our server starts the simulation.
```bash
~/CoppeliaSim/CoppeliaSim_Edu_V4_10_0_rev0_Ubuntu24_04/coppeliaSim.sh    # Linux
```
(Windows: Start menu → CoppeliaSim Edu. macOS: open coppeliaSim.app.)

**3. Start the robot server with the CoppeliaSim backend.** If no robot is open, it loads
`scenes/teleop_p3dx.ttt` by itself (the P3-DX in the same room as the mock):
```bash
python -m teleop.server --backend coppelia --transport tcp --port 9000
```
**4. Drive it** exactly as in Demo A or B, or run the video demo (about 1 minute):
```bash
python -m teleop.cli --port 9000 --script macros/video_demo.tlm
```
Real result on CoppeliaSim 4.10: every goto reached within 2.9 cm, `turn 90` within 1.1°, and the robot
stopped 0.30 m in front of the box with the state OBSTACLE.

**5. Record** the CoppeliaSim window (Ubuntu: Ctrl+Shift+Alt+R; Windows: Win+Alt+R; macOS: Cmd+Shift+5),
or share it in the team meeting. Stop the server with Ctrl+C. It stops the simulation cleanly, so you can
start it again straight away.

Notes:
* To rebuild the scene (for example after changing the room), open an empty scene in CoppeliaSim and run
  `python scenes/build_scene.py`.
* Do not open the scene with `coppeliaSim.sh -f "<path>"`: CoppeliaSim 4.10 cannot handle the space in
  "Robotics project". Let the server load it, or use *File → Open scene* in CoppeliaSim.
* `--gui` also works with `--backend coppelia`. It shows the same robot from above, next to the 3-D view.

---

## 6. Tests

```bash
python -m pytest                # all tests; MQTT ones skip if no broker on 127.0.0.1:1883
python -m pytest -v tests/test_mqtt.py     # with a broker running
MQTT_PORT=1884 python -m pytest            # broker on another port (Windows: set MQTT_PORT=1884)
```
Real result on the development machine with a broker running: `68 passed`.

---

## 7. Experiments, tables and figures

```bash
# brokers: 1883 WITH set_tcp_nodelay (main runs), 1885 WITHOUT it (Nagle ablation S0 only)
mosquitto -c config/mosquitto.conf                # or tools/mosquitto/run_mosquitto.sh 1883 true
tools/mosquitto/run_mosquitto.sh 1885 false        # Linux helper; elsewhere copy the config, drop set_tcp_nodelay, port 1885

python experiments/run_experiments.py --trials 10 --workers 12     # about 15-20 min
python experiments/pid_tuning.py                                   # a few seconds, no network
python experiments/analyze.py                                      # tables + figures
python scripts/diagrams.py                                         # architecture/sequence/flow diagrams
```
For a quick look use `--scenarios S1_latency --trials 2`.

---

## 8. Where every output is saved

| What | Where |
|---|---|
| Shell history | `~/.teleop_history` |
| Telemetry log (`log start f.csv`) | the file you name, relative to the current folder |
| Raw experiment rows (one per trial) | `results/raw/S*_*.csv`, per-ping samples in `results/raw/S1_latency_samples.csv` |
| Trajectories of trial 0 | `results/traces/*.csv` |
| Summary tables (CSV + Markdown) | `results/tables/T_*.csv`, `T_*.md` |
| Figures | `results/figures/fig_*.png` (measurements), `diag_*.png` (drawings) |
| Run metadata (dates, backend, conditions) | `results/run_info.json`; all summary numbers: `results/summary.json` |
