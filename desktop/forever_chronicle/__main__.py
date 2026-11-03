from .app import main

if __name__ == "__main__":      # not when a worker process (the 3D map's, ui/stage3d/ground.py) imports it
    raise SystemExit(main())
