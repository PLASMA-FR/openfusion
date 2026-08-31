# SPDX-License-Identifier: LGPL-2.1-or-later
"""Acceptance test executed by the extracted Windows portable GUI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
import sys
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets


class OpenFusionPortableWindowsAcceptanceTest(unittest.TestCase):
    def test_relocated_gui_python_ssl_qt_and_document_round_trip(self) -> None:
        root = Path(os.environ["OPENFUSION_PORTABLE_ROOT"]).resolve()
        output = Path(os.environ["OPENFUSION_ACCEPTANCE_OUTPUT_DIR"]).resolve()
        output.mkdir(parents=True, exist_ok=True)

        def require_below(value, label):
            resolved = Path(value).resolve()
            self.assertTrue(resolved.is_relative_to(root), f"{label} escaped package: {resolved}")
            return resolved

        require_below(App.getHomePath(), "OpenFusion home")
        require_below(Part.__file__, "Part extension")
        require_below(ssl.__file__, "ssl module")
        require_below(sys.executable, "embedded Python")
        self.assertEqual(Path(os.environ["OPENSSL_CONF"]).resolve(), root / "ssl" / "openssl.cnf")
        self.assertTrue(ssl.OPENSSL_VERSION.startswith("OpenSSL "))
        ssl.create_default_context()

        self.assertIsNotNone(QtWidgets.QApplication.instance())
        plugin_paths = [Path(path).resolve() for path in QtCore.QCoreApplication.libraryPaths()]
        self.assertIn(root / "plugins", plugin_paths)
        self.assertTrue(all(path.is_relative_to(root) for path in plugin_paths))
        self.assertIsNotNone(Gui.getMainWindow())
        Gui.updateGui()

        document = App.newDocument("PortableRoundTrip")
        feature = document.addObject("PartDesign::Feature", "PortableBox")
        feature.Shape = Part.makeBox(11.0, 7.0, 3.0)
        document.recompute()
        self.assertAlmostEqual(feature.Shape.Volume, 231.0, places=7)
        destination = output / "OpenFusionPortableRoundTrip.FCStd"
        document.saveAs(str(destination))
        self.assertGreater(destination.stat().st_size, 0)
        App.closeDocument(document.Name)

        reopened = App.openDocument(str(destination))
        reopened.recompute()
        restored = reopened.getObject("PortableBox")
        self.assertIsNotNone(restored)
        self.assertAlmostEqual(restored.Shape.Volume, 231.0, places=7)
        App.closeDocument(reopened.Name)

        evidence = {
            "document": str(destination),
            "home": App.getHomePath(),
            "openssl": ssl.OPENSSL_VERSION,
            "plugins": [str(path) for path in plugin_paths],
            "python": sys.executable,
            "qt": QtCore.qVersion(),
        }
        (output / "OpenFusionPortableWindowsAcceptance.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
