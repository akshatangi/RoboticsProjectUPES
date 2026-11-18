# Protocol

Owner: **Harsh Varma** (grammar, JSON, TCP framing). **Aniket Singh Bisht** owns the MQTT topic mapping.

## 1. Command grammar (what the operator types)

```
command  := name { SP number }
name     := move | turn | goto | vel | stop | status | ping | reset
```

| Command | Arguments (defaults) | Units | Finishes with a `result`? |
|---|---|---|---|
| `move` | `dist` `[speed=0.3]` | m, m/s | yes |
| `turn` | `angle` `[rate=60]` | deg (+ = left), deg/s | yes |
| `goto` | `x` `y` `[speed=0.3]` | m (world frame), m/s | yes |
| `vel` | `v` `w` | m/s, deg/s | no (held until replaced or stopped) |
| `stop`, `status`, `ping`, `reset` | none | | no |

Rules: names are case-insensitive. Every argument must be a finite number. `speed` and `rate` must be
positive. Too many arguments is an error. The robot additionally clamps every value to the limits in
`teleop/config.py` (max 0.7 m/s forward, 0.2 m/s reverse, 2 rad/s turn).

A new motion command **pre-empts** the running one. The old goal gets `outcome: "preempted"`.

## 2. Messages (JSON)

TCP: one JSON object per line (`\n`-terminated, UTF-8, at most 64 KiB). MQTT: one object per payload.

### operator → robot
```json
{"type":"cmd","seq":7,"sid":"3fa2c1d0","t":1794662500.123,"cmd":"goto","args":{"x":1.0,"y":1.0,"speed":0.3}}
{"type":"hb","t":1794662500.373}
```
* `seq`: per-operator counter, so every reply can be matched to its command.
* `sid`: random session id, chosen when the operator starts. The robot runs each (sid, seq) **once**.
  A second copy (MQTT QoS 1 may deliver twice) is acknowledged with `"err":"duplicate ignored"`.
* `t`: sender wall-clock time (s). The robot rejects **motion** commands older than 1.0 s
  (`max_command_age`). `stop` is never rejected.
* `hb`: heartbeat, 4 per second. Any message resets the robot's 1.0 s watchdog.

### robot → operator
```json
{"type":"ack","seq":7,"ok":true,"err":null,"t_cmd":1794662500.123}
{"type":"ack","seq":8,"ok":false,"err":"stale: command is 3.21 s old"}
{"type":"pong","seq":9,"t_cmd":1794662500.5}
{"type":"result","seq":7,"cmd":"goto","outcome":"reached","duration":4.45,"error":0.027}
{"type":"telem","t":1794662501.0,"n":412,"pose":[0.999,0.974,1.547],"v":0.0,"w":0.0,
 "state":"IDLE","mode":"idle","active":null,"obstacle":1.0}
{"type":"error","err":"robot busy: another operator has control"}
```
`outcome` is one of `reached`, `stopped`, `preempted`, `blocked` (obstacle for more than 2 s),
`link_lost`, or `timeout`. `error` is metres, or degrees for `turn`.
`state` is one of `IDLE`, `MOVING`, `OBSTACLE`, `LINK_LOST`.

## 3. TCP specifics
* Robot listens on port 9000. `TCP_NODELAY` is set on both ends.
* **Exclusive control:** a second operator is refused with an `error` message while the first has
  sent something in the last 1.0 s.
* The operator reconnects automatically every 0.25 s after a drop. Messages sent while disconnected
  are reported as "not sent".

## 4. MQTT specifics

| Topic | Direction | QoS | Retained |
|---|---|---|---|
| `teleop/<id>/cmd` | operator → robot | chosen (0/1) | no |
| `teleop/<id>/telem` | robot → operator | chosen | no |
| `teleop/<id>/event` | robot → operator (ack, pong, result) | chosen | no |
| `teleop/<id>/status` | robot `online`/`offline` (Last Will) | 1 | yes |
| `teleop/<id>/operator` | operator `online`/`offline` (Last Will) | 1 | yes |

* QoS 1 uses a persistent session (`clean_session=False`), so messages survive a reconnect. QoS 0 uses
  a clean session.
* When the operator's Last Will (`offline`) arrives, the robot stops at once.
* Keepalive is 5 s by default (2 s in the experiments). `TCP_NODELAY` is set on paho's socket. The
  broker needs `set_tcp_nodelay true` (see MQTT_SETUP.md for the measured effect).

## 5. Validation on the robot
`protocol.validate_cmd()` re-uses the operator's parser, so both sides apply the same rules. Malformed
JSON, unknown commands, missing or non-numeric arguments and a non-integer `seq` are answered with
`ok:false` and never reach the controller (tests: `tests/test_protocol.py`, `test_system_tcp.py`).
