# SPDX-License-Identifier: LGPL-2.1-or-later

# **************************************************************************
#   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
#                                                                         *
#   This file is part of the FreeCAD CAx development system.              *
#                                                                         *
#   This program is free software; you can redistribute it and/or modify  *
#   it under the terms of the GNU Lesser General Public License (LGPL)    *
#   as published by the Free Software Foundation; either version 2 of     *
#   the License, or (at your option) any later version.                   *
#   for detail see the LICENCE text file.                                 *
#                                                                         *
#   FreeCAD is distributed in the hope that it will be useful,            *
#   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
#   GNU Library General Public License for more details.                  *
#                                                                         *
#   You should have received a copy of the GNU Library General Public     *
#   License along with FreeCAD; if not, write to the Free Software        *
#   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
#   USA                                                                   *
# **************************************************************************

import os
import sys
import unittest
import FreeCAD
import FreeCADGui
import Part
import PartGui
from PySide import QtCore, QtWidgets


def findDockWidget(name):
    """Get a dock widget by name"""
    mw = FreeCADGui.getMainWindow()
    dws = mw.findChildren(QtWidgets.QDockWidget)
    for dw in dws:
        if dw.objectName() == name:
            return dw
    return None


"""
#---------------------------------------------------------------------------
# define the test cases to test the FreeCAD Part module
#---------------------------------------------------------------------------
"""
from parttests.ColorPerFaceTest import ColorPerFaceTest
from parttests.ColorTransparencyTest import ColorTransparencyTest


# class PartGuiTestCases(unittest.TestCase):
#    def setUp(self):
#        self.Doc = FreeCAD.newDocument("PartGuiTest")
#
#    def testBoxCase(self):
#        self.Box = self.Doc.addObject('Part::SketchObject','SketchBox')
#        self.Box.addGeometry(Part.LineSegment(App.Vector(-99.230339,36.960674,0),App.Vector(69.432587,36.960674,0)))
#        self.Box.addGeometry(Part.LineSegment(App.Vector(69.432587,36.960674,0),App.Vector(69.432587,-53.196629,0)))
#        self.Box.addGeometry(Part.LineSegment(App.Vector(69.432587,-53.196629,0),App.Vector(-99.230339,-53.196629,0)))
#        self.Box.addGeometry(Part.LineSegment(App.Vector(-99.230339,-53.196629,0),App.Vector(-99.230339,36.960674,0)))
#
#    def tearDown(self):
#        #closing doc
#        FreeCAD.closeDocument("PartGuiTest")
class PartGuiViewProviderTestCases(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartGuiTest")

    def testCanDropObject(self):
        # https://github.com/FreeCAD/FreeCAD/pull/6850
        box = self.Doc.addObject("Part::Box", "Box")
        with self.assertRaises(TypeError):
            box.ViewObject.canDragObject(0)
        with self.assertRaises(TypeError):
            box.ViewObject.canDropObject(0)
        box.ViewObject.canDropObject()
        with self.assertRaises(TypeError):
            box.ViewObject.dropObject(box, 0)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartGuiTest")


class PartMirrorGuiTestCases(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartMirrorGuiTest")

    def tearDown(self):
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        FreeCADGui.Selection.clearSelection()
        FreeCAD.closeDocument(self.Doc.Name)

    def mirrorBoxWithLabel(self, label):
        if not FreeCAD.GuiUp:
            self.skipTest("This test requires a graphical user interface (GUI).")

        box = self.Doc.addObject("Part::Box", "Box")
        box.Label = label
        self.Doc.recompute()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.Doc.Name, box.Name)
        FreeCADGui.runCommand("Part_Mirror")
        self.assertTrue(FreeCADGui.Control.activeDialog(), "Part Mirror task dialog did not open.")

        FreeCADGui.Control.activeTaskDialog().accept()
        QtWidgets.QApplication.processEvents()

        mirrors = [obj for obj in self.Doc.Objects if obj.isDerivedFrom("Part::Mirroring")]
        self.assertEqual(1, len(mirrors))
        return mirrors[0].Label

    def testMirrorLabelWithUnicodeIsNotDoubleEscaped(self):
        self.assertEqual("caf\u00e9 (Mirror #1)", self.mirrorBoxWithLabel("caf\u00e9"))

    def testMirrorLabelEscapesQuotesBeforePythonCommand(self):
        label = 'a");print("Erasing your hard drive, please stand by....")'
        self.assertEqual(f"{label} (Mirror #1)", self.mirrorBoxWithLabel(label))

    def testMirrorLabelWithNewlinesIsNotMangled(self):
        label = "a\nb\nc"
        self.assertEqual(f"{label} (Mirror #1)", self.mirrorBoxWithLabel(label))


class SectionCutTestCases(unittest.TestCase):
    dock_name = "Section cutting"

    @staticmethod
    def _flushDockDeletion(dock):
        QtCore.QCoreApplication.sendPostedEvents(dock, QtCore.QEvent.DeferredDelete)
        QtWidgets.QApplication.processEvents()

    @classmethod
    def _closeSectionCutDock(cls):
        dock = findDockWidget(cls.dock_name)
        if not dock:
            return

        button_box = dock.findChild(QtWidgets.QDialogButtonBox)
        close_button = (
            button_box.button(QtWidgets.QDialogButtonBox.Close) if button_box else None
        )
        if close_button:
            close_button.click()
        else:
            dock.deleteLater()
        cls._flushDockDeletion(dock)

    def setUp(self):
        self.DocName = "SectionCut"
        self.Doc = None
        self._closeSectionCutDock()
        self.assertIsNone(
            findDockWidget(self.dock_name), "A stale Section Cut dock is open."
        )
        FreeCADGui.Selection.clearSelection()
        if self.DocName in FreeCAD.listDocuments():
            FreeCAD.closeDocument(self.DocName)
        self.Doc = FreeCAD.newDocument(self.DocName)

    def testOpenDialog(self):
        source_box = self.Doc.addObject("Part::Box", "SectionCutSource")
        self.Doc.recompute()
        source_box.ViewObject.Visibility = True
        QtWidgets.QApplication.processEvents()

        FreeCADGui.runCommand("Part_SectionCut")
        dock = findDockWidget(self.dock_name)
        self.assertIsNotNone(dock, "Part Section Cut dock did not open.")

        button_box = dock.findChild(QtWidgets.QDialogButtonBox)
        self.assertIsNotNone(button_box, "Part Section Cut dock has no button box.")
        close_button = button_box.button(QtWidgets.QDialogButtonBox.Close)
        self.assertIsNotNone(close_button, "Part Section Cut dock has no Close button.")
        close_button.click()
        self._flushDockDeletion(dock)
        self.assertIsNone(
            findDockWidget(self.dock_name), "Part Section Cut dock did not close."
        )

    def tearDown(self):
        try:
            self._closeSectionCutDock()
        finally:
            try:
                FreeCADGui.Selection.clearSelection()
            finally:
                if self.DocName in FreeCAD.listDocuments():
                    FreeCAD.closeDocument(self.DocName)
