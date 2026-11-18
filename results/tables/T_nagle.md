| Broker TCP_NODELAY | Client TCP_NODELAY | Trials | Median RTT (ms, mean ± sd) | Mean of max RTT (ms) |
|---|---|---|---|---|
| off (default) | off (paho default) | 10 | 55.2 ± 7.3 | 85.3 |
| off (default) | on | 10 | 41.7 ± 0.1 | 45.9 |
| on | off (paho default) | 10 | 41.8 ± 0.3 | 43.5 |
| on | on | 10 | 1.2 ± 0.1 | 2.0 |
