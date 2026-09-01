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
_OWNED_WORKBENCH_MENU_PROPERTY = "OpenFusionOwnedWorkbenchMenuIdentity"


class IntentionalInternalSuccess(unittest.TestCase):
    def test_success_exit_code(self) -> None:
        observe_gui_runtime(INTERNAL_SUCCESS_MODE)
        FreeCADGui.updateGui()


class IntentionalMdiTeardown(unittest.TestCase):
    def _exercise_workbench_menu_cache(self, main_window: QtWidgets.QMainWindow) -> None:
        menu_bar = main_window.menuBar()
        external_menu = QtWidgets.QMenu("OpenFusion external retained menu", menu_bar)
        external_menu.setObjectName("OpenFusionExternalRetainedMenu")
        menu_bar.addMenu(external_menu)
        _MDI_TEARDOWN_OBJECTS.append(external_menu)

        available_workbenches = set(FreeCADGui.listWorkbenches())
        preferred_workbenches = ("MaterialWorkbench", "DraftWorkbench")
        fallback_workbenches = ("NoneWorkbench", "PartWorkbench")
        selected_workbenches = (
            preferred_workbenches
            if all(name in available_workbenches for name in preferred_workbenches)
            else fallback_workbenches
        )
        workbenches = [
            name
            for name in selected_workbenches
            if name in available_workbenches
        ]
        self.assertEqual(len(workbenches), 2)
        active_workbench = FreeCADGui.activeWorkbench()
        original_workbench = active_workbench.name() if active_workbench else ""

        def owned_menu_identities() -> list[str]:
            direct_menus = [
                menu
                for menu in menu_bar.findChildren(QtWidgets.QMenu)
                if menu.parent() is menu_bar
            ]
            identities = [
                str(menu.property(_OWNED_WORKBENCH_MENU_PROPERTY))
                for menu in direct_menus
                if menu.property(_OWNED_WORKBENCH_MENU_PROPERTY)
            ]
            self.assertEqual(len(identities), len(set(identities)))
            return identities

        try:
            for workbench in workbenches:
                FreeCADGui.activateWorkbench(workbench)
                QtWidgets.QApplication.processEvents()
            expected_identities = set(owned_menu_identities())
            self.assertTrue(expected_identities)

            for iteration in range(64):
                FreeCADGui.activateWorkbench(workbenches[iteration % len(workbenches)])
                QtWidgets.QApplication.processEvents()
                self.assertEqual(set(owned_menu_identities()), expected_identities)
                self.assertIs(external_menu.parent(), menu_bar)
                self.assertIn(external_menu.menuAction(), menu_bar.actions())
        finally:
            if original_workbench in available_workbenches:
                FreeCADGui.activateWorkbench(original_workbench)
                QtWidgets.QApplication.processEvents()

    def test_mdi_children_shutdown_cleanly(self) -> None:
        main_window = FreeCADGui.getMainWindow()
        mdi_area = main_window.findChild(QtWidgets.QMdiArea)
        self.assertIsNotNone(mdi_area)

        created_subwindows = []
        for index in range(64):
            content = QtWidgets.QWidget()
            content.setObjectName(f"OpenFusionMdiTeardownContent{index}")
            subwindow = mdi_area.addSubWindow(content)
            subwindow.setObjectName(f"OpenFusionMdiTeardownSubWindow{index}")
            subwindow.showMaximized()
            QtWidgets.QApplication.processEvents()
            created_subwindows.append(subwindow)
            _MDI_TEARDOWN_OBJECTS.extend((content, subwindow))

        FreeCADGui.updateGui()
        self._exercise_workbench_menu_cache(main_window)
        observe_gui_runtime(INTERNAL_MDI_TEARDOWN_MODE)
        self.assertTrue(all(window in mdi_area.subWindowList() for window in created_subwindows))
