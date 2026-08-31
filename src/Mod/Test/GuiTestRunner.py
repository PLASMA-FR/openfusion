# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fail-closed diagnostics for the internal GUI unittest callback."""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from typing import Any, TypeVar


_Result = TypeVar("_Result")
_ExceptionInfo = tuple[type[BaseException], BaseException, Any]


def _format_exception(exception_info: _ExceptionInfo) -> str:
    try:
        return "".join(traceback.format_exception(*exception_info))
    except BaseException:
        exception_type, exception, _traceback = exception_info
        try:
            return f"{exception_type.__name__}: {exception!s}\n"
        except BaseException:
            return "Internal GUI test callback raised an exception that could not be formatted\n"


def _write_exception(
    exception_info: _ExceptionInfo,
    error_stream: Any,
    fallback: Callable[[str], Any] | None,
) -> None:
    diagnostic = _format_exception(exception_info)
    try:
        if error_stream is None:
            raise RuntimeError("the original error stream is unavailable")
        error_stream.write(diagnostic)
        error_stream.flush()
        return
    except BaseException:
        pass

    if fallback is not None:
        try:
            fallback(diagnostic)
        except BaseException:
            pass


def _flush_streams(streams: tuple[Any, ...]) -> BaseException | None:
    seen: set[int] = set()
    first_error: BaseException | None = None
    for stream in streams:
        if stream is None or id(stream) in seen:
            continue
        seen.add(id(stream))
        try:
            flush = getattr(stream, "flush", None)
            if flush is not None:
                flush()
        except BaseException as error:
            if first_error is None:
                first_error = error
    return first_error


def run_test_with_diagnostics(
    run_test: Callable[[], _Result],
    *,
    stdout: Any = None,
    stderr: Any = None,
    fallback: Callable[[str], Any] | None = None,
) -> _Result:
    """Run a GUI test callback while retaining its original failure and output.

    The streams are captured before the callback because tests may replace or close
    ``sys.stdout`` and ``sys.stderr``. A flush failure remains fatal after a successful
    callback, but it never replaces an exception already raised by the callback.
    """

    original_stdout = sys.stdout if stdout is None else stdout
    original_stderr = sys.stderr if stderr is None else stderr
    callback_failed = False
    try:
        return run_test()
    except BaseException:
        callback_failed = True
        exception_info = sys.exc_info()
        _write_exception(exception_info, original_stderr, fallback)
        raise
    finally:
        flush_error = _flush_streams(
            (original_stdout, original_stderr, sys.stdout, sys.stderr)
        )
        if flush_error is not None and not callback_failed:
            raise flush_error
