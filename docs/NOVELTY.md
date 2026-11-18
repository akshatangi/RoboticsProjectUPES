# Novelty notes (report Section 4)

Owner: **Aniket Singh Bisht**. Each point is backed by a measured result. All numbers are from the mock
backend (see [RESULTS.md](RESULTS.md)).

| # | What is new | Compared with | Evidence |
|---|---|---|---|
| 1 | **One robot stack, three transports, one impairment model.** TCP, MQTT QoS 0 and MQTT QoS 1 drive the *same* server, controller and safety layer through the *same* reproducible delay/jitter/loss/outage proxy. The comparison covers task outcomes (goal time, tracking error, commands lost or replayed), not only latency. | Typical MQTT-versus-TCP comparisons measure message latency or throughput alone, without a robot task. | S1-S5: 550 trials, 10 per cell |
| 2 | **A measured Nagle pitfall for robot MQTT.** paho-mqtt never sets `TCP_NODELAY`, and Mosquitto defaults to `set_tcp_nodelay false`. Together they add about 40-55 ms to every QoS 1 round trip, even on one machine. Fixing one side is not enough. | Default installs of paho and Mosquitto | S0: 55.2 ± 7.3 ms (defaults), 41.7 / 41.8 ms (one side fixed), 1.2 ± 0.1 ms (both fixed) |
| 3 | **"At-least-once" is unsafe for motion without a staleness guard.** After a 3 s outage, QoS 1 delivered all 150 queued `vel` commands. The robot's age check rejected 125 of them, and only the 25 sent in the last second ran. TCP and QoS 0 simply lost them. | Treating QoS 1 as "more reliable, therefore better" for teleoperation | S4 table: lost 150 / 150 / 0; rejected stale 0 / 0 / 125 |
| 4 | **Supervisory versus direct control under identical impairments, with an operator-in-the-loop model.** `goto` keeps its 2.7 cm accuracy and finishes all 480 goals at C3 (only 10-18 % slower). Pure-pursuit steering with `vel` degrades about 5× in tracking error, and only 2-8 of 10 runs finish. | Teleoperation studies usually test one control mode | S2 vs S3 |
| 5 | **Network-independent on-robot safety, verified across transports.** The obstacle guard (with hysteresis against sonar chatter) and the 1 s watchdog give the same behaviour for TCP, QoS 0 and QoS 1. | Safety that relies on the operator pressing stop | S5: 0 collisions, stop at 28.9-30.2 cm; S4: stop after 1.0-1.1 s, about 25 cm coast; 0 collisions in all 550 trials |

**Honest limits** (also in the report): mock backend only; the operator is a model; loss is emulated as
TCP retransmission; single PC.
