# SPDX-License-Identifier: LGPL-2.1-or-later

"""GUI-backed full-page TechDraw SVG and PDF export acceptance."""

from collections import Counter
import math
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

import FreeCAD as App


try:
    import FreeCADGui as Gui
    import TechDrawGui
except ImportError as error:
    Gui = None
    TechDrawGui = None
    GUI_IMPORT_ERROR = error
else:
    GUI_IMPORT_ERROR = None

from PySide import QtCore

try:
    import pypdfium2 as pdfium
except ImportError as pdfium_error:
    pdfium = None
    PDFIUM_IMPORT_ERROR = pdfium_error
else:
    PDFIUM_IMPORT_ERROR = None


DOCUMENT_NAMES = (
    "OpenFusionCoreAcceptance",
    "OpenFusionTechDrawAcceptance",
)
GRAPHICAL_SVG_ELEMENTS = {
    "circle",
    "ellipse",
    "line",
    "path",
    "polygon",
    "polyline",
    "rect",
}
NONFINITE_NUMBER = re.compile(
    r"(?<![A-Za-z])[-+]?(?:nan|inf(?:inity)?)(?![A-Za-z])",
    re.IGNORECASE,
)
SVG_LENGTH = re.compile(
    r"^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s*([A-Za-z]*)\s*$"
)


def _configured_path(environment_name):
    value = os.environ.get(environment_name, "").strip()
    if not value:
        return None
    return Path(os.path.expandvars(value)).expanduser().resolve()


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _quantity_value(value):
    return float(getattr(value, "Value", value))


def _svg_length_in_mm(value):
    match = SVG_LENGTH.fullmatch(value or "")
    if not match:
        raise ValueError(f"Unsupported SVG length: {value!r}")

    number = float(match.group(1))
    unit = match.group(2).lower()
    factors = {
        "": 25.4 / 96.0,
        "px": 25.4 / 96.0,
        "pt": 25.4 / 72.0,
        "pc": 25.4 / 6.0,
        "mm": 1.0,
        "cm": 10.0,
        "in": 25.4,
    }
    if unit not in factors:
        raise ValueError(f"Unsupported SVG length unit: {unit!r}")
    return number * factors[unit]


class OpenFusionTechDrawGuiExportAcceptanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not App.GuiUp or Gui is None or TechDrawGui is None:
            raise AssertionError(
                "OpenFusion TechDraw GUI export acceptance requires the GUI executable; "
                f"GUI import error: {GUI_IMPORT_ERROR!r}"
            )
        if pdfium is None:
            raise AssertionError(
                "pypdfium2 is required for semantic PDF validation; "
                f"PDFium import error: {PDFIUM_IMPORT_ERROR!r}"
            )

    def setUp(self):
        for name in DOCUMENT_NAMES:
            if name in App.listDocuments():
                App.closeDocument(name)

        self.document = None
        self.temporary_directory = None

        configured_output = _configured_path("OPENFUSION_ACCEPTANCE_OUTPUT_DIR")
        fixture_override = _configured_path(
            "OPENFUSION_TECHDRAW_ACCEPTANCE_FIXTURE"
        )
        if configured_output is None and fixture_override is None:
            self.fail(
                "Set OPENFUSION_ACCEPTANCE_OUTPUT_DIR or "
                "OPENFUSION_TECHDRAW_ACCEPTANCE_FIXTURE"
            )

        if configured_output is None:
            self.temporary_directory = tempfile.TemporaryDirectory(
                prefix="openfusion-techdraw-gui-export-"
            )
            configured_output = Path(self.temporary_directory.name)

        self.fixture_path = fixture_override or (
            configured_output / "OpenFusionTechDrawAcceptance.FCStd"
        )
        self.export_directory = configured_output / "TechDrawGuiExport"
        self.export_directory.mkdir(parents=True, exist_ok=True)
        self.svg_path = self.export_directory / "OpenFusionTechDraw-full-page.svg"
        self.unicode_svg_path = (
            self.export_directory / "OpenFusion Δ 机 e\u0301 🚀 full-page.svg"
        )
        self.pdf_path = self.export_directory / "OpenFusionTechDraw-full-page.pdf"
        self.unicode_pdf_path = (
            self.export_directory / "OpenFusion Δ 机 e\u0301 🚀 full-page.pdf"
        )

        for path in (
            self.svg_path,
            self.unicode_svg_path,
            self.pdf_path,
            self.unicode_pdf_path,
        ):
            if path.exists():
                path.unlink()

        self.assertTrue(
            self.fixture_path.is_file(),
            "TechDraw acceptance fixture is missing; run "
            "OpenFusion_TechDraw_Acceptance first or set "
            "OPENFUSION_TECHDRAW_ACCEPTANCE_FIXTURE",
        )

    def tearDown(self):
        if self.document is not None and self.document.Name in App.listDocuments():
            page = self.document.getObject("DrawingPage")
            if page is not None and hasattr(page, "ViewObject"):
                page.ViewObject.hide()
                Gui.updateGui()
            App.closeDocument(self.document.Name)
            self.document = None

        for name in DOCUMENT_NAMES:
            if name in App.listDocuments():
                App.closeDocument(name)

        if self.temporary_directory is not None:
            self.temporary_directory.cleanup()
            self.temporary_directory = None

    @staticmethod
    def pumpGuiEvents(milliseconds=25):
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(milliseconds, loop.quit)
        execute = getattr(loop, "exec", None) or loop.exec_
        execute()

    def waitFor(self, description, predicate, timeout_seconds=30.0):
        deadline = time.monotonic() + timeout_seconds
        last_error = None
        while time.monotonic() < deadline:
            Gui.updateGui()
            self.pumpGuiEvents()
            try:
                if predicate():
                    return
            except Exception as error:  # The object can be transiently incomplete.
                last_error = error
        self.fail(f"Timed out waiting for {description}; last error: {last_error!r}")

    def finiteVisibleEdges(self, view):
        edges = view.getVisibleEdges(True)
        if not edges:
            return False

        for edge in edges:
            if edge.isNull() or not edge.isValid():
                return False
            if not math.isfinite(float(edge.Length)) or float(edge.Length) <= 0.0:
                return False
            box = edge.BoundBox
            coordinates = (
                box.XMin,
                box.YMin,
                box.ZMin,
                box.XMax,
                box.YMax,
                box.ZMax,
            )
            if not all(math.isfinite(value) for value in coordinates):
                return False
        return True

    def projectionIsReady(self, view):
        return "Up-to-date" in view.State and self.finiteVisibleEdges(view)

    def activeMdiShowsPage(self, page):
        gui_document = Gui.activeDocument()
        if gui_document is None:
            return False
        active_view = gui_document.activeView()
        if active_view is None or not hasattr(active_view, "getPage"):
            return False
        active_page = active_view.getPage()
        return active_page is not None and active_page.Name == page.Name

    def validateSvg(self, page, svg_path):
        self.assertTrue(svg_path.is_file())
        self.assertGreater(svg_path.stat().st_size, 500)
        svg_text = svg_path.read_text(encoding="utf-8")
        self.assertIsNone(
            NONFINITE_NUMBER.search(svg_text),
            "Full-page SVG contains a non-finite coordinate",
        )

        root = ET.fromstring(svg_text)
        self.assertEqual(_local_name(root.tag), "svg")
        try:
            width_mm = _svg_length_in_mm(root.attrib.get("width", ""))
            height_mm = _svg_length_in_mm(root.attrib.get("height", ""))
        except ValueError as error:
            self.fail(str(error))

        page_width = _quantity_value(page.PageWidth)
        page_height = _quantity_value(page.PageHeight)
        self.assertAlmostEqual(width_mm, page_width, delta=0.75)
        self.assertAlmostEqual(height_mm, page_height, delta=0.75)

        view_box = re.split(r"[\s,]+", root.attrib.get("viewBox", "").strip())
        self.assertEqual(len(view_box), 4, "SVG has no four-value viewBox")
        view_box_values = [float(value) for value in view_box]
        self.assertTrue(all(math.isfinite(value) for value in view_box_values))
        self.assertGreater(view_box_values[2], 0.0)
        self.assertGreater(view_box_values[3], 0.0)
        self.assertAlmostEqual(
            view_box_values[2] / view_box_values[3],
            page_width / page_height,
            delta=0.01,
        )

        page_layers = [
            element
            for element in root.iter()
            if element.attrib.get("id") == page.Name
        ]
        self.assertEqual(len(page_layers), 1, "SVG does not contain the page layer")
        page_layer = page_layers[0]
        drawing_layers = [
            element
            for element in page_layer.iter()
            if element.attrib.get("id") == "DrawingContent"
        ]
        self.assertEqual(
            len(drawing_layers),
            1,
            "SVG does not contain the full-page DrawingContent layer",
        )

        template_groups = [
            element
            for element in list(page_layer)
            if _local_name(element.tag) == "g"
            and element.attrib.get("id") != "DrawingContent"
        ]
        self.assertTrue(template_groups, "SVG does not contain the page template")

        drawing_elements = [
            element
            for element in drawing_layers[0].iter()
            if _local_name(element.tag) in GRAPHICAL_SVG_ELEMENTS
        ]
        self.assertTrue(
            drawing_elements,
            "SVG DrawingContent contains no projected graphical elements",
        )
        self.assertTrue(
            any(
                element.attrib.get("d", "").strip()
                or element.attrib.get("points", "").strip()
                or any(
                    attribute in element.attrib
                    for attribute in ("x1", "x2", "cx", "rx", "width")
                )
                for element in drawing_elements
            ),
            "SVG projected graphical elements contain no geometry",
        )

    def validatePdf(self, page, view, pdf_path):
        self.assertTrue(pdf_path.is_file())
        self.assertGreater(pdf_path.stat().st_size, 1000)
        pdf_bytes = pdf_path.read_bytes()
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertTrue(pdf_bytes.rstrip().endswith(b"%%EOF"))

        pdf_document = None
        try:
            pdf_document = pdfium.PdfDocument(str(pdf_path))
        except Exception as error:
            self.fail(f"PDFium rejected the exported PDF: {error!r}")

        try:
            self.assertEqual(len(pdf_document), 1)
            point_width, point_height = pdf_document.get_page_size(0)
            expected_width = _quantity_value(page.PageWidth) * 72.0 / 25.4
            expected_height = _quantity_value(page.PageHeight) * 72.0 / 25.4
            self.assertGreater(point_width, point_height)
            self.assertAlmostEqual(point_width, expected_width, delta=1.5)
            self.assertAlmostEqual(point_height, expected_height, delta=1.5)
            self.assertEqual(pdf_document.get_metadata_value("Title"), page.Name)

            pdf_page = pdf_document[0]
            bitmap = None
            try:
                bitmap = pdf_page.render(scale=1.5, rev_byteorder=True)
                image = bitmap.to_pil().convert("RGBA").copy()
            finally:
                if bitmap is not None:
                    bitmap.close()
                pdf_page.close()
        finally:
            pdf_document.close()
        self.assertGreater(image.width, 0)
        self.assertGreater(image.height, 0)
        background = self.assertRenderedImageContainsGeometry(image)
        self.assertRenderedViewRegionContainsGeometry(image, page, view, background)

    def assertRenderedImageContainsGeometry(self, image):
        step = max(1, min(image.width, image.height) // 300)
        colors = Counter()
        luminances = []
        for y in range(0, image.height, step):
            for x in range(0, image.width, step):
                colors[image.getpixel((x, y))] += 1

        self.assertGreater(len(colors), 1, "Rendered PDF page is a uniform image")
        sample_count = sum(colors.values())
        background_count = max(colors.values())
        non_background_count = sample_count - background_count
        self.assertGreater(
            non_background_count,
            max(50, sample_count // 2000),
            "Rendered PDF page contains no meaningful non-background geometry",
        )

        for red, green, blue, alpha in colors:
            opacity = alpha / 255.0
            composite_red = red * opacity + 255.0 * (1.0 - opacity)
            composite_green = green * opacity + 255.0 * (1.0 - opacity)
            composite_blue = blue * opacity + 255.0 * (1.0 - opacity)
            luminances.append(
                0.2126 * composite_red
                + 0.7152 * composite_green
                + 0.0722 * composite_blue
            )
        self.assertGreater(
            max(luminances) - min(luminances),
            10.0,
            "Rendered PDF page has insufficient contrast to contain drawing geometry",
        )
        return colors.most_common(1)[0][0]

    @staticmethod
    def compositeLuminance(rgba):
        red, green, blue, alpha = rgba
        opacity = alpha / 255.0
        composite_red = red * opacity + 255.0 * (1.0 - opacity)
        composite_green = green * opacity + 255.0 * (1.0 - opacity)
        composite_blue = blue * opacity + 255.0 * (1.0 - opacity)
        return (
            0.2126 * composite_red
            + 0.7152 * composite_green
            + 0.0722 * composite_blue
        )

    def assertRenderedViewRegionContainsGeometry(self, image, page, view, background):
        page_width = _quantity_value(page.PageWidth)
        page_height = _quantity_value(page.PageHeight)
        view_x = _quantity_value(view.X)
        view_y = _quantity_value(view.Y)
        center_x = round(view_x / page_width * image.width)
        center_y = round((page_height - view_y) / page_height * image.height)
        half_width = max(1, round(40.0 / page_width * image.width))
        half_height = max(1, round(30.0 / page_height * image.height))
        left = max(0, center_x - half_width)
        right = min(image.width, center_x + half_width + 1)
        top = max(0, center_y - half_height)
        bottom = min(image.height, center_y + half_height + 1)
        self.assertGreater(right, left)
        self.assertGreater(bottom, top)

        step = max(1, min(image.width, image.height) // 600)
        background_luminance = self.compositeLuminance(background)
        contrasting_pixels = 0
        sampled_pixels = 0
        for y in range(top, bottom, step):
            for x in range(left, right, step):
                rgba = image.getpixel((x, y))
                sampled_pixels += 1
                if abs(self.compositeLuminance(rgba) - background_luminance) > 15.0:
                    contrasting_pixels += 1

        self.assertGreater(
            contrasting_pixels,
            max(50, sampled_pixels // 1000),
            "Rendered PDF has no projected geometry around FilletTopView's page position",
        )

    def test_full_page_svg_and_pdf_exports_render_real_drawing(self):
        self.document = App.openDocument(str(self.fixture_path))
        App.setActiveDocument(self.document.Name)
        Gui.setActiveDocument(self.document.Name)

        page = self.document.getObject("DrawingPage")
        view = self.document.getObject("FilletTopView")
        self.assertIsNotNone(page)
        self.assertIsNotNone(view)
        self.assertEqual(page.TypeId, "TechDraw::DrawPage")
        self.assertEqual(view.TypeId, "TechDraw::DrawViewPart")
        self.assertAlmostEqual(_quantity_value(page.PageWidth), 297.0, places=5)
        self.assertAlmostEqual(_quantity_value(page.PageHeight), 210.0, places=5)

        self.document.recompute()
        self.waitFor(
            "finite, up-to-date projected geometry",
            lambda: self.projectionIsReady(view),
        )
        self.assertTrue(self.finiteVisibleEdges(view))

        page.ViewObject.show()
        Gui.updateGui()
        self.waitFor(
            "DrawingPage to become the active TechDraw MDI page",
            lambda: self.activeMdiShowsPage(page),
        )
        self.assertIsNotNone(TechDrawGui.getSceneForPage(page))

        gui_document = Gui.activeDocument()
        self.assertIsNotNone(gui_document)
        modified_before_svg = bool(gui_document.Modified)
        TechDrawGui.exportPageAsSvg(page, str(self.svg_path))
        self.assertEqual(bool(gui_document.Modified), modified_before_svg)
        self.validateSvg(page, self.svg_path)

        svg_count_before_unicode = len(list(self.export_directory.glob("*.svg")))
        modified_before_unicode_svg = bool(gui_document.Modified)
        TechDrawGui.exportPageAsSvg(page, str(self.unicode_svg_path))
        self.assertEqual(bool(gui_document.Modified), modified_before_unicode_svg)
        self.validateSvg(page, self.unicode_svg_path)
        self.assertEqual(
            len(list(self.export_directory.glob("*.svg"))),
            svg_count_before_unicode + 1,
            "Unicode SVG export created a mojibake sibling or an unexpected extra file",
        )

        modified_before_pdf = bool(gui_document.Modified)
        TechDrawGui.exportPageAsPdf(page, str(self.pdf_path))
        self.assertEqual(bool(gui_document.Modified), modified_before_pdf)
        self.validatePdf(page, view, self.pdf_path)

        pdf_count_before_unicode = len(list(self.export_directory.glob("*.pdf")))
        modified_before_unicode_pdf = bool(gui_document.Modified)
        TechDrawGui.exportPageAsPdf(page, str(self.unicode_pdf_path))
        self.assertEqual(bool(gui_document.Modified), modified_before_unicode_pdf)
        self.validatePdf(page, view, self.unicode_pdf_path)
        self.assertEqual(
            len(list(self.export_directory.glob("*.pdf"))),
            pdf_count_before_unicode + 1,
            "Unicode PDF export created a mojibake sibling or an unexpected extra file",
        )


if __name__ == "__main__":
    unittest.main()
