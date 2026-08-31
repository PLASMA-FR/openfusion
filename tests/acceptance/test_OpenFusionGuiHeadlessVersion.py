# SPDX-License-Identifier: LGPL-2.1-or-later
"""Regression tests for bounded rejected-version GUI process cleanup."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from OpenFusionGuiHeadlessVersion import (
    is_headless_version_output,
    observe_normal_path,
)


class HeadlessVersionNormalPathTest(unittest.TestCase):
    def test_timeout_cleans_new_process_group_with_finite_waits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "wait.py"
            script.write_text(
                "import subprocess, sys, time\n"
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                "print('normal-path-started', flush=True)\n"
                "time.sleep(60)\n",
                encoding="utf-8",
            )
            started = time.monotonic()
            observation = observe_normal_path(
                [sys.executable, str(script)],
                os.environ.copy(),
                observation_timeout=0.25,
                terminate_timeout=1.0,
                kill_timeout=3.0,
            )
            self.assertTrue(observation.timed_out)
            self.assertIsInstance(observation.returncode, int)
            self.assertIn("normal-path-started", observation.stdout)
            self.assertLess(time.monotonic() - started, 5.0)

    def test_only_exact_supported_shapes_are_headless_payloads(self) -> None:
        expected = "OpenFusion 1.1.3"
        self.assertTrue(is_headless_version_output(expected + "\n", expected))
        self.assertTrue(
            is_headless_version_output(
                expected
                + "\nSource revision: abc\nSource revision date: today\n"
                + "Source repository: origin\n",
                expected,
            )
        )
        self.assertFalse(
            is_headless_version_output(expected + ", Libs: Qt 6.8.3\n", expected)
        )


if __name__ == "__main__":
    unittest.main()
