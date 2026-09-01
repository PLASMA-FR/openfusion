# SPDX-License-Identifier: LGPL-2.1-or-later
"""Controlled failure at the internal GUI unittest runner boundary."""

from __future__ import annotations

import unittest

from PySide import QtCore
from qtunittest import _ACTIVE_TEST_PROPERTY

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
    def __str__(self) -> str:
        return (
            "ControlledRunnerSystemExit.test_not_reached"
            '\t\x1b\x00\u0085\u2028\u2029"\\'
        )

    def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult:
        application = QtCore.QCoreApplication.instance()
        if application is None:
            raise RuntimeError("Controlled SystemExit test has no QCoreApplication")
        application.setProperty(_ACTIVE_TEST_PROPERTY, str(self))
        observe_gui_runtime(INTERNAL_SYSTEM_EXIT_MODE)
        raise SystemExit(INTERNAL_SYSTEM_EXIT_CODE)

    def test_not_reached(self) -> None:
        self.fail("Controlled runner SystemExit did not occur")
