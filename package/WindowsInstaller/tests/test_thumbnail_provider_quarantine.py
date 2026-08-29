"""Static release guard for the unaudited inherited Windows thumbnail provider."""

import hashlib
from pathlib import Path
import unittest


INSTALLER_ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".bat", ".md", ".nsh", ".nsi", ".txt"}
PROVIDER_BINARY = INSTALLER_ROOT / "thumbnail" / "FCStdThumbnail.dll"
INHERITED_PROVIDER_SHA256 = (
    "cf9985aca43c116fe3565436a9da267de8b7f17ceed8c0cae000cfb40e69a1b0"
)


def installer_text_files():
    return sorted(
        path
        for path in INSTALLER_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
        and "tests" not in path.relative_to(INSTALLER_ROOT).parts
    )


class ThumbnailProviderQuarantineTest(unittest.TestCase):
    def test_inherited_provider_binary_is_not_packaged(self):
        self.assertFalse(
            PROVIDER_BINARY.exists(),
            f"remove unaudited prebuilt COM server: {PROVIDER_BINARY}",
        )

        for candidate in INSTALLER_ROOT.rglob("*.dll"):
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            with self.subTest(candidate=candidate.relative_to(INSTALLER_ROOT)):
                self.assertNotEqual(
                    INHERITED_PROVIDER_SHA256,
                    digest,
                    "inherited provider was reintroduced under another filename",
                )

    def test_installer_has_no_thumbnail_provider_actions(self):
        forbidden = {
            "FCStdThumbnail": "inherited provider filename or component name",
            "FILES_THUMBS": "inherited provider input directory",
            "{4BBBEAB5-BE00-41F4-A209-FE838660B9B1}": "inherited provider CLSID",
            "{E357FCCD-A995-4576-B01F-234630154E96}": "thumbnail-handler interface",
        }

        for path in installer_text_files():
            contents = path.read_text(encoding="utf-8-sig").upper()
            for fragment, description in forbidden.items():
                with self.subTest(path=path.relative_to(INSTALLER_ROOT), fragment=fragment):
                    self.assertNotIn(fragment.upper(), contents, description)

    def test_fcstd_open_and_icon_association_remains(self):
        configure = (INSTALLER_ROOT / "setup" / "configure.nsh").read_text(
            encoding="utf-8-sig"
        )
        uninstall = (INSTALLER_ROOT / "setup" / "uninstall.nsh").read_text(
            encoding="utf-8-sig"
        )
        required_install = (
            'WriteRegStr SHCTX "Software\\Classes\\${APP_REGNAME_DOC}\\DefaultIcon"',
            'WriteRegStr SHCTX "Software\\Classes\\${APP_REGNAME_DOC}\\Shell\\open\\command"',
            'WriteRegStr SHCTX "Software\\Classes\\${APP_EXT}" "" "${APP_REGNAME_DOC}"',
        )

        for association in required_install:
            with self.subTest(association=association):
                self.assertIn(association, configure)

        required_uninstall = (
            'ReadRegStr $R0 SHCTX "Software\\Classes\\${APP_EXT}" ""',
            '$R0 == "${APP_REGNAME_DOC}"',
            'DeleteRegKey SHCTX "Software\\Classes\\${APP_EXT}"',
        )

        for association in required_uninstall:
            with self.subTest(association=association):
                self.assertIn(association, uninstall)


if __name__ == "__main__":
    unittest.main()
