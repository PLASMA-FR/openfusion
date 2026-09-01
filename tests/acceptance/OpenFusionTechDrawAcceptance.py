# SPDX-License-Identifier: LGPL-2.1-or-later

"""Headless TechDraw projection, persistence, and parametric update acceptance."""

import math
import os
from pathlib import Path
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET

import FreeCAD as App
import TechDraw


DOCUMENT_NAMES = (
    "OpenFusionCoreAcceptance",
    "OpenFusionTechDrawAcceptance",
)
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
NONFINITE_NUMBER = re.compile(
    r"(?<![A-Za-z])[-+]?(?:nan|inf(?:inity)?)(?![A-Za-z])",
    re.IGNORECASE,
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


def _configured_path(environment_name):
    value = os.environ.get(environment_name, "").strip()
    if not value:
        return None
    return Path(os.path.expandvars(value)).expanduser().resolve()


def _quantity_value(value):
    return float(getattr(value, "Value", value))


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


class OpenFusionTechDrawAcceptanceTest(unittest.TestCase):
    def setUp(self):
        for name in DOCUMENT_NAMES:
            if name in App.listDocuments():
                App.closeDocument(name)

        self._temporary_directory = None
        self.output_directory = _configured_path(
            "OPENFUSION_ACCEPTANCE_OUTPUT_DIR"
        )
        if self.output_directory is None:
            self._temporary_directory = tempfile.TemporaryDirectory(
                prefix="openfusion-techdraw-acceptance-"
            )
            self.output_directory = Path(self._temporary_directory.name)
        self.output_directory.mkdir(parents=True, exist_ok=True)

        fixture_override = _configured_path(
            "OPENFUSION_CORE_ACCEPTANCE_FIXTURE"
        )
        self.core_fixture_path = fixture_override or (
            self.output_directory / "OpenFusionCoreAcceptance.FCStd"
        )
        self.result_path = (
            self.output_directory / "OpenFusionTechDrawAcceptance.FCStd"
        )
        self.initial_svg_path = (
            self.output_directory / "OpenFusionTechDraw-initial.svg"
        )
        self.updated_svg_path = (
            self.output_directory / "OpenFusionTechDraw-updated.svg"
        )
        self.reopened_svg_path = (
            self.output_directory / "OpenFusionTechDraw-reopened.svg"
        )

        self.assertTrue(
            self.core_fixture_path.is_file(),
            "Core acceptance fixture is missing; run "
            "OpenFusion_Core_Acceptance first or set "
            "OPENFUSION_CORE_ACCEPTANCE_FIXTURE",
        )
        self.assertNotEqual(
            self.core_fixture_path,
            self.result_path,
            "TechDraw result must not overwrite the core acceptance fixture",
        )
        for path in (
            self.result_path,
            self.initial_svg_path,
            self.updated_svg_path,
            self.reopened_svg_path,
        ):
            if path.exists():
                path.unlink()

    def tearDown(self):
        for name in list(App.listDocuments()):
            if name in DOCUMENT_NAMES:
                App.closeDocument(name)
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()

    def assertDrawingLinks(self, page, template, view, source):
        self.assertEqual(page.TypeId, "TechDraw::DrawPage")
        self.assertEqual(template.TypeId, "TechDraw::DrawSVGTemplate")
        self.assertEqual(view.TypeId, "TechDraw::DrawViewPart")
        self.assertIsNotNone(page.Template)
        self.assertEqual(page.Template.Name, template.Name)
        self.assertEqual([item.Name for item in page.Views], [view.Name])
        self.assertEqual([item.Name for item in page.getViews()], [view.Name])
        self.assertEqual(view.findParentPage().Name, page.Name)
        self.assertEqual([item.Name for item in view.Source], [source.Name])

    def assertTopViewConfiguration(self, view):
        self.assertEqual(view.ScaleType, "Custom")
        self.assertAlmostEqual(_quantity_value(view.Scale), 1.0, places=7)
        direction = view.Direction
        for actual, expected in zip(
            (direction.x, direction.y, direction.z),
            (0.0, 0.0, 1.0),
        ):
            self.assertAlmostEqual(actual, expected, places=7)
        x_direction = view.XDirection
        for actual, expected in zip(
            (x_direction.x, x_direction.y, x_direction.z),
            (1.0, 0.0, 0.0),
        ):
            self.assertAlmostEqual(actual, expected, places=7)
        self.assertTrue(math.isfinite(_quantity_value(view.X)))
        self.assertTrue(math.isfinite(_quantity_value(view.Y)))

    def assertFiniteProjectedGeometry(self, view):
        edges = view.getVisibleEdges(True)
        self.assertTrue(edges, "TechDraw produced no visible projected edges")

        boxes = []
        total_length = 0.0
        for index, edge in enumerate(edges, start=1):
            with self.subTest(projected_edge=index):
                self.assertFalse(edge.isNull(), "Projected edge is null")
                self.assertTrue(edge.isValid(), "Projected edge is invalid")
                length = float(edge.Length)
                self.assertTrue(math.isfinite(length))
                self.assertGreater(length, 0.0)
                total_length += length

                box = edge.BoundBox
                coordinates = (
                    box.XMin,
                    box.YMin,
                    box.ZMin,
                    box.XMax,
                    box.YMax,
                    box.ZMax,
                )
                self.assertTrue(
                    all(math.isfinite(value) for value in coordinates),
                    "Projected edge has a non-finite bounding box",
                )
                boxes.append(box)

        self.assertGreater(total_length, 0.0)
        bounds = (
            min(box.XMin for box in boxes),
            min(box.YMin for box in boxes),
            min(box.ZMin for box in boxes),
            max(box.XMax for box in boxes),
            max(box.YMax for box in boxes),
            max(box.ZMax for box in boxes),
        )
        self.assertGreater(bounds[3] - bounds[0], 0.0)
        self.assertGreater(bounds[4] - bounds[1], 0.0)
        return bounds

    def writeAndValidateDrawingSvg(self, template, view, destination):
        fragment = str(TechDraw.viewPartAsSvg(view))
        self.assertTrue(fragment.strip(), "TechDraw emitted an empty SVG fragment")
        self.assertIsNone(
            NONFINITE_NUMBER.search(fragment),
            "TechDraw SVG contains a non-finite number",
        )

        fragment_root = ET.fromstring(
            f'<svg xmlns="{SVG_NAMESPACE}">{fragment}</svg>'
        )
        projected_elements = [
            element
            for element in fragment_root.iter()
            if _local_name(element.tag) in GRAPHICAL_SVG_ELEMENTS
        ]
        self.assertTrue(
            projected_elements,
            "TechDraw SVG contains no projected graphical elements",
        )

        included_template = Path(str(template.PageResult))
        self.assertTrue(
            included_template.is_file(),
            "The drawing template has no readable embedded PageResult",
        )
        template_tree = ET.parse(included_template)
        template_root = template_tree.getroot()
        self.assertEqual(_local_name(template_root.tag), "svg")

        drawing_layer = ET.SubElement(
            template_root,
            f"{{{SVG_NAMESPACE}}}g",
            {
                "id": "OpenFusionProjectedView",
                "transform": (
                    f"translate({_quantity_value(view.X):.12g} "
                    f"{_quantity_value(view.Y):.12g})"
                ),
            },
        )
        for element in list(fragment_root):
            drawing_layer.append(element)

        ET.register_namespace("", SVG_NAMESPACE)
        template_tree.write(destination, encoding="utf-8", xml_declaration=True)
        self.assertTrue(destination.is_file())
        self.assertGreater(destination.stat().st_size, 500)

        saved_root = ET.parse(destination).getroot()
        saved_layers = [
            element
            for element in saved_root.iter()
            if element.attrib.get("id") == "OpenFusionProjectedView"
        ]
        self.assertEqual(len(saved_layers), 1)
        saved_projected_elements = [
            element
            for element in saved_layers[0].iter()
            if _local_name(element.tag) in GRAPHICAL_SVG_ELEMENTS
        ]
        self.assertEqual(
            len(saved_projected_elements),
            len(projected_elements),
        )
        return fragment

    def projectionSnapshot(self, document, template, view, svg_path=None):
        document.recompute()
        self.assertIn("Up-to-date", view.State)
        bounds = self.assertFiniteProjectedGeometry(view)
        fragment = None
        if svg_path is not None:
            fragment = self.writeAndValidateDrawingSvg(template, view, svg_path)
        return bounds, fragment

    def test_drawing_tracks_parametric_model_and_round_trips(self):
        document = App.openDocument(str(self.core_fixture_path))
        document.UndoMode = 1

        base_sketch = document.getObject("BaseSketch")
        fillet = document.getObject("EdgeFillet")
        self.assertIsNotNone(base_sketch)
        self.assertIsNotNone(fillet)
        self.assertFalse(fillet.Shape.isNull())
        self.assertTrue(fillet.Shape.isValid())

        template_path = (
            Path(App.getResourceDir())
            / "Mod"
            / "TechDraw"
            / "Templates"
            / "ISO"
            / "A4_Landscape_ISO5457_minimal.svg"
        )
        self.assertTrue(template_path.is_file(), "Shipped A4 template is missing")

        page = document.addObject("TechDraw::DrawPage", "DrawingPage")
        template = document.addObject(
            "TechDraw::DrawSVGTemplate", "DrawingTemplate"
        )
        template.Template = str(template_path)
        page.Template = template
        page.KeepUpdated = True
        page.Scale = 1.0
        document.recompute()
        self.assertEqual(page.Template.Name, template.Name)
        self.assertAlmostEqual(page.PageWidth, 297.0, places=5)
        self.assertAlmostEqual(page.PageHeight, 210.0, places=5)
        self.assertEqual(page.PageOrientation, "Landscape")

        view = document.addObject("TechDraw::DrawViewPart", "FilletTopView")
        view.Direction = App.Vector(0.0, 0.0, 1.0)
        view.XDirection = App.Vector(1.0, 0.0, 0.0)
        view.ScaleType = "Custom"
        view.Scale = 1.0

        # A valid template must already be attached because addView queries its
        # dimensions when positioning and checking the new view.
        self.assertEqual(page.addView(view), 1)
        view.Source = [fillet]
        self.assertDrawingLinks(page, template, view, fillet)
        self.assertTopViewConfiguration(view)

        initial_bounds, initial_svg = self.projectionSnapshot(
            document,
            template,
            view,
            self.initial_svg_path,
        )
        initial_span = initial_bounds[3] - initial_bounds[0]
        self.assertAlmostEqual(
            initial_span,
            fillet.Shape.BoundBox.XLength,
            delta=1.0e-4,
        )

        width_constraint = base_sketch.getIndexByName("Width")
        self.assertGreaterEqual(width_constraint, 0)
        initial_width = float(base_sketch.Constraints[width_constraint].Value)
        width_delta = 8.0
        updated_width = initial_width + width_delta

        document.openTransaction("Edit early sketch width for drawing")
        try:
            base_sketch.setDatum(
                width_constraint,
                App.Units.Quantity(f"{updated_width:.12g} mm"),
            )
            document.commitTransaction()
        except Exception:
            document.abortTransaction()
            raise

        updated_bounds, updated_svg = self.projectionSnapshot(
            document,
            template,
            view,
            self.updated_svg_path,
        )
        updated_span = updated_bounds[3] - updated_bounds[0]
        self.assertAlmostEqual(
            base_sketch.Constraints[width_constraint].Value,
            updated_width,
            places=5,
        )
        self.assertAlmostEqual(
            updated_span,
            fillet.Shape.BoundBox.XLength,
            delta=1.0e-4,
        )
        self.assertAlmostEqual(
            updated_span - initial_span,
            width_delta,
            delta=1.0e-4,
        )
        self.assertNotEqual(initial_svg, updated_svg)

        document.undo()
        undo_bounds, _ = self.projectionSnapshot(document, template, view)
        self.assertAlmostEqual(
            base_sketch.Constraints[width_constraint].Value,
            initial_width,
            places=5,
        )
        self.assertAlmostEqual(
            undo_bounds[3] - undo_bounds[0],
            initial_span,
            delta=1.0e-4,
        )

        document.redo()
        redo_bounds, _ = self.projectionSnapshot(document, template, view)
        self.assertAlmostEqual(
            base_sketch.Constraints[width_constraint].Value,
            updated_width,
            places=5,
        )
        self.assertAlmostEqual(
            redo_bounds[3] - redo_bounds[0],
            updated_span,
            delta=1.0e-4,
        )

        document.saveAs(str(self.result_path))
        self.assertTrue(self.result_path.is_file())
        self.assertGreater(self.result_path.stat().st_size, 0)
        App.closeDocument(document.Name)

        document = App.openDocument(str(self.result_path))
        document.recompute()
        base_sketch = document.getObject("BaseSketch")
        fillet = document.getObject("EdgeFillet")
        page = document.getObject("DrawingPage")
        template = document.getObject("DrawingTemplate")
        view = document.getObject("FilletTopView")
        for name, item in (
            ("BaseSketch", base_sketch),
            ("EdgeFillet", fillet),
            ("DrawingPage", page),
            ("DrawingTemplate", template),
            ("FilletTopView", view),
        ):
            self.assertIsNotNone(item, f"{name} did not survive save/reopen")

        self.assertDrawingLinks(page, template, view, fillet)
        self.assertTopViewConfiguration(view)
        self.assertTrue(Path(str(template.PageResult)).is_file())
        self.assertAlmostEqual(page.PageWidth, 297.0, places=5)
        self.assertAlmostEqual(page.PageHeight, 210.0, places=5)
        self.assertEqual(page.PageOrientation, "Landscape")
        width_constraint = base_sketch.getIndexByName("Width")
        self.assertGreaterEqual(width_constraint, 0)
        self.assertAlmostEqual(
            base_sketch.Constraints[width_constraint].Value,
            updated_width,
            places=5,
        )

        reopened_bounds, reopened_svg = self.projectionSnapshot(
            document,
            template,
            view,
            self.reopened_svg_path,
        )
        self.assertAlmostEqual(
            reopened_bounds[3] - reopened_bounds[0],
            updated_span,
            delta=1.0e-4,
        )
        self.assertTrue(reopened_svg.strip())


if __name__ == "__main__":
    unittest.main()
