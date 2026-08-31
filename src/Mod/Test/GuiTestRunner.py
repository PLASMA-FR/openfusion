# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fail-closed diagnostics for the internal GUI unittest callback."""

from __future__ import annotations

import sys
import traceback
import unicodedata
from collections.abc import Callable
from typing import Any, TypeVar


_Result = TypeVar("_Result")
_ExceptionInfo = tuple[type[BaseException], BaseException, Any]
_MAXIMUM_LOG_FIELD_LENGTH = 256
_MAXIMUM_WIDGET_RECORDS = 128
_MAXIMUM_WIDGET_REPORT_BYTES = 32 * 1024


def is_full_gui_test_selection(test_case: str) -> bool:
    """Return whether a selection denotes the complete GUI suite."""

    return test_case in {"0", "TestApp.All"}


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


def sanitize_log_field(value: Any) -> str:
    """Return a bounded, quoted-field-safe representation without addresses."""

    try:
        text = str(value)
    except BaseException:
        return "<unavailable>"

    truncated = len(text) > _MAXIMUM_LOG_FIELD_LENGTH
    text = text[:_MAXIMUM_LOG_FIELD_LENGTH]
    sanitized: list[str] = []
    for character in text:
        codepoint = ord(character)
        category = unicodedata.category(character)
        if character == "\\":
            sanitized.append("\\\\")
        elif character == '"':
            sanitized.append('\\"')
        elif category in {"Cc", "Cf", "Cs", "Zl", "Zp"}:
            escape = "u" if codepoint <= 0xFFFF else "U"
            width = 4 if codepoint <= 0xFFFF else 8
            sanitized.append(f"\\{escape}{codepoint:0{width}x}")
        else:
            sanitized.append(character)
    if truncated:
        sanitized.append("...")
    return "".join(sanitized)


def _safe_widget_value(callback: Callable[[], Any]) -> Any:
    try:
        return callback()
    except BaseException:
        return "<unavailable>"


def format_top_level_widget_inventory(widgets: Any, main_window: Any) -> str:
    """Format deterministic, pointer-free top-level widget lifecycle diagnostics."""

    total = len(widgets)
    records: list[str] = []
    for index, widget in enumerate(widgets):
        if index >= _MAXIMUM_WIDGET_RECORDS:
            break
        class_name = _safe_widget_value(lambda: widget.metaObject().className())
        object_name = _safe_widget_value(lambda: widget.objectName())
        title = _safe_widget_value(lambda: widget.windowTitle())
        visible = _safe_widget_value(lambda: widget.isVisible())
        record = (
            'OpenFusion top-level widget: class="{}" object="{}" title="{}" '
            "visible={} main={} delete_pending=unavailable"
        ).format(
            sanitize_log_field(class_name),
            sanitize_log_field(object_name),
            sanitize_log_field(title),
            "yes" if visible is True else "no" if visible is False else "unavailable",
            "yes" if widget is main_window else "no",
        )
        records.append(record)
    records.sort()

    emitted: list[str] = []
    body_bytes = 0
    maximum_body_bytes = _MAXIMUM_WIDGET_REPORT_BYTES - 512
    for record in records:
        record_bytes = len((record + "\n").encode("utf-8", errors="replace"))
        if body_bytes + record_bytes > maximum_body_bytes:
            break
        emitted.append(record)
        body_bytes += record_bytes

    omitted = total - len(emitted)
    header = (
        "OpenFusion top-level widget inventory: total={} emitted={} omitted={} truncated={}\n"
    ).format(
        total,
        len(emitted),
        omitted,
        "yes" if omitted else "no",
    )
    report = header + "\n".join(emitted)
    if emitted:
        report += "\n"
    return report


def _default_inventory_mirror() -> Callable[[str], Any]:
    import FreeCAD

    return FreeCAD.Console.PrintLog


def report_top_level_widgets(
    *,
    main_window: Any = None,
    widgets: Any = None,
    stderr: Any = None,
    mirror: Callable[[str], Any] | None = None,
) -> None:
    """Report internal full-suite top-level widgets without changing test behavior."""

    try:
        if widgets is None:
            from PySide import QtWidgets

            widgets = QtWidgets.QApplication.topLevelWidgets()
        if main_window is None:
            import FreeCADGui

            main_window = FreeCADGui.getMainWindow()
        report = format_top_level_widget_inventory(
            widgets,
            main_window,
        )
    except BaseException:
        report = "OpenFusion top-level widget inventory: unavailable\n"

    if mirror is None:
        try:
            mirror = _default_inventory_mirror()
        except BaseException:
            mirror = None

    try:
        output = sys.stderr if stderr is None else stderr
        if output is not None:
            output.write(report)
            output.flush()
    except BaseException:
        pass
    if mirror is not None:
        try:
            mirror(report)
        except BaseException:
            pass


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
