# Design and Implementation Plan

**Project:** Networked Teleoperation of a Robot through Shell Commands
**Course:** CSAI4014 Algorithms for Intelligent Systems and Robotics, UPES, B.Tech CSE (AI & ML), Semester VII, Batch B3-B4
**Team:** Akshat Kumar Angi, Harsh Varma, Aniket Singh Bisht, Priyam Paliwal, Yeshang Soni

This document fixes the structure of the system, who owns which part, the interfaces between the parts, the safety design, the order in which the parts are implemented, and how they are tested. It contains no results. Results are produced by the experiments and are reported in `docs/RESULTS.md` and in the report.

## 1. Goal and scope

An operator types shell commands in a terminal. The commands travel over a network (a TCP socket, or MQTT with QoS 0 or QoS 1 through a Mosquitto broker) to a simulated Pioneer P3-DX differential-drive robot. The robot executes them with PID control, protects itself with an on-board safety layer, and sends telemetry back.

The study compares TCP, MQTT QoS 0 and MQTT QoS 1 under emulated delay, jitter, packet loss and link outages. It also includes an operator-in-the-loop steering test that uses a synthetic driver model.

Course topics covered: Decision-Control Hierarchy, Open/Closed-Loop Control, Stability, Software Architectures.

Out of scope: real hardware, vision, multi-robot control, more than one operator at a time.

## 2. Architecture

```
 operator shell --TCP or MQTT--> [impairment proxy] --> robot server (20 Hz) --> mock P3-DX / CoppeliaSim
      ^                                                    | controller -> safety -> wheels
      +------------ ack, result, telemetry (10 Hz) <-------+
```

Layers (decision-control hierarchy):
- Operator intent: shell commands (`move`, `turn`, `goto`, `vel`, `stop`, `status`, `ping`, `reset`).
- Supervisory: the go-to-goal logic and heading control on the robot, and the safety layer that can override any command.
- Low level: wheel velocities from differential-drive kinematics, executed by the backend.

The robot is reached only through a backend interface, so the same server runs on the pure-Python mock backend and on CoppeliaSim.

## 3. Requirements

Functional:
- Commands: `move <dist> [speed]`, `turn <deg> [rate]`, `goto <x> <y> [speed]`, `vel <v> <w>`, `stop`, `status`, `ping`, `reset`.
- Shell-only helpers: `wait`, `watch`, `rtt`, `log`, `macro`, `history`, `help`, `quit`.
- Every motion command is acknowledged, and a result message follows when it finishes.
- Telemetry at 10 Hz: pose, state, obstacle distance, goal result.
- Two interchangeable transports (TCP and MQTT) behind one transport interface.

Safety:
- Sonar obstacle stop: the robot halts in front of an obstacle even if no stop is sent.
- Link-loss watchdog: no messages for about one second puts the robot into a link-lost stop.
- Stale-command guard: commands older than a configurable age are rejected.
- Single operator: a second operator is refused while one has control.
- MQTT Last Will so the broker announces a dead link.

Non-functional:
- All tunable numbers live in one configuration module.
- Everything runs without CoppeliaSim (mock backend) and works on Windows, Linux and macOS.
- Every experiment result is labelled with the backend it came from.

## 4. Modules and ownership

| Module | Files | Owner | Responsibility |
|---|---|---|---|
| Protocol | `teleop/protocol.py` | Harsh | Command parser and JSON message format |
| Operator side | `teleop/client.py`, `teleop/cli.py`, `teleop/transport/tcp.py` | Harsh | Client API, interactive shell, TCP transport |
| MQTT | `teleop/transport/mqtt.py`, `config/mosquitto.conf` | Aniket | MQTT transport, QoS, Last Will, TCP_NODELAY |
| Server | `teleop/server.py` | Akshat | Robot-side 20 Hz loop |
| Backends | `teleop/backends/mock.py`, `teleop/backends/coppelia.py` | Akshat | Mock P3-DX and room simulator; CoppeliaSim ZMQ backend |
| Control | `teleop/kinematics.py`, `teleop/pid.py`, `teleop/controller.py` | Priyam | Differential-drive kinematics, PID, move/turn/goto |
| Safety | `teleop/safety.py` | Priyam | Obstacle stop, watchdog, stale-command guard |
| Network impairment | `teleop/netem.py` | Yeshang | Delay, jitter, loss and outage proxy |
| Experiments | `experiments/` | Yeshang (S0 by Aniket) | Scenarios, runner, metrics, analysis, PID tuning |
| Configuration | `teleop/config.py` | shared | Every tunable number |
| Report and docs | `report/`, `docs/` | shared | Report builder, run guides, per-member guides |

## 5. Interfaces

- **Transport:** a transport sends and receives protocol messages; TCP and MQTT implement the same interface, so the shell and the server do not know which one is in use.
- **Backend:** the server sets wheel or body velocities and reads pose and sonar distance through a backend; the mock and CoppeliaSim backends are interchangeable.
- **Controller:** given the current pose and the active command, the controller returns the velocity to apply; the safety layer then gets the final say before the velocity reaches the backend.
- **Wire format:** JSON messages as described in `docs/PROTOCOL.md`.

## 6. Control design

- Kinematics: the unicycle model, with wheel speeds derived from forward speed `v` and turn rate `w` and the wheel separation of the P3-DX.
- PID loops for distance, heading and speed; gains are chosen in the tuning study (`experiments/pid_tuning.py`) and stored in the configuration module.
- `goto`: drive toward the target point with a heading PID and slow down near the goal.

## 7. Implementation order

Each step ends with a check that must pass before the next one starts.

| Step | Work | Owner | Done when |
|---|---|---|---|
| 0 | This document, README, `requirements.txt`, `.gitignore` | repo owner | repo installs cleanly |
| 1 | Protocol: command parser and message format | Harsh | parser tests pass |
| 2 | TCP transport, client, shell | Harsh | `ping` works over TCP against a stub |
| 3 | Mock backend and kinematics | Akshat, Priyam | straight-line and rotation tests pass |
| 4 | Server loop, PID, `move`, `turn`, `vel` | Akshat, Priyam | commands reach their targets within tolerance |
| 5 | `goto`, safety layer, tuning | Priyam | robot stops at an obstacle and on link loss |
| 6 | MQTT transport and broker configuration | Aniket | same shell session works over MQTT QoS 0 and 1 |
| 7 | Impairment proxy | Yeshang | measured delay and loss match the settings |
| 8 | Experiment runner and analysis | Yeshang | tables and figures regenerate from raw data |
| 9 | CoppeliaSim backend and scene | Akshat | scene checklist in `docs/SCENE_SETUP.md` passes on a real CoppeliaSim |
| 10 | Report, docs, final checks | all | `report/check_report.py` ends with 0 FAIL |

## 8. Test and experiment plan

- Automated tests with pytest on the mock backend. MQTT tests need a Mosquitto broker and are skipped without one.
- Experiments: TCP, MQTT QoS 0 and MQTT QoS 1 under combinations of delay, jitter, loss and outage, 10 trials per cell; plus an operator-in-the-loop steering test with a synthetic driver model.
- Results are written to `results/` (raw CSVs, tables, figures) and are labelled `backend: mock` until they are repeated on CoppeliaSim.

## 9. Risks and open items

- The CoppeliaSim backend is written but has not yet been run on a real CoppeliaSim. Until it is, results come from the mock backend only and must be described that way.
- The stale-command guard compares timestamps, so operator and robot clocks must agree when they run on different machines.
- MQTT results depend on the broker configuration (Nagle on or off); the experiments use two broker settings for that reason.

## 10. Definition of done

- All automated tests pass and every experiment table and figure regenerates from the raw data.
- The shell demo works over TCP and MQTT, including the obstacle stop and link-loss stop.
- The CoppeliaSim scene checklist is completed, or the report states clearly that it was not.
- Each member can run and explain their own modules and the overall design.
