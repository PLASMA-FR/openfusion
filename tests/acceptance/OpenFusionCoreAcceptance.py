# SPDX-License-Identifier: LGPL-2.1-or-later

"""Core parametric, persistence, undo, and interoperability acceptance test."""

import math
import os
from pathlib import Path
import tempfile
import unittest

import FreeCAD as App
import Import
import Mesh
import Part
import Sketcher


DOCUMENT_NAMES = (
    "OpenFusionCoreAcceptance",
    "OpenFusionStepRoundTrip",
    "OpenFusionMeshRoundTrip",
)


def _xy_plane(body):
    for feature in body.Origin.OriginFeatures:
        if getattr(feature, "Role", "") == "XY_Plane":
            return feature
    raise AssertionError(f"Body {body.Name} has no semantic XY plane")


def _add_fully_constrained_rectangle(sketch, width, height, center_x=0.0, center_y=0.0):
    half_width = width / 2.0
    half_height = height / 2.0
    corners = (
        App.Vector(center_x - half_width, center_y + half_height, 0),
        App.Vector(center_x + half_width, center_y + half_height, 0),
        App.Vector(center_x + half_width, center_y - half_height, 0),
        App.Vector(center_x - half_width, center_y - half_height, 0),
    )

    for start, end in zip(corners, corners[1:] + corners[:1]):
        sketch.addGeometry(Part.LineSegment(start, end), False)

    for first, second in ((0, 1), (1, 2), (2, 3), (3, 0)):
        sketch.addConstraint(Sketcher.Constraint("Coincident", first, 2, second, 1))

    sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
    sketch.addConstraint(Sketcher.Constraint("Vertical", 1))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", 2))
    sketch.addConstraint(Sketcher.Constraint("Vertical", 3))
    sketch.addConstraint(
        Sketcher.Constraint("DistanceX", 2, 2, center_x - half_width)
    )
    sketch.addConstraint(
        Sketcher.Constraint("DistanceY", 2, 2, center_y - half_height)
    )

    width_constraint = sketch.addConstraint(Sketcher.Constraint("Distance", 0, width))
    height_constraint = sketch.addConstraint(Sketcher.Constraint("Distance", 1, height))
    sketch.renameConstraint(width_constraint, "Width")
    sketch.renameConstraint(height_constraint, "Height")
    return width_constraint


def _add_fully_constrained_circle(sketch, radius):
    geometry = sketch.addGeometry(
        Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), radius),
        False,
    )
    sketch.addConstraint(Sketcher.Constraint("Coincident", geometry, 3, -1, 1))
    sketch.addConstraint(Sketcher.Constraint("Radius", geometry, radius))


def _top_planar_face_name(shape):
    z_max = shape.BoundBox.ZMax
    candidates = []
    for index, face in enumerate(shape.Faces, start=1):
        bounds = face.BoundBox
        if abs(bounds.ZMax - z_max) > 1.0e-7 or bounds.ZLength > 1.0e-7:
            continue
        try:
            u_min, u_max, v_min, v_max = face.ParameterRange
            normal = face.normalAt((u_min + u_max) / 2.0, (v_min + v_max) / 2.0)
        except (Part.OCCError, RuntimeError):
            continue
        if normal.z > 0.999:
            candidates.append(f"Face{index}")

    if len(candidates) != 1:
        raise AssertionError(f"Expected one top planar face, found {candidates}")
    return candidates[0]


def _outer_vertical_edge_name(shape):
    bounds = shape.BoundBox
    candidates = []
    for index, edge in enumerate(shape.Edges, start=1):
        edge_bounds = edge.BoundBox
        if abs(edge_bounds.ZLength - bounds.ZLength) > 1.0e-7:
            continue
        if edge_bounds.XLength > 1.0e-7 or edge_bounds.YLength > 1.0e-7:
            continue
        on_x_boundary = min(
            abs(edge_bounds.XMin - bounds.XMin),
            abs(edge_bounds.XMin - bounds.XMax),
        ) < 1.0e-7
        on_y_boundary = min(
            abs(edge_bounds.YMin - bounds.YMin),
            abs(edge_bounds.YMin - bounds.YMax),
        ) < 1.0e-7
        if on_x_boundary and on_y_boundary:
            candidates.append(f"Edge{index}")

    if not candidates:
        raise AssertionError("No exterior vertical edge was found for the fillet")
    return candidates[0]


def _bounds(entities):
    boxes = [entity.BoundBox for entity in entities]
    if not boxes:
        raise AssertionError("No entities supplied for a bounding-box comparison")
    return (
        min(box.XMin for box in boxes),
        min(box.YMin for box in boxes),
        min(box.ZMin for box in boxes),
        max(box.XMax for box in boxes),
        max(box.YMax for box in boxes),
        max(box.ZMax for box in boxes),
    )


def _unique_solid_signatures(shapes):
    signatures = set()
    for shape in shapes:
        for solid in shape.Solids:
            center = solid.CenterOfMass
            signatures.add(
                (
                    round(solid.Volume, 5),
                    round(center.x, 5),
                    round(center.y, 5),
                    round(center.z, 5),
                )
            )
    return sorted(signatures)


class OpenFusionCoreAcceptanceTest(unittest.TestCase):
    def setUp(self):
        for name in DOCUMENT_NAMES:
            if name in App.listDocuments():
                App.closeDocument(name)

        configured_output = os.environ.get("OPENFUSION_ACCEPTANCE_OUTPUT_DIR")
        self._temporary_directory = None
        if configured_output:
            self.output_directory = Path(configured_output)
            self.output_directory.mkdir(parents=True, exist_ok=True)
        else:
            self._temporary_directory = tempfile.TemporaryDirectory(
                prefix="openfusion-acceptance-"
            )
            self.output_directory = Path(self._temporary_directory.name)

        self.fcstd_path = self.output_directory / "OpenFusionCoreAcceptance.FCStd"
        self.step_path = self.output_directory / "OpenFusionCoreAcceptance.step"
        self.stl_path = self.output_directory / "OpenFusionCoreAcceptance.stl"
        for path in (self.fcstd_path, self.step_path, self.stl_path):
            if path.exists():
                path.unlink()

    def tearDown(self):
        for name in DOCUMENT_NAMES:
            if name in App.listDocuments():
                App.closeDocument(name)
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()

    def assertValidSingleSolid(self, feature):
        self.assertFalse(feature.Shape.isNull(), f"{feature.Name} has a null shape")
        self.assertTrue(feature.Shape.isValid(), f"{feature.Name} has an invalid shape")
        self.assertEqual(len(feature.Shape.Solids), 1, f"{feature.Name} is not one solid")

    def assertFullyConstrained(self, sketch):
        self.assertEqual(sketch.solve(), 0, f"{sketch.Name} solver did not converge")
        self.assertTrue(sketch.FullyConstrained, f"{sketch.Name} is not fully constrained")

    def test_core_model_round_trip(self):
        document = App.newDocument(DOCUMENT_NAMES[0])
        document.UndoMode = 1

        root_component = document.addObject("App::Part", "RootComponent")
        body = root_component.newObject("PartDesign::Body", "DesignBody")
        base_sketch = body.newObject("Sketcher::SketchObject", "BaseSketch")
        base_sketch.AttachmentSupport = (_xy_plane(body), [""])
        base_sketch.MapMode = "FlatFace"
        _add_fully_constrained_rectangle(base_sketch, 40.0, 30.0)
        document.recompute()
        self.assertFullyConstrained(base_sketch)

        pad = body.newObject("PartDesign::Pad", "BasePad")
        pad.Profile = base_sketch
        pad.Length = 10.0
        document.recompute()
        self.assertValidSingleSolid(pad)
        self.assertAlmostEqual(pad.Shape.Volume, 12000.0, places=5)
        self.assertEqual(body.Tip, pad)

        hole_sketch = body.newObject("Sketcher::SketchObject", "HoleSketch")
        hole_sketch.AttachmentSupport = (pad, [_top_planar_face_name(pad.Shape)])
        hole_sketch.MapMode = "FlatFace"
        _add_fully_constrained_circle(hole_sketch, 3.0)
        document.recompute()
        self.assertFullyConstrained(hole_sketch)

        hole = body.newObject("PartDesign::Hole", "ThroughHole")
        hole.Profile = hole_sketch
        hole.Diameter = 6.0
        hole.ThreadType = 0
        hole.HoleCutType = 0
        hole.DepthType = 1
        hole.DrillPoint = 0
        hole.Tapered = 0
        document.recompute()
        self.assertValidSingleSolid(hole)
        self.assertAlmostEqual(hole.Shape.Volume, 12000.0 - math.pi * 3.0**2 * 10.0, places=5)

        fillet = body.newObject("PartDesign::Fillet", "EdgeFillet")
        fillet.Base = (hole, [_outer_vertical_edge_name(hole.Shape)])
        fillet.Radius = 2.0
        document.recompute()
        self.assertValidSingleSolid(fillet)
        self.assertEqual(body.Tip, fillet)
        initial_fillet_volume = fillet.Shape.Volume
        initial_fillet_bounds = _bounds([fillet.Shape])

        pattern_component = document.addObject("App::Part", "PatternComponent")
        pattern_body = pattern_component.newObject("PartDesign::Body", "PatternBody")
        pattern_sketch = pattern_body.newObject("Sketcher::SketchObject", "PatternSketch")
        pattern_sketch.AttachmentSupport = (_xy_plane(pattern_body), [""])
        pattern_sketch.MapMode = "FlatFace"
        _add_fully_constrained_rectangle(
            pattern_sketch,
            10.0,
            10.0,
            center_x=70.0,
        )
        document.recompute()
        self.assertFullyConstrained(pattern_sketch)

        pattern_pad = pattern_body.newObject("PartDesign::Pad", "PatternPad")
        pattern_pad.Profile = pattern_sketch
        pattern_pad.Length = 10.0
        document.recompute()

        linear_pattern = pattern_body.newObject("PartDesign::LinearPattern", "LinearPattern")
        linear_pattern.Originals = [pattern_pad]
        linear_pattern.Direction = (pattern_sketch, ["H_Axis"])
        linear_pattern.Length = 30.0
        linear_pattern.Occurrences = 4
        linear_pattern.Refine = True
        document.recompute()
        self.assertValidSingleSolid(linear_pattern)
        self.assertAlmostEqual(linear_pattern.Shape.Volume, 4000.0, places=5)

        self.assertIn(body, root_component.Group)
        self.assertIn(pattern_body, pattern_component.Group)
        self.assertEqual(pattern_body.Tip, linear_pattern)

        document.saveAs(str(self.fcstd_path))
        self.assertGreater(self.fcstd_path.stat().st_size, 0)
        App.closeDocument(document.Name)

        document = App.openDocument(str(self.fcstd_path))
        document.recompute()
        root_component = document.getObject("RootComponent")
        body = document.getObject("DesignBody")
        base_sketch = document.getObject("BaseSketch")
        hole_sketch = document.getObject("HoleSketch")
        pad = document.getObject("BasePad")
        hole = document.getObject("ThroughHole")
        fillet = document.getObject("EdgeFillet")
        pattern_component = document.getObject("PatternComponent")
        pattern_body = document.getObject("PatternBody")
        pattern_sketch = document.getObject("PatternSketch")
        linear_pattern = document.getObject("LinearPattern")

        self.assertIn(body, root_component.Group)
        self.assertIn(pattern_body, pattern_component.Group)
        self.assertEqual(body.Tip, fillet)
        self.assertEqual(pattern_body.Tip, linear_pattern)
        self.assertFullyConstrained(base_sketch)
        self.assertFullyConstrained(hole_sketch)
        self.assertFullyConstrained(pattern_sketch)
        self.assertValidSingleSolid(fillet)
        self.assertValidSingleSolid(linear_pattern)

        document.UndoMode = 1
        width_constraint = base_sketch.getIndexByName("Width")
        document.openTransaction("Edit base width")
        base_sketch.setDatum(width_constraint, App.Units.Quantity("48 mm"))
        document.commitTransaction()
        document.recompute()
        self.assertAlmostEqual(
            base_sketch.Constraints[width_constraint].Value,
            48.0,
            places=5,
        )
        self.assertAlmostEqual(pad.Shape.Volume, 14400.0, places=5)
        self.assertAlmostEqual(hole.Shape.Volume, 14400.0 - math.pi * 3.0**2 * 10.0, places=5)
        self.assertValidSingleSolid(fillet)
        wide_fillet_volume = fillet.Shape.Volume
        wide_fillet_bounds = _bounds([fillet.Shape])
        self.assertGreater(wide_fillet_volume, initial_fillet_volume)
        self.assertGreater(wide_fillet_bounds[3] - wide_fillet_bounds[0], 40.0)
        for feature in (pad, hole, fillet):
            self.assertIn("Up-to-date", feature.State)

        document.undo()
        document.recompute()
        self.assertAlmostEqual(
            base_sketch.Constraints[width_constraint].Value,
            40.0,
            places=5,
        )
        self.assertAlmostEqual(pad.Shape.Volume, 12000.0, places=5)
        self.assertAlmostEqual(hole.Shape.Volume, 12000.0 - math.pi * 3.0**2 * 10.0, places=5)
        self.assertAlmostEqual(fillet.Shape.Volume, initial_fillet_volume, places=5)
        for expected, actual in zip(initial_fillet_bounds, _bounds([fillet.Shape])):
            self.assertAlmostEqual(expected, actual, delta=1.0e-7)
        self.assertValidSingleSolid(fillet)
        for feature in (pad, hole, fillet):
            self.assertIn("Up-to-date", feature.State)

        document.redo()
        document.recompute()
        self.assertAlmostEqual(
            base_sketch.Constraints[width_constraint].Value,
            48.0,
            places=5,
        )
        self.assertAlmostEqual(pad.Shape.Volume, 14400.0, places=5)
        self.assertAlmostEqual(hole.Shape.Volume, 14400.0 - math.pi * 3.0**2 * 10.0, places=5)
        self.assertAlmostEqual(fillet.Shape.Volume, wide_fillet_volume, places=5)
        for expected, actual in zip(wide_fillet_bounds, _bounds([fillet.Shape])):
            self.assertAlmostEqual(expected, actual, delta=1.0e-7)
        self.assertValidSingleSolid(fillet)
        for feature in (pad, hole, fillet):
            self.assertIn("Up-to-date", feature.State)

        document.save()
        App.closeDocument(document.Name)
        document = App.openDocument(str(self.fcstd_path))
        document.recompute()
        base_sketch = document.getObject("BaseSketch")
        fillet = document.getObject("EdgeFillet")
        linear_pattern = document.getObject("LinearPattern")
        width_constraint = base_sketch.getIndexByName("Width")
        self.assertAlmostEqual(base_sketch.Constraints[width_constraint].Value, 48.0, places=5)
        self.assertValidSingleSolid(fillet)
        self.assertValidSingleSolid(linear_pattern)
        self.assertAlmostEqual(fillet.Shape.Volume, wide_fillet_volume, places=5)
        source_shapes = [fillet.Shape, linear_pattern.Shape]
        source_signatures = _unique_solid_signatures(source_shapes)
        self.assertEqual(len(source_signatures), 2)
        source_centers_x = [signature[1] for signature in source_signatures]
        self.assertGreater(max(source_centers_x) - min(source_centers_x), 40.0)
        source_bounds = _bounds(source_shapes)
        source_volume = sum(shape.Volume for shape in source_shapes)

        Import.export([fillet, linear_pattern], str(self.step_path))
        Mesh.export([fillet, linear_pattern], str(self.stl_path), 0.005)
        self.assertGreater(self.step_path.stat().st_size, 0)
        self.assertGreater(self.stl_path.stat().st_size, 0)

        step_document = App.newDocument(DOCUMENT_NAMES[1])
        Import.insert(
            name=str(self.step_path),
            docName=step_document.Name,
            importHidden=False,
            merge=False,
            useLinkGroup=False,
            mode=0,
        )
        step_document.recompute()
        imported_shapes = [
            obj.Shape
            for obj in step_document.Objects
            if hasattr(obj, "Shape") and not obj.Shape.isNull()
        ]
        self.assertTrue(imported_shapes, "STEP reimport produced no shapes")
        self.assertTrue(all(shape.isValid() for shape in imported_shapes))
        imported_signatures = _unique_solid_signatures(imported_shapes)
        self.assertEqual(len(imported_signatures), len(source_signatures))
        for expected, actual in zip(source_signatures, imported_signatures):
            for expected_value, actual_value in zip(expected, actual):
                self.assertAlmostEqual(expected_value, actual_value, delta=0.01)

        mesh_document = App.newDocument(DOCUMENT_NAMES[2])
        Mesh.insert(str(self.stl_path), mesh_document.Name)
        mesh_document.recompute()
        imported_meshes = [
            obj.Mesh
            for obj in mesh_document.Objects
            if obj.TypeId.startswith("Mesh::") and hasattr(obj, "Mesh")
        ]
        self.assertTrue(imported_meshes, "STL reimport produced no mesh features")
        self.assertGreater(sum(mesh.CountFacets for mesh in imported_meshes), 0)
        imported_mesh_volume = sum(abs(mesh.Volume) for mesh in imported_meshes)
        self.assertAlmostEqual(source_volume, imported_mesh_volume, delta=5.0)
        mesh_bounds = _bounds(imported_meshes)
        for expected, actual in zip(source_bounds, mesh_bounds):
            self.assertAlmostEqual(expected, actual, delta=0.05)


if __name__ == "__main__":
    unittest.main()
