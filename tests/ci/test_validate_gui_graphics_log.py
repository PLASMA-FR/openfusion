#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / ".github" / "scripts" / "validate_gui_graphics_log.py"
SPEC = importlib.util.spec_from_file_location("validate_gui_graphics_log", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class ValidateGraphicsLogTest(unittest.TestCase):
    def test_accepts_clean_gui_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = Path(temporary_directory) / "gui.log"
            log.write_text(
                "OpenGL renderer initialized\nAll tests passed\n", encoding="utf-8"
            )

            self.assertEqual(
                validator.validate_graphics_log(log),
                (2, validator.GRAPHICS_FAILURE_SIGNATURE_COUNT),
            )

    def test_rejects_every_hard_graphics_failure_signature(self) -> None:
        signatures = (
            "This system is running OpenGL 1.1. FreeCAD requires OpenGL 2.0 or above.",
            "This system is running OpenGL 1.5. FreeCAD requires OpenGL 2.0 or above.",
            "QOpenGLWidget: Failed to create wrapper texture",
            "QOpenGLContext::makeCurrent() failed",
            "Failed to create a suitable OpenGL context",
            "Coin warning in cc_glglue_instance(): Error when setting up the GL context.",
            "The error message is: Access violation - no RTTI data!",
        )
        for signature in signatures:
            with self.subTest(
                signature=signature
            ), tempfile.TemporaryDirectory() as temporary_directory:
                log = Path(temporary_directory) / "gui.log"
                log.write_text(f"before\n{signature}\nafter\n", encoding="utf-8")

                with self.assertRaisesRegex(
                    validator.GraphicsLogError, "unusable context"
                ):
                    validator.validate_graphics_log(log)

    def test_accepts_each_recoverable_warning_alone_but_rejects_the_combination(
        self,
    ) -> None:
        warnings = (
            "The frame buffer has become invalid, a new frame buffer will be created",
            "Attempted to call beginFrame() within a still active frame; ignored",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = Path(temporary_directory) / "gui.log"
            for warning in warnings:
                with self.subTest(warning=warning):
                    log.write_text(f"before\n{warning}\nafter\n", encoding="utf-8")
                    validator.validate_graphics_log(log)
            log.write_text("\n".join(warnings) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(validator.GraphicsLogError, "frame lifecycle"):
                validator.validate_graphics_log(log)

    def test_accepts_supported_and_similar_non_failure_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = Path(temporary_directory) / "gui.log"
            log.write_text(
                "This system is running OpenGL 2.1.\n"
                "Documentation: QOpenGLWidget wrapper texture initialized\n",
                encoding="utf-8",
            )
            validator.validate_graphics_log(log)

    def test_rejects_missing_or_empty_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = Path(temporary_directory) / "gui.log"
            with self.assertRaisesRegex(validator.GraphicsLogError, "Cannot read"):
                validator.validate_graphics_log(log)
            log.touch()
            with self.assertRaisesRegex(validator.GraphicsLogError, "empty"):
                validator.validate_graphics_log(log)
            log.write_text(" \n\t\n", encoding="utf-8")
            with self.assertRaisesRegex(validator.GraphicsLogError, "empty"):
                validator.validate_graphics_log(log)


if __name__ == "__main__":
    unittest.main()
