# SPDX-License-Identifier: LGPL-2.1-or-later
"""Passing GUI unittest used only by the lifecycle process driver."""

import unittest

import FreeCADGui
from PySide import QtWidgets

from OpenFusionGuiSystemExitRegression import (
    INTERNAL_MDI_TEARDOWN_MODE,
    INTERNAL_SUCCESS_MODE,
    observe_gui_runtime,
)


_MDI_TEARDOWN_OBJECTS = []


class IntentionalInternalSuccess(unittest.TestCase):
    def test_success_exit_code(self) -> None:
        observe_gui_runtime(INTERNAL_SUCCESS_MODE)
        FreeCADGui.updateGui()


class IntentionalMdiTeardown(unittest.TestCase):
    def test_mdi_children_shutdown_cleanly(self) -> None:
        main_window = FreeCADGui.getMainWindow()
        mdi_area = main_window.findChild(QtWidgets.QMdiArea)
        self.assertIsNotNone(mdi_area)

        created_subwindows = []
        for index in range(6):
            content = QtWidgets.QWidget()
            content.setObjectName(f"OpenFusionMdiTeardownContent{index}")
            subwindow = mdi_area.addSubWindow(content)
            subwindow.setObjectName(f"OpenFusionMdiTeardownSubWindow{index}")
            subwindow.show()
            created_subwindows.append(subwindow)
            _MDI_TEARDOWN_OBJECTS.extend((content, subwindow))

        created_subwindows[-1].showMaximized()
        FreeCADGui.updateGui()
        observe_gui_runtime(INTERNAL_MDI_TEARDOWN_MODE)
        self.assertTrue(all(window in mdi_area.subWindowList() for window in created_subwindows))
