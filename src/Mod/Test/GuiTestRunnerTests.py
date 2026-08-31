# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests for fail-closed internal GUI unittest diagnostics."""

from __future__ import annotations

import unittest

from GuiTestRunner import run_test_with_diagnostics


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


class GuiTestRunnerDiagnosticsTests(unittest.TestCase):
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
