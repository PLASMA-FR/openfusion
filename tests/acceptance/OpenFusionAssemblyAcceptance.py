# SPDX-License-Identifier: LGPL-2.1-or-later

"""Assembly solving and persistence acceptance test built on the core fixture."""

import os
from pathlib import Path
import unittest

import Assembly  # Registers Assembly::AssemblyObject and Assembly::JointGroup.
import FreeCAD as App
import JointObject


DOCUMENT_NAMES = (
    "OpenFusionCoreAcceptance",
    "OpenFusionAssemblyAcceptance",
)
PLACEMENT_TOLERANCE = 1.0e-6


class OpenFusionAssemblyAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self._opened_document_names = set()

        configured_output = os.environ.get("OPENFUSION_ACCEPTANCE_OUTPUT_DIR")
        self.output_directory = Path(configured_output) if configured_output else Path.cwd()
        self.output_directory.mkdir(parents=True, exist_ok=True)

        self.addCleanup(self._close_opened_documents)

        self.core_fixture_path = self.output_directory / "OpenFusionCoreAcceptance.FCStd"
        self.assembly_path = self.output_directory / "OpenFusionAssemblyAcceptance.FCStd"
        self._close_fixture_documents()

        if not self.core_fixture_path.is_file():
            self.fail(
                "The core acceptance fixture is missing: "
                f"{self.core_fixture_path}. Run OpenFusion_Core_Acceptance first."
            )
        if self.assembly_path.exists():
            self.assembly_path.unlink()

    def _close_fixture_documents(self):
        fixture_paths = {
            self.core_fixture_path.resolve(),
            self.assembly_path.resolve(),
        }
        for name, document in list(App.listDocuments().items()):
            file_name = getattr(document, "FileName", "")
            matches_fixture = bool(file_name) and Path(file_name).resolve() in fixture_paths
            if name in DOCUMENT_NAMES or matches_fixture:
                App.closeDocument(name)

    def _track_document(self, document):
        self._opened_document_names.add(document.Name)
        return document

    def _close_opened_documents(self):
        for name in tuple(self._opened_document_names):
            if name in App.listDocuments():
                App.closeDocument(name)
        self._opened_document_names.clear()

    def assertPlacementEqual(self, actual, expected, message):
        self.assertTrue(
            actual.isSame(expected, PLACEMENT_TOLERANCE),
            f"{message}: expected {expected}, got {actual}",
        )

    def assertOriginReference(self, joint, property_name, expected_occurrence):
        reference = getattr(joint, property_name)
        self.assertIsNotNone(reference, f"{property_name} was not restored")
        self.assertEqual(reference[0], expected_occurrence)
        self.assertEqual(tuple(reference[1]), ("", ""))
        self.assertNotIn("?", "".join(reference[1]))

    def assertAssemblyObjectTypes(
        self, assembly, joint_group, primary, secondary, grounded_joint, fixed_joint
    ):
        self.assertEqual(assembly.TypeId, "Assembly::AssemblyObject")
        self.assertEqual(joint_group.TypeId, "Assembly::JointGroup")
        self.assertEqual(primary.TypeId, "App::Link")
        self.assertEqual(secondary.TypeId, "App::Link")
        self.assertFalse(primary.LinkTransform)
        self.assertFalse(secondary.LinkTransform)
        self.assertEqual(grounded_joint.TypeId, "App::FeaturePython")
        self.assertEqual(fixed_joint.TypeId, "App::FeaturePython")
        self.assertEqual(
            grounded_joint.getTypeIdOfProperty("ObjectToGround"),
            "App::PropertyLinkGlobal",
        )
        self.assertEqual(
            fixed_joint.getTypeIdOfProperty("Reference1"),
            "App::PropertyXLinkSub",
        )
        self.assertEqual(
            fixed_joint.getTypeIdOfProperty("Reference2"),
            "App::PropertyXLinkSub",
        )
        self.assertFalse(fixed_joint.Suppressed)

    def assertAssemblyConnectivity(self, assembly, primary, secondary, fixed_joint):
        self.assertEqual(tuple(assembly.Joints), (fixed_joint,))
        self.assertTrue(assembly.isPartGrounded(primary))
        self.assertFalse(assembly.isPartGrounded(secondary))
        self.assertTrue(assembly.isPartConnected(primary))
        self.assertTrue(assembly.isPartConnected(secondary))
        self.assertFalse(
            assembly.isJointConnectingPartToGround(fixed_joint, "Reference1")
        )
        self.assertTrue(
            assembly.isJointConnectingPartToGround(fixed_joint, "Reference2")
        )

    def perturbAndSolve(self, assembly, primary, secondary, expected_placement):
        perturbed_placement = App.Placement(
            App.Vector(-43.0, 29.0, 61.0),
            App.Rotation(App.Vector(1.0, 2.0, 3.0), 71.0),
        )
        secondary.Placement = perturbed_placement
        self.assertFalse(
            secondary.Placement.isSame(expected_placement, PLACEMENT_TOLERANCE)
        )

        self.assertEqual(assembly.solve(), 0, "The assembly solver did not converge")
        self.assertPlacementEqual(
            primary.Placement,
            expected_placement,
            "The grounded occurrence moved during solve",
        )
        self.assertPlacementEqual(
            secondary.Placement,
            expected_placement,
            "The fixed joint did not restore the moving occurrence",
        )

    def test_fixed_joint_round_trip(self):
        document = self._track_document(App.openDocument(str(self.core_fixture_path)))
        root_component = document.getObject("RootComponent")
        pattern_component = document.getObject("PatternComponent")
        self.assertIsNotNone(root_component, "Core fixture has no RootComponent")
        self.assertIsNotNone(pattern_component, "Core fixture has no PatternComponent")

        assembly = document.addObject("Assembly::AssemblyObject", "AcceptanceAssembly")
        assembly.Type = "Assembly"
        joint_group = assembly.newObject("Assembly::JointGroup", "AssemblyJoints")

        primary = assembly.newObject("App::Link", "RootOccurrence")
        primary.LinkedObject = root_component
        primary.LinkTransform = False
        secondary = assembly.newObject("App::Link", "PatternOccurrence")
        secondary.LinkedObject = pattern_component
        secondary.LinkTransform = False

        expected_placement = App.Placement(
            App.Vector(18.0, -11.0, 7.0),
            App.Rotation(App.Vector(2.0, 3.0, 5.0), 37.0),
        )
        primary.Placement = expected_placement
        secondary.Placement = expected_placement

        grounded_joint = joint_group.newObject("App::FeaturePython", "GroundedOccurrence")
        JointObject.GroundedJoint(grounded_joint, primary)

        fixed_joint = joint_group.newObject("App::FeaturePython", "FixedOriginJoint")
        JointObject.Joint(fixed_joint, JointObject.JointTypes.index("Fixed"))
        fixed_joint.Proxy.setJointConnectors(
            fixed_joint,
            [
                [primary, ["", ""]],
                [secondary, ["", ""]],
            ],
        )
        document.recompute()

        self.assertEqual(assembly.Type, "Assembly")
        self.assertEqual(primary.LinkedObject, root_component)
        self.assertEqual(secondary.LinkedObject, pattern_component)
        self.assertEqual(grounded_joint.ObjectToGround, primary)
        self.assertEqual(fixed_joint.JointType, "Fixed")
        self.assertAssemblyObjectTypes(
            assembly,
            joint_group,
            primary,
            secondary,
            grounded_joint,
            fixed_joint,
        )
        self.assertOriginReference(fixed_joint, "Reference1", primary)
        self.assertOriginReference(fixed_joint, "Reference2", secondary)
        self.assertAssemblyConnectivity(assembly, primary, secondary, fixed_joint)
        self.assertPlacementEqual(
            secondary.Placement,
            expected_placement,
            "Connector setup did not align the occurrence origins",
        )

        self.perturbAndSolve(assembly, primary, secondary, expected_placement)
        self.assertAssemblyConnectivity(assembly, primary, secondary, fixed_joint)

        document.saveAs(str(self.assembly_path))
        self.assertGreater(self.assembly_path.stat().st_size, 0)
        document_name = document.Name
        App.closeDocument(document_name)
        self._opened_document_names.discard(document_name)

        document = self._track_document(App.openDocument(str(self.assembly_path)))
        assembly = document.getObject("AcceptanceAssembly")
        joint_group = document.getObject("AssemblyJoints")
        primary = document.getObject("RootOccurrence")
        secondary = document.getObject("PatternOccurrence")
        grounded_joint = document.getObject("GroundedOccurrence")
        fixed_joint = document.getObject("FixedOriginJoint")

        for name, obj in (
            ("AcceptanceAssembly", assembly),
            ("AssemblyJoints", joint_group),
            ("RootOccurrence", primary),
            ("PatternOccurrence", secondary),
            ("GroundedOccurrence", grounded_joint),
            ("FixedOriginJoint", fixed_joint),
        ):
            self.assertIsNotNone(obj, f"{name} was not restored")

        self.assertEqual(assembly.Type, "Assembly")
        self.assertIn(primary, assembly.Group)
        self.assertIn(secondary, assembly.Group)
        self.assertIn(joint_group, assembly.Group)
        self.assertIn(grounded_joint, joint_group.Group)
        self.assertIn(fixed_joint, joint_group.Group)
        self.assertEqual(len(joint_group.Group), 2)
        self.assertEqual(primary.LinkedObject, document.getObject("RootComponent"))
        self.assertEqual(secondary.LinkedObject, document.getObject("PatternComponent"))
        self.assertIsInstance(grounded_joint.Proxy, JointObject.GroundedJoint)
        self.assertIsInstance(fixed_joint.Proxy, JointObject.Joint)
        self.assertTrue(callable(fixed_joint.Proxy.setJointConnectors))
        self.assertEqual(grounded_joint.ObjectToGround, primary)
        self.assertEqual(fixed_joint.JointType, "Fixed")
        self.assertAssemblyObjectTypes(
            assembly,
            joint_group,
            primary,
            secondary,
            grounded_joint,
            fixed_joint,
        )
        self.assertOriginReference(fixed_joint, "Reference1", primary)
        self.assertOriginReference(fixed_joint, "Reference2", secondary)

        document.recompute()
        reloaded_expected_placement = App.Placement(primary.Placement)
        self.assertPlacementEqual(
            reloaded_expected_placement,
            expected_placement,
            "The grounded occurrence placement did not persist",
        )
        self.assertPlacementEqual(
            secondary.Placement,
            reloaded_expected_placement,
            "The fixed occurrence placement did not persist",
        )
        self.assertAssemblyConnectivity(assembly, primary, secondary, fixed_joint)

        self.perturbAndSolve(
            assembly,
            primary,
            secondary,
            reloaded_expected_placement,
        )
        self.assertAssemblyConnectivity(assembly, primary, secondary, fixed_joint)
        document.recompute()
        document.save()


if __name__ == "__main__":
    unittest.main()
