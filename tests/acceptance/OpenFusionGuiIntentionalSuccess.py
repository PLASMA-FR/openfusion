# SPDX-License-Identifier: LGPL-2.1-or-later
"""Passing GUI unittest used only by the lifecycle process driver."""

import os
import unittest

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets

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

    def _retain_owned_main_window_shell(self, main_window: QtWidgets.QMainWindow) -> None:
        document = FreeCAD.newDocument("OpenFusionDockTeardown")
        selected_object = None
        for index in range(32):
            selected_object = document.addObject("App::Feature", f"DockFeature{index}")
            selected_object.Label = f"Dock feature {index}"
        document.recompute()
        document.saveAs(
            os.path.join(
                os.environ["OPENFUSION_GUI_SYSTEM_EXIT_STATE_DIR"],
                "OpenFusionDockTeardown.FCStd",
            )
        )
        if selected_object is not None:
            FreeCADGui.Selection.addSelection(document.Name, selected_object.Name)
        FreeCADGui.updateGui()

        tool_bar = QtWidgets.QToolBar("OpenFusion retained toolbar", main_window)
        tool_bar.setObjectName("OpenFusionRetainedToolBar")
        main_window.addToolBar(tool_bar)

        dock_widgets = []
        for index in range(5):
            dock_widget = QtWidgets.QDockWidget(
                f"OpenFusion retained dock {index}",
                main_window,
            )
            dock_widget.setObjectName(f"OpenFusionRetainedDockWidget{index}")
            dock_widget.setWidget(
                QtWidgets.QLabel(f"retained dock content {index}", dock_widget)
            )
            dock_area = (
                QtCore.Qt.LeftDockWidgetArea
                if index % 2 == 0
                else QtCore.Qt.RightDockWidgetArea
            )
            main_window.addDockWidget(dock_area, dock_widget)
            dock_widgets.append(dock_widget)

        external_action_owner = QtCore.QObject()
        external_action = QtGui.QAction("OpenFusion retained external action", external_action_owner)
        tool_bar.addAction(external_action)
        dock_widgets[0].addAction(external_action)

        status_widget = QtWidgets.QLabel("retained status content", main_window.statusBar())
        status_widget.setObjectName("OpenFusionRetainedStatusWidget")
        main_window.statusBar().addPermanentWidget(status_widget)
        _MDI_TEARDOWN_OBJECTS.extend(
            (
                document,
                tool_bar,
                *dock_widgets,
                status_widget,
                external_action_owner,
                external_action,
            )
        )

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
        self._retain_owned_main_window_shell(main_window)
        observe_gui_runtime(INTERNAL_MDI_TEARDOWN_MODE)
        self.assertTrue(all(window in mdi_area.subWindowList() for window in created_subwindows))
