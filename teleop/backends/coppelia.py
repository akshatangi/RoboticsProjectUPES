"""CoppeliaSim backend (ZMQ Remote API).

STATUS: run on CoppeliaSim Edu 4.10.0 (Ubuntu 24.04) with scenes/teleop_p3dx.ttt
(built by scenes/build_scene.py): move, turn, goto, sonar obstacle stop, reset,
watchdog, clean shutdown and macros/video_demo.tlm all work, and the 20 Hz loop
is held.  Two bugs found on the real simulator are fixed here: stopping in
stepping mode must keep stepping, and Ctrl+C must not interrupt a ZMQ call.
The team re-checks it on their own machines (docs/SCENE_SETUP.md, section 4).

How it works
------------
* CoppeliaSim runs the ZMQ Remote API server add-on (enabled by default,
  port 23000).  `pip install coppeliasim-zmqremoteapi-client` gives the client.
* We switch the simulation to *stepping* mode: the simulation advances one
  step (default 50 ms) only when we call sim.step().  Our server loop runs at
  20 Hz, so one server tick = one simulation step, exactly like the mock.
* The scene must contain the stock Pioneer P3-DX model with its built-in
  Braitenberg script REMOVED (otherwise that script also drives the motors).

Object paths (CoppeliaSim 4.6+ model "PioneerP3DX"):
    /PioneerP3DX                       robot base (pose)
    /PioneerP3DX/leftMotor             left wheel joint
    /PioneerP3DX/rightMotor            right wheel joint
    /PioneerP3DX/ultrasonicSensor[i]   16 sonars, i = 0..15
If your scene uses other names, pass them with --robot-path etc.
"""

from __future__ import annotations

import os
import threading
import time
from typing import List, Optional, Tuple

from ..config import RobotParams
from .base import RobotBackend

SONAR_RANGE = 1.0
DEFAULT_SCENE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "scenes", "teleop_p3dx.ttt")


class CoppeliaBackend(RobotBackend):
    name = "coppeliasim"

    def __init__(self, host: str = "localhost", port: int = 23000,
                 robot_path: str = "/PioneerP3DX", params: Optional[RobotParams] = None,
                 start_sim: bool = True, scene: Optional[str] = None):
        try:
            from coppeliasim_zmqremoteapi_client import RemoteAPIClient
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise RuntimeError("pip install coppeliasim-zmqremoteapi-client") from exc
        self.p = params or RobotParams()
        # The ZMQ client is not thread-safe; the --gui viewer reads from another thread.
        self._lock = threading.RLock()
        self.client = RemoteAPIClient(host=host, port=port)
        self.sim = self.client.require("sim")
        sim = self.sim
        if sim.getSimulationState() != sim.simulation_stopped:
            # a previous run left the simulation running: stop it cleanly first
            sim.setStepping(True)
            self._stop_and_wait()
        # Load our scene if asked to, or if the open scene has no robot (e.g. CoppeliaSim
        # was started empty).  Done through the API because the project path has a space,
        # which CoppeliaSim's own -f command-line option does not accept.
        scene = scene or (None if self._has(robot_path) else DEFAULT_SCENE)
        if scene:
            if not os.path.exists(scene):
                raise RuntimeError(f"scene not found: {scene} (build it with scenes/build_scene.py)")
            sim.loadScene(os.path.abspath(scene))
        self.robot = sim.getObject(robot_path)
        self.left = sim.getObject(robot_path + "/leftMotor")
        self.right = sim.getObject(robot_path + "/rightMotor")
        self.sonars = [sim.getObject(f"{robot_path}/ultrasonicSensor[{i}]") for i in range(16)]
        self._start_pose = sim.getObjectPose(self.robot, sim.handle_world)
        self._started_here = False
        if start_sim:
            sim.setStepping(True)
            if sim.getSimulationState() == sim.simulation_stopped:
                sim.startSimulation()
                self._started_here = True

    def _has(self, path: str) -> bool:
        try:
            self.sim.getObject(path)
            return True
        except Exception:
            return False

    def _stop_and_wait(self, timeout: float = 5.0) -> None:
        """Stop the simulation.  In stepping mode CoppeliaSim only finishes stopping
        while the client keeps stepping, so we step until the state is 'stopped'
        (waiting without stepping hangs forever - found when first run on 4.10)."""
        sim = self.sim
        sim.stopSimulation()
        deadline = time.monotonic() + timeout
        while sim.getSimulationState() != sim.simulation_stopped:
            if time.monotonic() > deadline:
                raise RuntimeError("CoppeliaSim did not stop within %.0f s" % timeout)
            sim.step()

    def _reset(self) -> None:
        sim = self.sim
        self._set_wheel_speeds(0.0, 0.0)
        # Restarting the simulation restores every object to its saved pose.
        self._stop_and_wait()
        sim.setStepping(True)
        sim.startSimulation()

    def _set_wheel_speeds(self, w_left: float, w_right: float) -> None:
        self.sim.setJointTargetVelocity(self.left, w_left)
        self.sim.setJointTargetVelocity(self.right, w_right)

    def _step(self, dt: float) -> None:
        # dt is fixed by the scene (Simulation settings -> dt = 50 ms); we just step.
        self.sim.step()

    def _get_pose(self) -> Tuple[float, float, float]:
        sim = self.sim
        x, y, _ = sim.getObjectPosition(self.robot, sim.handle_world)
        _, _, yaw = sim.getObjectOrientation(self.robot, sim.handle_world)
        return x, y, yaw

    def _get_wheel_speeds(self) -> Tuple[float, float]:
        sim = self.sim
        return (sim.getJointVelocity(self.left), sim.getJointVelocity(self.right))

    def _get_sonar(self) -> List[float]:
        out = []
        for h in self.sonars:
            res, dist, *_ = self.sim.readProximitySensor(h)
            out.append(dist if res > 0 else SONAR_RANGE)
        return out

    def close(self) -> None:
        try:
            with self._lock:
                self._set_wheel_speeds(0.0, 0.0)
                if self._started_here:
                    self._stop_and_wait()
        except Exception:
            pass

    # ------------------------------------------------------------ locked public interface
    def reset(self) -> None:
        with self._lock:
            self._reset()

    def set_wheel_speeds(self, w_left: float, w_right: float) -> None:
        with self._lock:
            self._set_wheel_speeds(w_left, w_right)

    def step(self, dt: float) -> None:
        with self._lock:
            self._step(dt)

    def get_pose(self) -> Tuple[float, float, float]:
        with self._lock:
            return self._get_pose()

    def get_wheel_speeds(self) -> Tuple[float, float]:
        with self._lock:
            return self._get_wheel_speeds()

    def get_sonar(self) -> List[float]:
        with self._lock:
            return self._get_sonar()
