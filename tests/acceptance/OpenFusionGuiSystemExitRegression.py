# SPDX-License-Identifier: LGPL-2.1-or-later
"""Process-level regression for GUI test exits, diagnostics, and shutdown cleanup."""

from __future__ import annotations

import argparse
import atexit
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


POSITIONAL_MODE = "positional"
DIAGNOSTIC_MODE = "diagnostic"
INTERNAL_MODE = "internal"
INTERNAL_SUCCESS_MODE = "internal-success"
INTERNAL_MDI_TEARDOWN_MODE = "internal-mdi-teardown"
INTERNAL_SYSTEM_EXIT_MODE = "internal-system-exit"
POSITIONAL_EXIT_CODE = 7
INTERNAL_EXIT_CODE = 1
INTERNAL_SUCCESS_EXIT_CODE = 0
INTERNAL_SYSTEM_EXIT_CODE = 23
DIAGNOSTIC_EXIT_CODE = 1
DIAGNOSTIC_MESSAGE = "OpenFusion controlled non-SystemExit callback failure"
DIAGNOSTIC_LOG_PREFIX = "Exception diagnostic in delayed startup callback"
SANITIZED_SYSTEM_EXIT_TEST_NAME = (
    'active_test="ControlledRunnerSystemExit.test_not_reached'
    "\\u0009\\u001b\\u0000\\u0085\\u2028\\u2029"
    '\\"'
    "\\\\"
    '"'
)
CHILD_MODE_ENV = "OPENFUSION_GUI_SYSTEM_EXIT_CHILD"
STATE_DIR_ENV = "OPENFUSION_GUI_SYSTEM_EXIT_STATE_DIR"
QT_PLUGIN_PATH_ENV = "QT_PLUGIN_PATH"
QT_PLATFORM_PLUGIN_PATH_ENV = "QT_QPA_PLATFORM_PLUGIN_PATH"


def _validate_windows_qt_plugin_environment() -> list[str]:
    if os.name != "nt":
        return []

    failures: list[str] = []
    configured_paths: dict[str, Path] = {}
    for variable in (QT_PLUGIN_PATH_ENV, QT_PLATFORM_PLUGIN_PATH_ENV):
        value = os.environ.get(variable, "")
        if not value:
            failures.append(f"lifecycle driver did not inherit {variable}")
            continue
        try:
            configured_paths[variable] = Path(value).resolve(strict=True)
        except OSError as error:
            failures.append(f"{variable} does not name an existing path: {error}")

    if len(configured_paths) != 2:
        return failures

    plugin_directory = configured_paths[QT_PLUGIN_PATH_ENV]
    platform_directory = configured_paths[QT_PLATFORM_PLUGIN_PATH_ENV]
    if platform_directory.parent != plugin_directory:
        failures.append(
            f"{QT_PLATFORM_PLUGIN_PATH_ENV} is not the platforms directory below "
            f"{QT_PLUGIN_PATH_ENV}: {platform_directory}"
        )

    available_plugins = {
        candidate.name.casefold()
        for candidate in platform_directory.iterdir()
        if candidate.is_file()
    }
    for platform in ("windows", "offscreen"):
        prefix = f"q{platform}"
        if not any(name.startswith(prefix) and name.endswith(".dll") for name in available_plugins):
            failures.append(f"Qt {platform} platform plugin is missing from {platform_directory}")
    return failures


def observe_gui_runtime(scenario: str) -> None:
    import FreeCAD
    import FreeCADGui
    from PySide import QtWidgets

    state_dir = Path(os.environ[STATE_DIR_ENV])
    state_dir.mkdir(parents=True, exist_ok=True)
    finalized_marker = state_dir / "python-finalized.txt"

    def mark_python_finalized(path: str = str(finalized_marker)) -> None:
        with open(path, "w", encoding="utf-8") as marker:
            marker.write("finalized\n")

    atexit.register(mark_python_finalized)

    event_loop_active = bool(FreeCADGui.getMainWindow().property("eventLoop"))
    if not event_loop_active:
        raise RuntimeError("GUI SystemExit regression did not run inside the Qt event loop")

    quit_on_last_window_closed = QtWidgets.QApplication.quitOnLastWindowClosed()
    expected_automatic_quit = scenario == POSITIONAL_MODE
    if quit_on_last_window_closed != expected_automatic_quit:
        raise RuntimeError(
            "GUI lifecycle used the wrong automatic last-window exit policy: "
            f"scenario={scenario!r}, expected={expected_automatic_quit}, "
            f"actual={quit_on_last_window_closed}"
        )

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

    observation = {
        "cache_dir": str(cache_dir),
        "event_loop_active": event_loop_active,
        "executable_name": executable_name,
        "lock_path": str(lock_candidates[0]),
        "pid": os.getpid(),
        "quit_on_last_window_closed": quit_on_last_window_closed,
        "scenario": scenario,
    }
    observation_path = state_dir / "observation.json"
    temporary_path = state_dir / "observation.json.tmp"
    temporary_path.write_text(
        json.dumps(observation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, observation_path)


def _run_positional_child() -> None:
    observe_gui_runtime(POSITIONAL_MODE)
    print("OpenFusion GUI positional callback raising SystemExit(7)", flush=True)
    raise SystemExit(POSITIONAL_EXIT_CODE)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freecad", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    return parser.parse_args()


def _run_scenario(
    freecad: Path,
    root_state_dir: Path,
    scenario: str,
    expected_exit_code: int,
) -> list[str]:
    state_dir = root_state_dir / scenario
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

    environment = os.environ.copy()
    environment.update(
        {
            CHILD_MODE_ENV: scenario,
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
        str(profile_dir / "user.cfg"),
        "--system-cfg",
        str(profile_dir / "system.cfg"),
        "--log-file",
        str(application_log),
    ]
    if scenario == POSITIONAL_MODE:
        command.append(str(Path(__file__).resolve()))
    else:
        if scenario == DIAGNOSTIC_MODE:
            test_case = "OpenFusionGuiRunnerFailure.ControlledRunnerFailure"
        elif scenario == INTERNAL_SYSTEM_EXIT_MODE:
            test_case = "OpenFusionGuiRunnerFailure.ControlledRunnerSystemExit"
        elif scenario == INTERNAL_MDI_TEARDOWN_MODE:
            test_case = (
                "OpenFusionGuiIntentionalSuccess.IntentionalMdiTeardown."
                "test_mdi_children_shutdown_cleanly"
            )
        elif scenario == INTERNAL_SUCCESS_MODE:
            test_case = (
                "OpenFusionGuiIntentionalSuccess.IntentionalInternalSuccess."
                "test_success_exit_code"
            )
        else:
            test_case = (
                "OpenFusionGuiIntentionalFailure.IntentionalInternalFailure."
                "test_failure_exit_code"
            )
        command.extend(
            [
                "--python-path",
                str(Path(__file__).resolve().parent),
                "--run-test",
                test_case,
            ]
        )

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
        return [f"{scenario}: FreeCAD GUI lifecycle regression timed out"]

    console_log.write_text(console_output, encoding="utf-8")
    failures: list[str] = []
    if return_code != expected_exit_code:
        failures.append(
            f"{scenario}: FreeCAD returned {return_code}; "
            f"expected exact exit code {expected_exit_code}"
        )

    observation: dict[str, object] = {}
    if not observation_path.is_file():
        failures.append(f"{scenario}: callback observation was not written")
    else:
        try:
            observation = json.loads(observation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"{scenario}: cannot read callback observation: {error}")

    if observation:
        if observation.get("scenario") != scenario:
            failures.append(f"{scenario}: callback recorded the wrong scenario")
        if observation.get("event_loop_active") is not True:
            failures.append(f"{scenario}: callback did not observe the active event loop")
        expected_automatic_quit = scenario == POSITIONAL_MODE
        if observation.get("quit_on_last_window_closed") is not expected_automatic_quit:
            failures.append(
                f"{scenario}: callback observed the wrong automatic last-window exit policy"
            )

        observed_cache = Path(str(observation.get("cache_dir", "")))
        observed_lock = Path(str(observation.get("lock_path", "")))
        if not observed_cache.is_dir():
            failures.append(f"{scenario}: persistent cache directory was removed: {observed_cache}")
        if observed_lock.exists():
            failures.append(
                f"{scenario}: GUI process lock remained after shutdown: {observed_lock}"
            )

    if not finalized_marker.is_file():
        failures.append(f"{scenario}: embedded Python was not finalized")

    if not application_log.is_file():
        failures.append(f"{scenario}: FreeCAD did not write its application log")
    else:
        application_output = application_log.read_text(encoding="utf-8", errors="replace")
        if "Finish: Event loop left" not in application_output:
            failures.append(f"{scenario}: event loop did not return normally")
        if " terminating..." not in application_output:
            failures.append(f"{scenario}: normal teardown did not start")
        if "runApplicationWithExitCode catch:" in application_output:
            failures.append(f"{scenario}: unexpected runApplicationWithExitCode catch")

        if scenario == DIAGNOSTIC_MODE:
            expected_event_loop_state = "GUI event loop return: raw=1 stored_present=no stored_code=0 selected=1"
        else:
            expected_event_loop_state = (
                f"GUI event loop return: raw={expected_exit_code} stored_present=yes "
                f"stored_code={expected_exit_code} selected={expected_exit_code}"
            )
        if expected_event_loop_state not in application_output:
            failures.append(
                f"{scenario}: event-loop exit-state diagnostic was missing or incorrect"
            )

        request_marker = "GUI SystemExit request:"
        if scenario == DIAGNOSTIC_MODE:
            if request_marker in application_output:
                failures.append(
                    f"{scenario}: non-SystemExit path unexpectedly recorded SystemExit"
                )
        else:
            expected_request = (
                f"requested={expected_exit_code} authoritative={expected_exit_code} "
                "first=yes dispatch=direct"
            )
            if (
                request_marker not in application_output
                or expected_request not in application_output
            ):
                failures.append(
                    f"{scenario}: SystemExit request diagnostic was missing or incorrect"
                )
            if scenario == INTERNAL_SYSTEM_EXIT_MODE and (
                SANITIZED_SYSTEM_EXIT_TEST_NAME not in application_output
            ):
                failures.append(
                    f"{scenario}: SystemExit diagnostic omitted the active internal test"
                )
        if scenario == DIAGNOSTIC_MODE:
            if DIAGNOSTIC_MESSAGE not in application_output:
                failures.append(f"{scenario}: application log omitted the controlled failure")
            if DIAGNOSTIC_LOG_PREFIX not in application_output:
                failures.append(f"{scenario}: Release log omitted the ordinary callback diagnostic")

    if scenario == DIAGNOSTIC_MODE:
        if "Traceback (most recent call last):" not in console_output:
            failures.append(f"{scenario}: console omitted the Python traceback")
        if "in run" not in console_output:
            failures.append(f"{scenario}: traceback omitted the failing frame")
        if "raise RuntimeError(DIAGNOSTIC_MESSAGE)" not in console_output:
            failures.append(f"{scenario}: traceback omitted the failing source line")
        if DIAGNOSTIC_MESSAGE not in console_output:
            failures.append(f"{scenario}: console omitted the controlled failure")
    elif scenario == INTERNAL_SYSTEM_EXIT_MODE:
        if f"SystemExit: {INTERNAL_SYSTEM_EXIT_CODE}" not in console_output:
            failures.append(f"{scenario}: console omitted the controlled SystemExit")

    if " completely terminated" not in console_output:
        failures.append(f"{scenario}: normal teardown did not complete")

    expected_lifecycle_stages = (
        "run-returned",
        "streams-restored",
        "app-destruct-begin",
        "app-destruct-complete",
        "main-return",
        "main-window-destruct-body-begin",
        "main-window-owned-ui-destruct-begin",
        "main-window-owned-ui-destruct-end",
        "main-window-owned-menus-destruct-begin",
        "main-window-owned-menus-destruct-end",
        "main-window-destruct-body-end",
    )
    for stage in expected_lifecycle_stages:
        marker = f"OpenFusion lifecycle: stage={stage}"
        if not stage.startswith("main-window-"):
            marker += f" exit_code={expected_exit_code}"
        if marker not in console_output:
            failures.append(f"{scenario}: missing main lifecycle stage {stage}")
    if "OpenFusion lifecycle: stage=run-application-catch" in console_output:
        failures.append(f"{scenario}: unexpected raw runApplication catch marker")

    teardown_markers = (
        "main-window-destruct-body-begin",
        "main-window-owned-ui-destruct-begin",
        "main-window-owned-ui-destruct-end",
        "main-window-owned-menus-destruct-begin",
        "main-window-owned-menus-destruct-end",
        "main-window-destruct-body-end",
    )
    teardown_offsets = [
        console_output.find(f"OpenFusion lifecycle: stage={stage}")
        for stage in teardown_markers
    ]
    if any(offset < 0 for offset in teardown_offsets) or teardown_offsets != sorted(teardown_offsets):
        failures.append(f"{scenario}: MainWindow owned-UI teardown markers are out of order")

    if failures and console_output:
        failures.append(f"{scenario}: FreeCAD output follows:\n{console_output}")
    return failures


def _run_driver() -> int:
    args = _parse_args()
    freecad = args.freecad.resolve()
    state_dir = args.state_dir.resolve()

    environment_failures = _validate_windows_qt_plugin_environment()
    if environment_failures:
        for failure in environment_failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    if state_dir.exists():
        shutil.rmtree(state_dir)
    state_dir.mkdir(parents=True)

    failures = _run_scenario(freecad, state_dir, POSITIONAL_MODE, POSITIONAL_EXIT_CODE)
    failures.extend(
        _run_scenario(
            freecad,
            state_dir,
            INTERNAL_SUCCESS_MODE,
            INTERNAL_SUCCESS_EXIT_CODE,
        )
    )
    failures.extend(
        _run_scenario(
            freecad,
            state_dir,
            INTERNAL_MDI_TEARDOWN_MODE,
            INTERNAL_SUCCESS_EXIT_CODE,
        )
    )
    failures.extend(_run_scenario(freecad, state_dir, INTERNAL_MODE, INTERNAL_EXIT_CODE))
    failures.extend(
        _run_scenario(
            freecad,
            state_dir,
            DIAGNOSTIC_MODE,
            DIAGNOSTIC_EXIT_CODE,
        )
    )
    failures.extend(
        _run_scenario(
            freecad,
            state_dir,
            INTERNAL_SYSTEM_EXIT_MODE,
            INTERNAL_SYSTEM_EXIT_CODE,
        )
    )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    print(
        "FreeCAD GUI preserved positional SystemExit(7), internal test success exit 0, "
        "live-MDI/menu-churn teardown exit 0, internal test failure exit 1, "
        "internal SystemExit(23), "
        "controlled non-SystemExit diagnostics, and completed lock/interpreter cleanup"
    )
    return 0


if os.environ.get(CHILD_MODE_ENV) == POSITIONAL_MODE:
    _run_positional_child()
elif __name__ == "__main__":
    raise SystemExit(_run_driver())
