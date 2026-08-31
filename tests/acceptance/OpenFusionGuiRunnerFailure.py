# SPDX-License-Identifier: LGPL-2.1-or-later
"""Controlled failure at the internal GUI unittest runner boundary."""

from __future__ import annotations

import unittest

from OpenFusionGuiSystemExitRegression import (
    DIAGNOSTIC_MESSAGE,
    DIAGNOSTIC_MODE,
    INTERNAL_SYSTEM_EXIT_CODE,
    INTERNAL_SYSTEM_EXIT_MODE,
    observe_gui_runtime,
)


class ControlledRunnerFailure(unittest.TestCase):
    def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult:
        observe_gui_runtime(DIAGNOSTIC_MODE)
        raise RuntimeError(DIAGNOSTIC_MESSAGE)

    def test_not_reached(self) -> None:
        self.fail("Controlled runner failure did not occur")


class ControlledRunnerSystemExit(unittest.TestCase):
    def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult:
        observe_gui_runtime(INTERNAL_SYSTEM_EXIT_MODE)
        raise SystemExit(INTERNAL_SYSTEM_EXIT_CODE)

    def test_not_reached(self) -> None:
        self.fail("Controlled runner SystemExit did not occur")
