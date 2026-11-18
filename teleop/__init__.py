"""Networked teleoperation of a differential-drive robot through shell commands.

Package layout (see docs/ARCHITECTURE.md for the full picture):

    protocol.py     command language + JSON message format          (Harsh)
    transport/      TCP socket and MQTT transports                   (Harsh / Aniket)
    cli.py          interactive operator shell                       (Harsh)
    client.py       operator-side API used by the shell/experiments  (Harsh)
    server.py       robot-side loop: network -> control -> robot     (Akshat)
    backends/       mock simulator and CoppeliaSim backend           (Akshat)
    kinematics.py   differential-drive maths                         (Priyam)
    pid.py          PID controller                                   (Priyam)
    controller.py   move / turn / goto / vel motion primitives       (Priyam)
    safety.py       obstacle stop, link watchdog, stale-command guard (Priyam)
    netem.py        network impairment proxy (delay, jitter, loss)   (Yeshang)
"""

__version__ = "1.0.0"
