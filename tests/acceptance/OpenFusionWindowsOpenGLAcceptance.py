# SPDX-License-Identifier: LGPL-2.1-or-later
"""Verify the exact software OpenGL module loaded by the Windows GUI process."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import unittest

from PySide import QtGui


GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02


def _loaded_module_path(name: str) -> Path | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleFileNameW.argtypes = [
        wintypes.HMODULE,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    kernel32.GetModuleFileNameW.restype = wintypes.DWORD
    handle = kernel32.GetModuleHandleW(name)
    if not handle:
        return None
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetModuleFileNameW(handle, buffer, len(buffer))
    if length == 0 or length >= len(buffer):
        raise OSError(ctypes.get_last_error(), f"Cannot resolve loaded module {name}")
    return Path(buffer.value).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class OpenFusionWindowsOpenGLAcceptanceTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows-only OpenGL runtime evidence")
    def test_staged_renderer_is_the_only_loaded_opengl_implementation(self) -> None:
        expected_path = Path(os.environ["OPENFUSION_STAGED_OPENGL_PATH"]).resolve()
        expected_digest = os.environ["OPENFUSION_STAGED_OPENGL_SHA256"].casefold()
        package = os.environ["OPENFUSION_STAGED_OPENGL_PACKAGE"]
        self.assertEqual(os.environ.get("QT_OPENGL"), "desktop")

        surface = QtGui.QOffscreenSurface()
        surface.setFormat(QtGui.QSurfaceFormat.defaultFormat())
        surface.create()
        self.assertTrue(surface.isValid(), "QOffscreenSurface creation failed")
        context = QtGui.QOpenGLContext()
        context.setFormat(surface.requestedFormat())
        self.assertTrue(context.create(), "QOpenGLContext creation failed")
        self.assertTrue(
            context.makeCurrent(surface), "OpenGL context could not be made current"
        )
        try:
            loaded_path = _loaded_module_path("opengl32.dll")
            self.assertIsNotNone(loaded_path, "opengl32.dll was not loaded")
            assert loaded_path is not None
            self.assertEqual(
                os.path.normcase(str(loaded_path)),
                os.path.normcase(str(expected_path)),
            )
            self.assertIsNone(
                _loaded_module_path("opengl32sw.dll"),
                "Qt loaded a second software OpenGL module",
            )
            loaded_digest = _sha256(loaded_path)
            self.assertEqual(loaded_digest, expected_digest)

            opengl = ctypes.WinDLL(str(loaded_path))
            opengl.glGetString.argtypes = [ctypes.c_uint]
            opengl.glGetString.restype = ctypes.c_char_p
            version_bytes = opengl.glGetString(GL_VERSION)
            renderer_bytes = opengl.glGetString(GL_RENDERER)
            self.assertIsNotNone(version_bytes, "GL_VERSION was unavailable")
            self.assertIsNotNone(renderer_bytes, "GL_RENDERER was unavailable")
            version = version_bytes.decode("utf-8", errors="replace")
            renderer = renderer_bytes.decode("utf-8", errors="replace")
            version_match = re.match(r"(\d+)\.(\d+)", version)
            self.assertIsNotNone(
                version_match, f"Unparseable OpenGL version: {version}"
            )
            assert version_match is not None
            self.assertGreaterEqual(
                (int(version_match.group(1)), int(version_match.group(2))),
                (2, 0),
            )
        finally:
            context.doneCurrent()

        evidence = {
            "loaded_module": str(loaded_path),
            "loaded_sha256": loaded_digest,
            "opengl32sw_loaded": False,
            "package": package,
            "qt_opengl": os.environ["QT_OPENGL"],
            "renderer": renderer,
            "version": version,
        }
        output_directory = Path(os.environ["OPENFUSION_ACCEPTANCE_OUTPUT_DIR"])
        output_directory.mkdir(parents=True, exist_ok=True)
        destination = output_directory / "WindowsOpenGLRuntime.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        print(
            "Windows OpenGL runtime: " + json.dumps(evidence, sort_keys=True),
            flush=True,
        )


if __name__ == "__main__":
    unittest.main()
