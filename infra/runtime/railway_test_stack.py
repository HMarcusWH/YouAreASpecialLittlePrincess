"""Railway's single-container synthetic test stack (API + Free analysis).

Each child receives only its reviewed role's environment variables. This mode
never enables Premium, purchases, notifications or a public identity provider.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from runtime_policy import preflight

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "infra" / "runtime" / "entrypoint.py"

COMMON = (
    "PATH", "PYTHONPATH", "PYTHONUNBUFFERED", "HOME", "LANG",
    "PRINCESS_ENV", "PRINCESS_LOCAL_STORAGE_DIR",
    "PRINCESS_TOMBSTONE_DIR", "PRINCESS_PUBLIC_API_BASE",
)


def role_env(role: str) -> dict[str, str]:
    environment = {key: os.environ[key] for key in COMMON if key in os.environ}
    # Bound BLAS/OpenMP thread pools within the Trial plan's 1 GB container memory.
    # Otherwise scientific imports may reserve large per-thread stacks.
    environment.update({
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
        "BLIS_NUM_THREADS": "1",
    })
    environment["PRINCESS_ENV"] = "test"
    environment["PRINCESS_COMPONENT"] = role
    database_key = "PRINCESS_API_DATABASE_URL" if role == "api" else "PRINCESS_WORKER_DATABASE_URL"
    environment["PRINCESS_DATABASE_URL"] = os.environ[database_key]
    if role == "api":
        required = ("PRINCESS_SESSION_SECRET", "PRINCESS_IDENTITY_AUDIENCE",
                    "PRINCESS_STORAGE_SIGNING_KEY")
    else:
        required = ("PRINCESS_STORAGE_READ_KEY",)
    for key in required:
        environment[key] = os.environ[key]
    preflight(environment, ROOT)
    return environment


def main() -> int:
    if os.environ.get("PRINCESS_ENV") != "test":
        raise RuntimeError("combined test stack requires PRINCESS_ENV=test")
    if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        raise RuntimeError("synthetic test identity must not be exposed on a public Railway domain")
    api_env, worker_env = role_env("api"), role_env("analysis_worker")
    os.umask(0o077)
    for directory in ("PRINCESS_LOCAL_STORAGE_DIR", "PRINCESS_TOMBSTONE_DIR"):
        path = Path(os.environ[directory])
        if not path.is_absolute() or not str(path).startswith("/data/"):
            raise RuntimeError("test storage paths must be under the attached /data volume")
        path.mkdir(parents=True, exist_ok=True)
        if os.geteuid() == 0:
            os.chown(path, 10001, 10001)
        path.chmod(0o700)

    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)

    processes: list[subprocess.Popen[bytes]] = []
    stopping = False

    def stop(_signal: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for role, env in (("api", api_env), ("analysis_worker", worker_env)):
            process = subprocess.Popen([sys.executable, str(ENTRYPOINT)], env=env)
            processes.append(process)
            print(f"Started synthetic test role {role} (pid={process.pid})", flush=True)
        while not stopping:
            if any(process.poll() is not None for process in processes):
                print("test stack process exited; stopping remaining roles", flush=True)
                return 1
            time.sleep(0.5)
        return 0
    finally:
        stop(signal.SIGTERM, None)
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
