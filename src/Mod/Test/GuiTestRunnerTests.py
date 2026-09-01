# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests for fail-closed internal GUI unittest diagnostics."""

from __future__ import annotations

import unittest
from unittest import mock

import GuiTestRunner
from GuiTestRunner import (
    format_top_level_widget_inventory,
    is_full_gui_test_selection,
    report_top_level_widgets,
    run_test_with_diagnostics,
    sanitize_log_field,
)


class _RecordingStream:
    def __init__(self) -> None:
        self.contents: list[str] = []
        self.flush_count = 0

    def write(self, text: str) -> None:
        self.contents.append(text)

    def flush(self) -> None:
        self.flush_count += 1


class _ClosedStream:
    def __init__(self, flush_error: BaseException) -> None:
        self.flush_error = flush_error
        self.flush_count = 0

    def write(self, _text: str) -> None:
        raise ValueError("diagnostic stream is closed")

    def flush(self) -> None:
        self.flush_count += 1
        raise self.flush_error


class _BufferedFlushFailure:
    def __init__(self, flush_error: BaseException) -> None:
        self.pending: list[str] = []
        self.flush_error = flush_error
        self.flush_count = 0

    def write(self, text: str) -> None:
        self.pending.append(text)

    def flush(self) -> None:
        self.flush_count += 1
        raise self.flush_error


class _HiddenRunnerFailure(RuntimeError):
    pass


class _MetaObject:
    def __init__(self, class_name: str) -> None:
        self.class_name = class_name

    def className(self) -> str:
        return self.class_name


class _Widget:
    def __init__(
        self, class_name: str, object_name: str, title: str, visible: bool
    ) -> None:
        self.meta = _MetaObject(class_name)
        self.object_name = object_name
        self.title = title
        self.visible = visible

    def metaObject(self) -> _MetaObject:
        return self.meta

    def objectName(self) -> str:
        return self.object_name

    def windowTitle(self) -> str:
        return self.title

    def isVisible(self) -> bool:
        return self.visible


class _DeletedWidget:
    def __getattribute__(self, _name: str):
        raise RuntimeError("wrapped C++ object was deleted")


class GuiTestRunnerDiagnosticsTests(unittest.TestCase):
    def test_full_gui_selection_accepts_canonical_and_command_line_names(self) -> None:
        self.assertTrue(is_full_gui_test_selection("TestApp.All"))
        self.assertTrue(is_full_gui_test_selection("0"))
        self.assertFalse(is_full_gui_test_selection("TestPartGui"))

    def test_log_field_sanitizer_escapes_controls_and_bounds_input(self) -> None:
        value = '\t\x1b\x00\u0085\u2028\u2029"\\' + "a" * 300
        sanitized = sanitize_log_field(value)

        self.assertTrue(
            sanitized.startswith('\\u0009\\u001b\\u0000\\u0085\\u2028\\u2029\\"\\\\')
        )
        self.assertTrue(sanitized.endswith("..."))
        self.assertNotIn("\x00", sanitized)
        self.assertLessEqual(len(sanitized), 310)

    def test_widget_inventory_is_sorted_escaped_and_pointer_free(self) -> None:
        main = _Widget("MainWindow", "main", "OpenFusion", True)
        dialog = _Widget("QDialog", 'bad\n"name', "title\x1b", False)

        inventory = format_top_level_widget_inventory([dialog, main], main)

        self.assertTrue(
            inventory.startswith(
                "OpenFusion top-level widget inventory: total=2 emitted=2 omitted=0 truncated=no\n"
            )
        )
        self.assertIn('object="bad\\u000a\\"name"', inventory)
        self.assertIn('title="title\\u001b"', inventory)
        self.assertIn("visible=yes main=yes delete_pending=unavailable", inventory)
        self.assertNotIn("0x", inventory)

    def test_widget_inventory_guards_deleted_wrappers(self) -> None:
        inventory = format_top_level_widget_inventory([_DeletedWidget()], object())

        self.assertIn('class="<unavailable>"', inventory)
        self.assertIn('object="<unavailable>"', inventory)
        self.assertIn('title="<unavailable>"', inventory)
        self.assertIn("visible=unavailable", inventory)

    def test_widget_inventory_caps_records_and_total_bytes(self) -> None:
        widgets = [
            _Widget("QDialog", f"widget-{index}", "界" * 300, bool(index % 2))
            for index in range(180)
        ]

        inventory = format_top_level_widget_inventory(widgets, object())
        header = inventory.splitlines()[0]
        fields = dict(field.split("=", 1) for field in header.split(": ", 1)[1].split())

        self.assertEqual(fields["total"], "180")
        self.assertEqual(fields["truncated"], "yes")
        self.assertGreater(int(fields["omitted"]), 0)
        self.assertLessEqual(int(fields["emitted"]), 128)
        self.assertLessEqual(len(inventory.encode("utf-8")), 32 * 1024)

    def test_widget_inventory_survives_default_mirror_lookup_failure(self) -> None:
        output = _RecordingStream()
        widget = _Widget("QDialog", "dialog", "Diagnostic", True)

        with mock.patch.object(
            GuiTestRunner,
            "_default_inventory_mirror",
            side_effect=RuntimeError("mirror unavailable"),
        ):
            report_top_level_widgets(
                main_window=object(),
                widgets=[widget],
                stderr=output,
            )

        self.assertIn(
            "total=1 emitted=1 omitted=0 truncated=no", "".join(output.contents)
        )

    def test_widget_inventory_mirrors_unavailable_acquisition(self) -> None:
        output = _RecordingStream()
        mirror: list[str] = []

        report_top_level_widgets(
            main_window=object(),
            widgets=object(),
            stderr=output,
            mirror=mirror.append,
        )

        self.assertEqual(
            "".join(output.contents),
            "OpenFusion top-level widget inventory: unavailable\n",
        )
        self.assertEqual(
            mirror, ["OpenFusion top-level widget inventory: unavailable\n"]
        )

    def test_non_system_exception_keeps_identity_and_full_traceback(self) -> None:
        output = _RecordingStream()
        errors = _RecordingStream()
        failure = _HiddenRunnerFailure("hidden callback failure")

        def fail() -> None:
            raise failure

        with self.assertRaises(_HiddenRunnerFailure) as raised:
            run_test_with_diagnostics(fail, stdout=output, stderr=errors)

        self.assertIs(raised.exception, failure)
        diagnostic = "".join(errors.contents)
        self.assertIn("Traceback (most recent call last):", diagnostic)
        self.assertIn("raise failure", diagnostic)
        self.assertIn("_HiddenRunnerFailure: hidden callback failure", diagnostic)
        self.assertEqual(output.flush_count, 1)
        self.assertEqual(errors.flush_count, 2)

    def test_closed_error_stream_uses_fallback_without_replacing_failure(self) -> None:
        flush_failure = OSError("closed stream flush")
        errors = _ClosedStream(flush_failure)
        fallback: list[str] = []
        failure = _HiddenRunnerFailure("preserve this failure")

        def fail() -> None:
            raise failure

        with self.assertRaises(_HiddenRunnerFailure) as raised:
            run_test_with_diagnostics(
                fail,
                stdout=_RecordingStream(),
                stderr=errors,
                fallback=fallback.append,
            )

        self.assertIs(raised.exception, failure)
        self.assertEqual(errors.flush_count, 1)
        self.assertEqual(len(fallback), 1)
        self.assertIn("_HiddenRunnerFailure: preserve this failure", fallback[0])

    def test_buffered_write_with_failed_flush_uses_fallback(self) -> None:
        flush_failure = OSError("buffered diagnostic could not flush")
        errors = _BufferedFlushFailure(flush_failure)
        fallback: list[str] = []
        failure = _HiddenRunnerFailure("buffered callback failure")

        def fail() -> None:
            raise failure

        with self.assertRaises(_HiddenRunnerFailure) as raised:
            run_test_with_diagnostics(
                fail,
                stdout=_RecordingStream(),
                stderr=errors,
                fallback=fallback.append,
            )

        self.assertIs(raised.exception, failure)
        self.assertEqual(errors.flush_count, 2)
        self.assertEqual(len(fallback), 1)
        self.assertIn("_HiddenRunnerFailure: buffered callback failure", fallback[0])

    def test_flush_failure_remains_fatal_after_success(self) -> None:
        flush_failure = OSError("successful callback could not flush")
        output = _ClosedStream(flush_failure)

        with self.assertRaises(OSError) as raised:
            run_test_with_diagnostics(
                lambda: True,
                stdout=output,
                stderr=_RecordingStream(),
            )

        self.assertIs(raised.exception, flush_failure)

    def test_ambient_exception_does_not_hide_successful_callback_flush_failure(
        self,
    ) -> None:
        flush_failure = OSError("outer handler flush failure")
        output = _ClosedStream(flush_failure)

        try:
            raise LookupError("ambient exception")
        except LookupError:
            with self.assertRaises(OSError) as raised:
                run_test_with_diagnostics(
                    lambda: True,
                    stdout=output,
                    stderr=_RecordingStream(),
                )

        self.assertIs(raised.exception, flush_failure)

    def test_system_exit_is_reported_and_preserved(self) -> None:
        errors = _RecordingStream()
        failure = SystemExit(19)

        def fail() -> None:
            raise failure

        with self.assertRaises(SystemExit) as raised:
            run_test_with_diagnostics(
                fail,
                stdout=_RecordingStream(),
                stderr=errors,
            )

        self.assertIs(raised.exception, failure)
        self.assertIn("SystemExit: 19", "".join(errors.contents))
