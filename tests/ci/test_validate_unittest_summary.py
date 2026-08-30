#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / ".github" / "scripts" / "validate_unittest_summary.py"
SPEC = importlib.util.spec_from_file_location("validate_unittest_summary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


class ValidateUnittestSummaryTest(unittest.TestCase):
    def test_accepts_decimal_singular_summary(self) -> None:
        self.assertEqual(summary.validate_unittest_summary("Ran 1 test in 0.125s\n"), 1)

    def test_accepts_integer_and_scientific_plural_summaries(self) -> None:
        for duration in ("3", "2.64e+02", "4E-03"):
            with self.subTest(duration=duration):
                self.assertEqual(
                    summary.validate_unittest_summary(f"Ran 12 tests in {duration}s\n"),
                    12,
                )

    def test_uses_latest_valid_summary(self) -> None:
        output = (
            "Ran 2 tests in 1s\n"
            "intermediate diagnostics\n"
            "Ran 7 tests in 2.64E+02s\n"
        )

        self.assertEqual(summary.validate_unittest_summary(output), 7)

    def test_rejects_expected_count_mismatch(self) -> None:
        with self.assertRaisesRegex(
            summary.SummaryValidationError, "reported 2 tests; expected 1"
        ):
            summary.validate_unittest_summary("Ran 2 tests in 0.2s\n", expected_count=1)

    def test_rejects_zero_count(self) -> None:
        with self.assertRaisesRegex(summary.SummaryValidationError, "zero tests"):
            summary.validate_unittest_summary("Ran 0 tests in 0s\n")

    def test_rejects_missing_summary(self) -> None:
        with self.assertRaisesRegex(summary.SummaryValidationError, "No anchored"):
            summary.validate_unittest_summary("test output without a summary\n")

    def test_rejects_malformed_summary_and_trailing_junk(self) -> None:
        malformed = (
            "Ran many tests in 1s",
            "Ran 3 tests in 1.2.3s",
            "Ran 3 tests in 1s unexpected",
            "Ran 3 tests in 1s Ran 4 tests in 2s",
        )
        for output in malformed:
            with self.subTest(output=output):
                with self.assertRaisesRegex(
                    summary.SummaryValidationError, "Malformed unittest summary"
                ):
                    summary.validate_unittest_summary(output)

    def test_rejects_nan_and_infinite_durations(self) -> None:
        for duration in ("NaN", "nan", "Inf", "infinity"):
            with self.subTest(duration=duration):
                with self.assertRaisesRegex(
                    summary.SummaryValidationError, "Malformed unittest summary"
                ):
                    summary.validate_unittest_summary(f"Ran 3 tests in {duration}s\n")

    def test_writes_validated_count_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            log = root / "runner.log"
            count_file = root / "diagnostics" / "count.txt"
            log.write_text("Ran 9 tests in 8e-01s\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                result = summary.main(
                    [str(log), "--count-file", str(count_file), "--label", "CLI"]
                )

            self.assertEqual(result, 0)
            self.assertEqual(count_file.read_text(encoding="utf-8"), "9\n")


if __name__ == "__main__":
    unittest.main()
