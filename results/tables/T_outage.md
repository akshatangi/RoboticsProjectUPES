| Transport | Trials | Stop after outage start (s) | Coast (cm) | Cmds sent in outage | Lost | Rejected stale | Executed late | Pings answered late | Resume after link back (s) | Collisions |
|---|---|---|---|---|---|---|---|---|---|---|
| TCP socket | 10 | 1.07 ± 0.03 | 25.0 | 150 | 150 | 0 | 0 | 0/50 | 0.35 | 0 |
| MQTT QoS 0 | 10 | 1.04 ± 0.08 | 24.9 | 150 | 150 | 0 | 0 | 0/50 | 0.35 | 0 |
| MQTT QoS 1 | 10 | 1.06 ± 0.07 | 25.3 | 150 | 0 | 125 | 25 | 50/50 | 0.33 | 0 |
