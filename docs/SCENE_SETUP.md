# CoppeliaSim scene setup and backend verification

Owner: **Akshat Kumar Angi**

> **Status:** `teleop/backends/coppelia.py` is written against the documented CoppeliaSim 4.6+
> ZMQ Remote API, but it has **not** been run on a real CoppeliaSim. Every step below must be
> checked by the team. Record each check in the meeting log and fix the code if a name or call differs.

## 1. Install
1. Download **CoppeliaSim Edu** (4.6 or newer) for your OS from https://www.coppeliarobotics.com/.
2. Start it once. The **ZMQ Remote API server** add-on starts automatically on port **23000**. Check the
   status bar message, or *Modules → Connectivity*.
3. In the project venv: `pip install coppeliasim-zmqremoteapi-client` (already in requirements.txt).

## 2. Build the scene (`scenes/teleop_p3dx.ttt`)
1. *File → New scene*.
2. From the **Model browser → robots → mobile**, drag **Pioneer p3dx** onto the floor at (0, 0), facing +x.
3. **Remove the built-in script.** The stock model has a child script that does Braitenberg obstacle
   avoidance and would fight our commands. Select `PioneerP3DX`, open its script (the page icon next
   to it in the scene hierarchy) and remove it (right-click → *Remove → Associated child script*), or
   replace its body with an empty `sysCall_init`.
4. Recreate the mock room so mock and CoppeliaSim runs are comparable (all values in metres):
   * floor: the default 5 m × 5 m floor is too small. Resize it, or use *Add → Primitive shape → Cuboid*
     for walls.
   * walls: a rectangle from x = −1.5 to 5.5 and y = −1.5 to 4.5, height 0.5, thickness 0.05.
   * box: a cuboid of 0.6 × 0.6 × 0.5 centred at (4.2, 0.0).
   * cylinder: radius 0.2, height 0.5, at (1.5, 4.0).
   * Tick **Collidable, Measurable, Detectable** on every obstacle (*Object properties → Common*). The
     sonars only see *detectable* objects.
5. *Simulation → Simulation settings*: time step **50 ms** (matches the 20 Hz server loop).
6. **Check the robot geometry** used in `teleop/config.py` (`wheel_radius` 0.0975 m, `wheel_base` 0.331 m)
   against the model: measure the wheel joint positions in the scene (`/PioneerP3DX/leftMotor` and
   `/PioneerP3DX/rightMotor`; the distance between them is the wheel base). Update `config.py` if different.
7. Save as `scenes/teleop_p3dx.ttt` and commit it.

## 3. Object names the backend expects
```
/PioneerP3DX                        base (pose)
/PioneerP3DX/leftMotor              /PioneerP3DX/rightMotor
/PioneerP3DX/ultrasonicSensor[0] … [15]
```
Older CoppeliaSim versions use names like `Pioneer_p3dx_leftMotor`. If `sim.getObject` raises
"object does not exist", read the real path in the scene hierarchy and change `coppelia.py` (or pass
`robot_path`).

## 4. Verification checklist (fill in, then commit)

| # | Check | How | Pass? |
|---|---|---|---|
| 1 | Client connects | `python -c "from coppeliasim_zmqremoteapi_client import RemoteAPIClient as C; print(C().require('sim').getSimulationTime())"` | |
| 2 | Handles found | `python -m teleop.server --backend coppelia` prints "Robot server ready" | |
| 3 | Stepping mode | sim time advances only while the server runs. It must equal 0.05 × ticks (printed at exit) | |
| 4 | Wheels turn the right way | `move 0.5`: robot moves +x; `turn 90`: robot turns left (CCW) | |
| 5 | Distances | `move 1.0` → `status` shows x ≈ 1.0. If it is 2x or 0.5x, fix wheel_radius | |
| 6 | Turn angle | `turn 90` → `status` shows th ≈ 90°. If it is wrong, fix wheel_base | |
| 7 | Sonars | drive at the box with `vel 0.3 0`: `obstacle` falls below 1.0 and the state becomes OBSTACLE near 0.30 | |
| 8 | Watchdog | quit the shell while `vel 0.2 0` runs: robot stops within ~1 s | |
| 9 | reset | `reset` puts the robot back at the start pose | |
| 10 | MQTT | repeat checks 4 and 8 with `--transport mqtt` | |
| 11 | Experiments | run `experiments/run_experiments.py` with a CoppeliaSim System (see member guide) and label the results `coppeliasim` | |

## 5. Known differences to expect versus the mock
* CoppeliaSim's sonars are cones with real detection and no Gaussian noise model. Distances can differ by a few cm.
* Wheels can slip, and the robot has inertia beyond the mock's first-order motor lag.
* Each `sim.step()` is a network round trip to CoppeliaSim. If the loop cannot keep 20 Hz, the server
  catches up (and resyncs if it falls 0.5 s behind). Report the achieved rate.
