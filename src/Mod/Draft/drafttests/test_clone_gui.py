# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2026 OpenFusion contributors                            *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

"""GUI regressions for deferred Draft Clone formatting."""

import sys
import time
import unittest
from unittest import mock

import Draft
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from draftmake.make_clone import _deferred_format_object
from draftutils import gui_utils

try:
    import Arch
except ImportError:
    Arch = None


class DraftCloneGui(unittest.TestCase):
    """Verify deferred clone presentation respects document lifetimes."""

    def setUp(self):
        self.document_name = None
        Gui.activateWorkbench("DraftWorkbench")
        self._drain_events()
        self.assertTrue(hasattr(Gui, "draftToolBar"))

    def tearDown(self):
        if self.document_name:
            try:
                App.closeDocument(self.document_name)
            except NameError:
                pass
            self.document_name = None
        self._drain_events()

    def _new_document(self):
        name = f"DraftCloneGui_{self._testMethodName}"
        try:
            App.closeDocument(name)
        except NameError:
            pass
        self.document_name = name
        return App.newDocument(name)

    @staticmethod
    def _pump_until(predicate, timeout_seconds=2.0):
        deadline = time.monotonic() + timeout_seconds
        while not predicate() and time.monotonic() < deadline:
            QtCore.QCoreApplication.processEvents(QtCore.QEventLoop.AllEvents, 50)
        return predicate()

    @classmethod
    def _drain_events(cls):
        sentinel = []
        QtCore.QTimer.singleShot(0, lambda: sentinel.append(True))
        cls._pump_until(lambda: sentinel)

    def _assert_deleted_clone_callback_is_safe(self, source, expected_clone_of=None):
        errors = []
        formatter_call_states = []
        sentinel = []
        close_document_returned = False
        original_hook = sys.excepthook
        original_formatter = gui_utils.format_object

        def record_exception(exception_type, exception, traceback):
            errors.append((exception_type, exception, traceback))

        def record_formatter_call(target, origin):
            formatter_call_states.append(close_document_returned)
            return original_formatter(target, origin)

        sys.excepthook = record_exception
        try:
            with mock.patch.object(
                gui_utils, "format_object", side_effect=record_formatter_call
            ):
                clone = Draft.make_clone(source)
                self.assertIsNotNone(clone)
                if expected_clone_of is not None:
                    self.assertEqual(clone.CloneOf, expected_clone_of)

                App.closeDocument(self.document_name)
                close_document_returned = True
                self.document_name = None
                QtCore.QTimer.singleShot(0, lambda: sentinel.append(True))
                completed = self._pump_until(lambda: formatter_call_states and sentinel)
        finally:
            sys.excepthook = original_hook

        self.assertTrue(completed, "Deferred formatting did not run before the timeout")
        self.assertEqual(
            formatter_call_states,
            [True],
            "Deferred formatting must run exactly once after closeDocument returns",
        )
        self.assertEqual(
            sentinel, [True], "A stale clone callback stopped the Qt event queue"
        )
        self.assertEqual(
            errors,
            [],
            "A stale clone callback reached sys.excepthook: "
            + "; ".join(f"{kind.__name__}: {error}" for kind, error, _tb in errors),
        )

    @unittest.skipIf(Arch is None, "BIM module is unavailable")
    def test_bim_clone_deleted_before_deferred_formatting(self):
        """Closing a BIM clone document must make queued formatting a no-op."""
        document = self._new_document()
        source = Arch.makeBuildingPart(name="BIM source")
        document.recompute()

        self._assert_deleted_clone_callback_is_safe(source, expected_clone_of=source)

    def test_draft_clone_deleted_before_deferred_formatting(self):
        """Closing a normal clone document must make queued formatting a no-op."""
        document = self._new_document()
        source = document.addObject("Part::Box", "Source")
        document.recompute()

        self._assert_deleted_clone_callback_is_safe(source)

    def test_live_clone_receives_delayed_diffuse_color(self):
        """The lifetime guard must preserve delayed per-face presentation."""
        document = self._new_document()
        source = document.addObject("Part::Box", "Source")
        document.recompute()
        source.ViewObject.DiffuseColor = [
            (1.0, 0.0, 0.0, 1.0),
            (0.0, 1.0, 0.0, 1.0),
            (0.0, 0.0, 1.0, 1.0),
            (1.0, 1.0, 0.0, 1.0),
            (1.0, 0.0, 1.0, 1.0),
            (0.0, 1.0, 1.0, 1.0),
        ]
        source.ViewObject.Visibility = False

        clone = Draft.make_clone(source)
        document.recompute()
        self._drain_events()

        self.assertEqual(
            tuple(clone.ViewObject.DiffuseColor),
            tuple(source.ViewObject.DiffuseColor),
        )

    def test_deferred_formatter_propagates_unexpected_exception(self):
        """Deleted wrappers are the only formatting exception safe to suppress."""
        with mock.patch.object(
            gui_utils,
            "format_object",
            side_effect=RuntimeError("unexpected formatting failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "unexpected formatting failure"):
                _deferred_format_object(object(), object())

        with mock.patch.object(
            gui_utils,
            "format_object",
            side_effect=ReferenceError("live-object formatting failure"),
        ):
            with self.assertRaisesRegex(
                ReferenceError, "live-object formatting failure"
            ):
                _deferred_format_object(object(), object())
