"""Run the stdlib-only ECS deployment entry point without installing backend dependencies."""

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "apps/backend/src/super_ai/deployment.py"),
        run_name="__main__",
    )
