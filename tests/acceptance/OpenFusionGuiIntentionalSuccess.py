# SPDX-License-Identifier: LGPL-2.1-or-later
"""Passing GUI unittest used only by the lifecycle process driver."""

import unittest

import FreeCADGui

from OpenFusionGuiSystemExitRegression import INTERNAL_SUCCESS_MODE, observe_gui_runtime


class IntentionalInternalSuccess(unittest.TestCase):
    def test_success_exit_code(self) -> None:
        observe_gui_runtime(INTERNAL_SUCCESS_MODE)
        FreeCADGui.updateGui()
