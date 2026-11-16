"""CoppeliaSim backend (ZMQ Remote API).

STATUS: written against the documented CoppeliaSim 4.6+ ZMQ Remote API, but
NOT YET RUN ON A REAL COPPELIASIM.  TO BE VERIFIED ON A REAL COPPELIASIM BY
THE TEAM (Akshat) - see docs/SCENE_SETUP.md and the checklist in
docs/members/Akshat_Kumar_Angi.md.

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

from typing import List, Optional, Tuple

from ..config import RobotParams
from .base import RobotBackend

SONAR_RANGE = 1.0


class CoppeliaBackend(RobotBackend):
    name = "coppeliasim"

    def __init__(self, host: str = "localhost", port: int = 23000,
                 robot_path: str = "/PioneerP3DX", params: Optional[RobotParams] = None,
                 start_sim: bool = True):
        try:
            from coppeliasim_zmqremoteapi_client import RemoteAPIClient
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise RuntimeError("pip install coppeliasim-zmqremoteapi-client") from exc
        self.p = params or RobotParams()
        self.client = RemoteAPIClient(host=host, port=port)
        self.sim = self.client.require("sim")
        sim = self.sim
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

    def reset(self) -> None:
        sim = self.sim
        self.set_wheel_speeds(0.0, 0.0)
        # Restarting the simulation restores every object to its saved pose.
        sim.stopSimulation()
        while sim.getSimulationState() != sim.simulation_stopped:
            pass
        sim.setStepping(True)
        sim.startSimulation()

    def set_wheel_speeds(self, w_left: float, w_right: float) -> None:
        self.sim.setJointTargetVelocity(self.left, w_left)
        self.sim.setJointTargetVelocity(self.right, w_right)

    def step(self, dt: float) -> None:
        # dt is fixed by the scene (Simulation settings -> dt = 50 ms); we just step.
        self.sim.step()

    def get_pose(self) -> Tuple[float, float, float]:
        sim = self.sim
        x, y, _ = sim.getObjectPosition(self.robot, sim.handle_world)
        _, _, yaw = sim.getObjectOrientation(self.robot, sim.handle_world)
        return x, y, yaw

    def get_wheel_speeds(self) -> Tuple[float, float]:
        sim = self.sim
        return (sim.getJointVelocity(self.left), sim.getJointVelocity(self.right))

    def get_sonar(self) -> List[float]:
        out = []
        for h in self.sonars:
            res, dist, *_ = self.sim.readProximitySensor(h)
            out.append(dist if res > 0 else SONAR_RANGE)
        return out

    def close(self) -> None:
        try:
            self.set_wheel_speeds(0.0, 0.0)
            if self._started_here:
                self.sim.stopSimulation()
        except Exception:
            pass
