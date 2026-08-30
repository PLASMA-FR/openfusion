# SPDX-License-Identifier: LGPL-2.1-or-later
"""Intentional GUI unittest failure used only by the lifecycle process driver."""

import unittest

from OpenFusionGuiSystemExitRegression import INTERNAL_MODE, observe_gui_runtime


class IntentionalInternalFailure(unittest.TestCase):
    def test_failure_exit_code(self) -> None:
        observe_gui_runtime(INTERNAL_MODE)
        self.fail("Intentional failure verifies GUI test exit-code propagation")
