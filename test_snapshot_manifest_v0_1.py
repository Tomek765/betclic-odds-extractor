from __future__ import annotations

import copy
import json
import os
import random
import tempfile
import unittest
from pathlib import Path

from snapshot_manifest_v0_1 import (
    SnapshotValidationError,
    build_manifest,
    build_manifest_from_sidecars,
    canonical_json_bytes,
    canonical_snapshot,
    write_manifest,
)
from snapshot_replay_v0_1 import verify_manifest_against_sidecars


def accepted_run() -> dict:
    return {
        "run_id": "run_test", "provider": "BETCLIC", "provider_event_id": "42",
        "kickoff_at": "2026-08-28T21:30:00Z",
        "capture_started_at": "2026-08-28T20:00:00Z",
        "capture_finished_at": "2026-08-28T20:00:10Z",
        "capture_status": "PREMATCH_VALID",
        "identity_validation": {"route_event_id": "42", "embedded_match_id": "42", "exact_match": True},
    }


def observation(sequence: int, payload: object, *, observed_at: str = "2026-08-28T20:00:01Z") -> dict:
    raw_id = f"run_test:{sequence}"
    return {
        "schema_version": "APEX_HISTORY_COLLECTION_CONTRACT_V0_1", "provider": "BETCLIC",
        "provider_event_id": "42", "observed_at": observed_at, "observation_sequence": sequence,
        "observation_id": raw_id, "raw_record_id": raw_id, "source_raw_record_ids": [raw_id],
        "disposition": "PENDING", "disposition_reason": None, "prematch_eligible": True,
        "prematch_ineligible_reason": None,
        "raw_observation": {"raw_record_id": raw_id, "source_hash": "a" * 64, "raw": payload},
    }


class SnapshotManifestV01Tests(unittest.TestCase):
    def manifest(self, observations: list[dict]) -> dict:
        return build_manifest(accepted_run(), observations, {"test": {"logical_path": "test", "sha256": "b" * 64}})

    def test_t01_t13_identical_replay_has_identical_identity_and_hash(self):
        first = self.manifest([observation(1, {"odds": "2.15"}), observation(2, {"odds": "2.15"}), observation(3, {"odds": "1.90"})])
        second = self.manifest(copy.deepcopy(first["canonical_snapshot"]["observations"][0:0]) or [observation(1, {"odds": "2.15"}), observation(2, {"odds": "2.15"}), observation(3, {"odds": "1.90"})])
        self.assertEqual((first["snapshot_id"], first["snapshot_sha256"]), (second["snapshot_id"], second["snapshot_sha256"]))

    def test_t02_permutations_preserve_hash_and_multiplicity(self):
        rows = [observation(1, {"odds": "2.15"}), observation(2, {"odds": "2.15"}), observation(3, {"odds": "1.90"})]
        expected = self.manifest(rows)["snapshot_sha256"]
        for seed in range(12):
            candidate = copy.deepcopy(rows); random.Random(seed).shuffle(candidate)
            self.assertEqual(expected, self.manifest(candidate)["snapshot_sha256"])
        manifest = self.manifest(rows)
        self.assertEqual((manifest["duplicate_content_group_count"], manifest["duplicate_content_occurrence_count"]), (1, 2))

    def test_t14_t22_t23_quote_mutation_and_duplicate_cardinality_change_hash(self):
        rows = [observation(1, {"odds": "2.15"}), observation(2, {"odds": "2.15"}), observation(3, {"odds": "1.90"})]
        original = self.manifest(rows)["snapshot_sha256"]
        changed = copy.deepcopy(rows); changed[0]["raw_observation"]["raw"]["odds"] = "2.16"
        self.assertNotEqual(original, self.manifest(changed)["snapshot_sha256"])
        self.assertNotEqual(original, self.manifest(rows[1:])["snapshot_sha256"])
        self.assertNotEqual(original, self.manifest(rows + [observation(4, {"odds": "2.15"})])["snapshot_sha256"])

    def test_t24_t25_sequence_and_provenance_are_artifact_material(self):
        rows = [observation(1, {"odds": "2.15"}), observation(2, {"odds": "2.15"})]
        original = self.manifest(rows)["snapshot_sha256"]
        changed_sequence = copy.deepcopy(rows); changed_sequence[1]["observation_sequence"] = 9
        self.assertNotEqual(original, self.manifest(changed_sequence)["snapshot_sha256"])
        changed_provenance = copy.deepcopy(rows); changed_provenance[1]["raw_observation"]["source_hash"] = "c" * 64
        self.assertNotEqual(original, self.manifest(changed_provenance)["snapshot_sha256"])

    def test_t27_t28_t29_t30_canonical_scalar_rules(self):
        self.assertEqual(canonical_json_bytes("é"), canonical_json_bytes("e\u0301"))
        self.assertNotEqual(canonical_json_bytes("2.15"), canonical_json_bytes("2,15"))
        first = [observation(1, {"odds": "2.15"}, observed_at="2026-08-28T20:00:01Z")]
        second = [observation(1, {"odds": "2.15"}, observed_at="2026-08-28T22:00:01+02:00")]
        self.assertEqual(self.manifest(first)["snapshot_sha256"], self.manifest(second)["snapshot_sha256"])
        self.assertNotEqual(canonical_json_bytes({"line": None}), canonical_json_bytes({}))
        self.assertNotEqual(canonical_json_bytes({"line": 0}), canonical_json_bytes({"line": None}))
        self.assertNotEqual(canonical_json_bytes("2.0"), canonical_json_bytes(2.0))

    def test_prematch_boundary_fails_closed(self):
        row = observation(1, {"odds": "2.15"}, observed_at="2026-08-28T21:30:00Z")
        row["prematch_eligible"] = False
        with self.assertRaises(SnapshotValidationError):
            canonical_snapshot(accepted_run(), [row])

    def test_t15_manifest_ignores_filesystem_mtime_and_independent_replay_validates(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary); run_path = root / "history_run_run_test.json"; obs_path = root / "history_observations_run_test.jsonl"
            run_path.write_text(json.dumps(accepted_run()), encoding="utf-8")
            obs_path.write_text("\n".join(json.dumps(item) for item in [observation(1, {"odds": "2.15"}), observation(2, {"odds": "2.15"})]) + "\n", encoding="utf-8")
            first = build_manifest_from_sidecars(run_path, obs_path)
            os.utime(run_path, (1, 1)); os.utime(obs_path, (2, 2))
            second = build_manifest_from_sidecars(run_path, obs_path)
            self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])
            manifest_path = write_manifest(root / "manifests", first)
            self.assertTrue(verify_manifest_against_sidecars(manifest_path, run_path, obs_path)["valid"])

    def test_real_patch_a_artifacts_replay_and_provenance_matrix(self):
        root = Path(__file__).parent / "diagnostics" / "history_v0_1"
        for run_id in ("run_1787949287_1344", "run_1787949360_11724"):
            run_path = root / f"history_run_{run_id}.json"; observations_path = root / f"history_observations_{run_id}.jsonl"
            manifest = build_manifest_from_sidecars(run_path, observations_path)
            rows = manifest["canonical_snapshot"]["observations"]
            self.assertEqual(len(rows), 380)
            self.assertEqual(manifest["duplicate_content_group_count"], 131)
            self.assertEqual(manifest["duplicate_content_occurrence_count"], 281)
            self.assertEqual({row["occurrence"]["raw_record_id"] for row in rows}, {row["occurrence"]["raw_observation"]["raw_record_id"] for row in rows})
            self.assertTrue(all(row["occurrence"]["raw_observation"].get("source_hash") for row in rows))
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
                manifest_path = write_manifest(Path(temporary), manifest)
                self.assertTrue(verify_manifest_against_sidecars(manifest_path, run_path, observations_path)["valid"])

    def test_finalization_juventus_parma_frozen_snapshot_replays_repeatedly(self):
        root = Path(__file__).parent / "diagnostics" / "history_v0_1"
        manifest_path = root / "manifests" / "history_snapshot_manifest_run_1788022903_5608.json"
        run_path = root / "history_run_run_1788022903_5608.json"
        observations_path = root / "history_observations_run_1788022903_5608.jsonl"
        first = verify_manifest_against_sidecars(manifest_path, run_path, observations_path)
        second = verify_manifest_against_sidecars(manifest_path, run_path, observations_path)
        self.assertTrue(first["valid"] and second["valid"])
        self.assertEqual(first["snapshot_id"], "apex-snapshot-v0.1:bbcf6c308182edd010333ce2ee68443e")
        self.assertEqual(first["replayed_snapshot_sha256"], second["replayed_snapshot_sha256"])
