import json
import tempfile
import unittest
from pathlib import Path

from identity_bridge_v0_1 import *


HTML = ('{"matchId":"120","widgets":[{"widget":{"sportradarWidget":'
        '{"externalMatchRef":"730","externalSportRef":"1"}}}]}')


class IdentityBridgeTests(unittest.TestCase):
    def test_c01_c02_provider_derived_bridge_is_deterministic(self):
        a = build_provider_derived_bridge("120", HTML, "capture/run/page.html")
        self.assertEqual(a, build_provider_derived_bridge("120", HTML, "capture/run/page.html"))
        self.assertEqual(a["identity_class"], EXACT_PROVIDER_DERIVED)

    def test_c03_names_only_and_ambiguous_source_fail_closed(self):
        self.assertIsNone(extract_betclic_sportradar_reference('Sportivo - Nacional 730', '120'))
        self.assertIsNone(extract_betclic_sportradar_reference(HTML.replace('730","externalSportRef', '730","externalMatchRef":"731","externalSportRef'), '120'))

    def test_c04_c05_wrong_provider_or_id_cannot_join(self):
        bridge = build_provider_derived_bridge("120", HTML, "capture/run/page.html")
        with self.assertRaises(IdentityBridgeValidationError):
            validate_bridge_for_label(bridge, "121", "SPORTRADAR", "730")
        with self.assertRaises(IdentityBridgeValidationError):
            validate_bridge_for_label(bridge, "120", "SOFASCORE", "730")

    def test_c06_unverified_or_rejected_never_canonical(self):
        bridge = build_provider_derived_bridge("120", HTML, "capture/run/page.html")
        for classification in (UNVERIFIED, REJECTED):
            with self.subTest(classification=classification):
                with self.assertRaises(IdentityBridgeValidationError):
                    validate_bridge_for_label({**bridge, "identity_class": classification}, "120", "SPORTRADAR", "730")

    def test_c11_source_mutation_changes_bridge_identity(self):
        original = build_provider_derived_bridge("120", HTML, "capture/run/page.html")
        changed = build_provider_derived_bridge("120", HTML.replace('730', '731'), "capture/run/page.html")
        self.assertNotEqual(original["bridge_sha256"], changed["bridge_sha256"])

    def test_c12_one_to_one_conflicts_fail_closed(self):
        bridge = build_provider_derived_bridge("120", HTML, "capture/run/page.html")
        with self.assertRaises(IdentityBridgeValidationError):
            validate_one_to_one_bridges([bridge, {**bridge, "upstream_event_id": "731"}])
        with self.assertRaises(IdentityBridgeValidationError):
            validate_one_to_one_bridges([bridge, {**bridge, "provider_event_id": "121"}])

    def test_c13_append_only_artifact_does_not_overwrite(self):
        bridge = build_provider_derived_bridge("120", HTML, "capture/run/page.html")
        with tempfile.TemporaryDirectory() as directory:
            path = write_bridge_append_only(Path(directory), bridge)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["bridge_sha256"], bridge["bridge_sha256"])
            with self.assertRaises(FileExistsError): write_bridge_append_only(Path(directory), bridge)

    def test_c14_tampered_bridge_identity_fails_closed(self):
        bridge = build_provider_derived_bridge("120", HTML, "capture/run/page.html")
        with self.assertRaises(IdentityBridgeValidationError):
            validate_bridge_for_label({**bridge, "bridge_sha256": "0" * 64}, "120", "SPORTRADAR", "730")
        with self.assertRaises(IdentityBridgeValidationError):
            write_bridge_append_only(Path(tempfile.gettempdir()), {**bridge, "bridge_id": "wrong"})

    def test_c15_persisted_exact_bridge_can_be_reused_only_when_unique_and_valid(self):
        bridge = build_provider_derived_bridge("120", HTML, "capture/run/page.html")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_bridge_append_only(root, bridge)
            self.assertEqual(load_exact_persisted_bridge(root, "120"), bridge)
            second = build_provider_derived_bridge("120", HTML, "capture/run/page.html", "2026-01-01T00:00:00Z")
            write_bridge_append_only(root, second)
            with self.assertRaises(IdentityBridgeValidationError):
                load_exact_persisted_bridge(root, "120")
