# CoppeliaSim scene

`teleop_p3dx.ttt`: a Pioneer P3-DX (built-in script removed) in the same 7 m x 6 m room as the mock
backend, with a box and a cylinder. Tested with CoppeliaSim Edu 4.10.

You do not need to open it yourself: `python -m teleop.server --backend coppelia` loads it when
CoppeliaSim has no robot open. To rebuild it, open an empty scene in CoppeliaSim and run
`python scenes/build_scene.py`. Details: [../docs/SCENE_SETUP.md](../docs/SCENE_SETUP.md).
