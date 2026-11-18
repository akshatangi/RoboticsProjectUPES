"""Build scenes/teleop_p3dx.ttt in a running CoppeliaSim (ZMQ Remote API).

    1. start CoppeliaSim (a new, empty scene is fine)
    2. python scenes/build_scene.py
    3. the scene is saved to scenes/teleop_p3dx.ttt; from then on just open that file

The room is the same as the mock backend's (teleop/backends/mock.py, World.default):
walls from x = -1.5..5.5 and y = -1.5..4.5, a 0.6 m box centred at (4.2, 0),
a cylinder of radius 0.2 m at (1.5, 4.0).  The stock Pioneer P3-DX model is
loaded at (0, 0) facing +x, and its built-in Braitenberg script is removed so
that only our server drives the motors.
"""

from __future__ import annotations

import os
import sys

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "teleop_p3dx.ttt")
WALL_H, WALL_T = 0.5, 0.05
GREY, WALLC, FLOORC = [0.75, 0.73, 0.68], [0.55, 0.57, 0.62], [0.92, 0.92, 0.90]


def main() -> None:
    client = RemoteAPIClient()
    sim = client.require("sim")
    if sim.getSimulationState() != sim.simulation_stopped:
        sim.stopSimulation()
        while sim.getSimulationState() != sim.simulation_stopped:
            pass

    def cuboid(name, size, pos, color, respondable=True):
        h = sim.createPrimitiveShape(sim.primitiveshape_cuboid, size, 0)
        sim.setObjectAlias(h, name)
        sim.setObjectPosition(h, sim.handle_world, pos)
        sim.setObjectInt32Param(h, sim.shapeintparam_static, 1)
        sim.setObjectInt32Param(h, sim.shapeintparam_respondable, 1 if respondable else 0)
        # collidable + measurable + detectable, so the sonars see it
        sim.setObjectSpecialProperty(h, sim.objectspecialproperty_collidable
                                     + sim.objectspecialproperty_measurable
                                     + sim.objectspecialproperty_detectable)
        sim.setShapeColor(h, None, sim.colorcomponent_ambient_diffuse, color)
        return h

    # floor that covers the whole room (the default scene floor is only 5 m x 5 m)
    cuboid("roomFloor", [7.6, 6.6, 0.02], [2.0, 1.5, -0.01], FLOORC)
    # walls
    x0, y0, x1, y1 = -1.5, -1.5, 5.5, 4.5
    cx, cy, w, d = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
    cuboid("wallSouth", [w + WALL_T, WALL_T, WALL_H], [cx, y0, WALL_H / 2], WALLC)
    cuboid("wallNorth", [w + WALL_T, WALL_T, WALL_H], [cx, y1, WALL_H / 2], WALLC)
    cuboid("wallWest", [WALL_T, d + WALL_T, WALL_H], [x0, cy, WALL_H / 2], WALLC)
    cuboid("wallEast", [WALL_T, d + WALL_T, WALL_H], [x1, cy, WALL_H / 2], WALLC)
    # obstacles
    cuboid("box", [0.6, 0.6, WALL_H], [4.2, 0.0, WALL_H / 2], GREY)
    cyl = sim.createPrimitiveShape(sim.primitiveshape_cylinder, [0.4, 0.4, WALL_H], 0)
    sim.setObjectAlias(cyl, "cylinder")
    sim.setObjectPosition(cyl, sim.handle_world, [1.5, 4.0, WALL_H / 2])
    sim.setObjectInt32Param(cyl, sim.shapeintparam_static, 1)
    sim.setObjectInt32Param(cyl, sim.shapeintparam_respondable, 1)
    sim.setObjectSpecialProperty(cyl, sim.objectspecialproperty_collidable
                                 + sim.objectspecialproperty_measurable + sim.objectspecialproperty_detectable)
    sim.setShapeColor(cyl, None, sim.colorcomponent_ambient_diffuse, GREY)

    # the robot
    app = sim.getStringParam(sim.stringparam_application_path)
    candidates = [os.path.join(app, "models", "robots", "mobile", "pioneer p3dx.ttm"),
                  os.path.join(app, "..", "models", "robots", "mobile", "pioneer p3dx.ttm")]
    model = next((p for p in candidates if os.path.exists(p)), None)
    if model is None:
        sys.exit("pioneer p3dx.ttm not found under " + app)
    robot = sim.loadModel(model)
    sim.setObjectAlias(robot, "PioneerP3DX")
    pos = sim.getObjectPosition(robot, sim.handle_world)
    sim.setObjectPosition(robot, sim.handle_world, [0.0, 0.0, pos[2]])
    sim.setObjectOrientation(robot, sim.handle_world, [0.0, 0.0, 0.0])

    # remove the built-in Braitenberg script (it would also drive the motors)
    removed = 0
    for h in sim.getObjectsInTree(robot, sim.sceneobject_script, 0):
        sim.removeObjects([h])
        removed += 1
    if removed == 0:                       # older versions: child script attached to the model
        try:
            s = sim.getScript(sim.scripttype_childscript, robot)
            if s != -1:
                sim.removeScript(s)
                removed += 1
        except Exception:
            pass

    # report what the backend will look for
    names = [sim.getObjectAlias(h, 1) for h in sim.getObjectsInTree(robot, sim.handle_all, 0)]
    for want in ["/PioneerP3DX/leftMotor", "/PioneerP3DX/rightMotor", "/PioneerP3DX/ultrasonicSensor[0]",
                 "/PioneerP3DX/ultrasonicSensor[15]"]:
        try:
            sim.getObject(want)
            print("found  ", want)
        except Exception:
            print("MISSING", want)
    left = sim.getObject("/PioneerP3DX/leftMotor")
    right = sim.getObject("/PioneerP3DX/rightMotor")
    lp = sim.getObjectPosition(left, sim.handle_world)
    rp = sim.getObjectPosition(right, sim.handle_world)
    base = ((lp[0] - rp[0]) ** 2 + (lp[1] - rp[1]) ** 2) ** 0.5
    print(f"scripts removed: {removed}; objects in model: {len(names)}")
    print(f"measured wheel base (joint distance): {base:.4f} m   (config.py uses 0.331)")
    print(f"simulation time step: {sim.getFloatParam(sim.floatparam_simulation_time_step):.3f} s")
    sim.saveScene(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    main()
