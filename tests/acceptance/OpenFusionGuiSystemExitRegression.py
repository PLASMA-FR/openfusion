# SPDX-License-Identifier: LGPL-2.1-or-later
"""Process-level regression for GUI SystemExit propagation and shutdown cleanup."""

from __future__ import annotations

import argparse
import atexit
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


EXPECTED_EXIT_CODE = 7
CHILD_MODE_ENV = "OPENFUSION_GUI_SYSTEM_EXIT_CHILD"
STATE_DIR_ENV = "OPENFUSION_GUI_SYSTEM_EXIT_STATE_DIR"


def _run_in_freecad() -> None:
    import FreeCAD
    import FreeCADGui

    state_dir = Path(os.environ[STATE_DIR_ENV])
    state_dir.mkdir(parents=True, exist_ok=True)
    finalized_marker = state_dir / "python-finalized.txt"

    def mark_python_finalized(path: str = str(finalized_marker)) -> None:
        with open(path, "w", encoding="utf-8") as marker:
            marker.write("finalized\n")

    atexit.register(mark_python_finalized)

    event_loop_active = bool(FreeCADGui.getMainWindow().property("eventLoop"))
    if not event_loop_active:
        raise RuntimeError(
            "GUI SystemExit regression did not run inside the Qt event loop"
        )

    pid = os.getpid()
    executable_name = FreeCAD.ConfigGet("ExeName")
    cache_dir = Path(FreeCAD.getUserCachePath())
    lock_candidates = sorted(
        path
        for path in cache_dir.glob(f"{executable_name}_*.lock")
        if path.is_file() and "_Doc_" not in path.name
    )
    if len(lock_candidates) != 1:
        raise RuntimeError(
            "Expected exactly one GUI process lock in "
            f"{cache_dir}, found: {[str(path) for path in lock_candidates]}"
        )
    lock_path = lock_candidates[0]

    observation = {
        "cache_dir": str(cache_dir),
        "event_loop_active": event_loop_active,
        "executable_name": executable_name,
        "lock_path": str(lock_path),
        "pid": pid,
    }
    observation_path = state_dir / "observation.json"
    temporary_path = state_dir / "observation.json.tmp"
    temporary_path.write_text(
        json.dumps(observation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, observation_path)
    print("OpenFusion GUI SystemExit callback raising exit code 7", flush=True)
    raise SystemExit(EXPECTED_EXIT_CODE)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freecad", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    return parser.parse_args()


def _run_driver() -> int:
    args = _parse_args()
    freecad = args.freecad.resolve()
    state_dir = args.state_dir.resolve()

    if state_dir.exists():
        shutil.rmtree(state_dir)
    state_dir.mkdir(parents=True)

    home_dir = state_dir / "home"
    data_dir = state_dir / "data"
    cache_dir = state_dir / "cache"
    profile_dir = state_dir / "profile"
    for directory in (home_dir, data_dir, cache_dir, profile_dir):
        directory.mkdir()

    application_log = state_dir / "FreeCADGui-system-exit.log"
    console_log = state_dir / "console.log"
    observation_path = state_dir / "observation.json"
    finalized_marker = state_dir / "python-finalized.txt"
    user_config = profile_dir / "user.cfg"
    system_config = profile_dir / "system.cfg"

    environment = os.environ.copy()
    environment.update(
        {
            CHILD_MODE_ENV: "1",
            STATE_DIR_ENV: str(state_dir),
            "FREECAD_USER_DATA": str(data_dir),
            "FREECAD_USER_HOME": str(home_dir),
            "FREECAD_USER_TEMP": str(cache_dir),
        }
    )
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)

    command = [
        str(freecad),
        "--hidden",
        "--user-cfg",
        str(user_config),
        "--system-cfg",
        str(system_config),
        "--log-file",
        str(application_log),
        str(Path(__file__).resolve()),
    ]

    try:
        completed = subprocess.run(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=90,
        )
        console_output = completed.stdout
        return_code = completed.returncode
    except subprocess.TimeoutExpired as error:
        console_output = error.stdout or ""
        if isinstance(console_output, bytes):
            console_output = console_output.decode("utf-8", errors="replace")
        console_log.write_text(console_output, encoding="utf-8")
        print("FreeCAD GUI SystemExit regression timed out", file=sys.stderr)
        return 1

    console_log.write_text(console_output, encoding="utf-8")
    failures: list[str] = []
    if return_code != EXPECTED_EXIT_CODE:
        failures.append(
            f"FreeCAD returned {return_code}; expected exact exit code {EXPECTED_EXIT_CODE}"
        )

    observation: dict[str, object] = {}
    if not observation_path.is_file():
        failures.append("FreeCAD did not write the SystemExit callback observation")
    else:
        try:
            observation = json.loads(observation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"Cannot read callback observation: {error}")

    if observation:
        if observation.get("event_loop_active") is not True:
            failures.append(
                "SystemExit callback did not observe the active Qt event loop"
            )

        observed_cache = Path(str(observation.get("cache_dir", "")))
        observed_lock = Path(str(observation.get("lock_path", "")))
        if not observed_cache.is_dir():
            failures.append(
                f"Persistent cache directory was unexpectedly removed: {observed_cache}"
            )
        if observed_lock.exists():
            failures.append(
                f"GUI process lock remained after shutdown: {observed_lock}"
            )

    if not finalized_marker.is_file():
        failures.append("Embedded Python was not finalized during application cleanup")

    if not application_log.is_file():
        failures.append("FreeCAD did not write its application log")
    else:
        application_output = application_log.read_text(
            encoding="utf-8", errors="replace"
        )
        if "Finish: Event loop left" not in application_output:
            failures.append("Application log does not show a normal event-loop return")
        if " terminating..." not in application_output:
            failures.append("Application log does not show normal teardown starting")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        if console_output:
            print("--- FreeCAD output ---", file=sys.stderr)
            print(console_output, file=sys.stderr)
        return 1

    print("FreeCAD GUI propagated SystemExit(7) and completed lock/interpreter cleanup")
    return 0


if os.environ.get(CHILD_MODE_ENV) == "1":
    _run_in_freecad()
elif __name__ == "__main__":
    raise SystemExit(_run_driver())
