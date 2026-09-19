from copy import deepcopy
import hashlib
import hmac
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

import evidence
import handoff
from schema import parse
import state
import storage
from support import Sandbox, TEXT, record


def changed(value, path, replacement):
    result = deepcopy(value)
    target = result
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement
    return result


class StorageAndStateTests(Sandbox):
    def test_hash_serialization_private_atomic_write_and_failure(self):
        self.assertEqual(storage.digest("α"), hashlib.sha256("α".encode()).hexdigest())
        self.assertEqual(storage.digest(b"abc"), storage.digest("abc"))
        path = self.root / "nested/value.json"
        storage.atomic_write(path, storage.json_text({"value": "α"}))
        self.assertEqual(storage.read_json(path), {"value": "α"})
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with patch.object(Path, "replace", side_effect=OSError("disk failure")), self.assertRaisesRegex(OSError, "disk failure"):
            storage.atomic_write(path, b"replacement")
        self.assertEqual(storage.read_json(path), {"value": "α"})
        with self.assertRaises(ValueError):
            storage.json_text({"bad": float("nan")})

    def test_paths_cannot_escape_or_follow_symlink_components(self):
        for value in (self.root / "absolute", "..", "../escape", ".", "a/../.."):
            with self.subTest(path=value), self.assertRaises(ValueError):
                storage.inside(self.root, value)
        self.assertEqual(storage.inside(self.root, "a/../file"), self.root / "file")
        (self.root / "link").symlink_to(self.home, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            storage.inside(self.root, "link/new")

    def test_request_state_and_deterministic_question_namespace(self):
        self.assertEqual(state.prepare_review(self.root, "Question   Text"), state.prepare_review(self.root, "question text"))
        self.assertEqual(state.prepare_review(self.root), str(self.root))
        self.assertIsNone(state.read_request(self.root))
        state.pause_request(self.root, "Q")
        self.assertEqual(state.read_request(self.root), {"status": "paused", "question": "Q"})
        request = {"status": "awaiting_callimachus", "question": "Original", "reason": "More data"}
        state.write_request(self.root, request)
        state.pause_request(self.root, "Changed")
        self.assertEqual(state.read_request(self.root), request)
        with self.assertRaisesRegex(ValueError, "Invalid data"):
            state.write_request(self.root, {"question": "Missing status"})
        self.assertEqual(state.read_request(self.root), request)


class HandoffTests(Sandbox):
    def test_signing_key_creation_reuse_permissions_and_concurrent_creation(self):
        with self.assertRaises(FileNotFoundError):
            handoff.signing_key(False)
        key = handoff.signing_key(True)
        self.assertEqual(len(key), 32)
        self.assertEqual(handoff.signing_key(True), key)
        self.assertEqual(handoff.seal({"test": "α"}), hmac.new(key, storage.json_text({"test": "α"}).encode(), hashlib.sha256).hexdigest())
        if os.name != "nt":
            self.assertEqual((self.home / ".arlandria/completion.key").stat().st_mode & 0o777, 0o600)
        with patch.object(Path, "exists", return_value=False):
            self.assertEqual(handoff.signing_key(True), key)

    def test_gate_fingerprints_cover_only_their_respective_state(self):
        value = self.review(complete=False)
        initial = {gate: handoff.gate_fingerprint(self.root, gate) for gate in handoff.GATES}
        value["records"][0]["screening"]["fulltext"]["reason"] = "More detail"
        self.write("ledger.json", value)
        self.assertEqual(handoff.gate_fingerprint(self.root, "criteria"), initial["criteria"])
        self.assertEqual(handoff.gate_fingerprint(self.root, "triage"), initial["triage"])
        self.assertNotEqual(handoff.gate_fingerprint(self.root, "curation"), initial["curation"])
        value["records"][0]["status"] = "deferred"
        self.write("ledger.json", value)
        self.assertNotEqual(handoff.gate_fingerprint(self.root, "triage"), initial["triage"])
        value["question"] = "New question"
        self.write("ledger.json", value)
        self.assertNotEqual(handoff.gate_fingerprint(self.root, "criteria"), initial["criteria"])
        with self.assertRaisesRegex(ValueError, "Unknown approval"):
            handoff.gate_fingerprint(self.root, "unknown")
        before = (self.root / ".callimachus/approvals.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "changed during approval"):
            handoff.approve_gate(self.root, "criteria", initial["criteria"])
        self.assertEqual((self.root / ".callimachus/approvals.json").read_bytes(), before)

    def test_completion_rejects_incomplete_or_ambiguous_reviews(self):
        original = self.review(complete=False)
        cases = [
            (["queries"], [], "search/pool audit"),
            (["records"], [original["records"][0]] * 2, "Duplicate record"),
            (["records", 0, "screening", "abstract", "decision"], "unscreened", "screening incomplete"),
            (["records", 0, "screening", "fulltext", "decided_by"], "llm", "Human full-text disposition"),
            (["records", 0, "screening", "fulltext", "reason"], None, "Human full-text disposition"),
            (["records", 0, "screening", "fulltext", "decision"], "unscreened", "Human full-text disposition"),
            (["records", 0, "status"], "deferred", "Source registry"),
        ]
        for path, replacement, error in cases:
            with self.subTest(path=path, replacement=replacement):
                self.write("ledger.json", changed(original, path, replacement))
                self.approve()
                with self.assertRaisesRegex(ValueError, error):
                    handoff.finalize(self.root)
        stale = deepcopy(original)
        stale["records"][0]["screening"]["abstract"].update(decided_by="llm", criteria_version=0)
        self.write("ledger.json", stale)
        self.approve()
        with self.assertRaisesRegex(ValueError, "Stale abstract"):
            handoff.finalize(self.root)
        self.assertFalse((self.root / ".callimachus/current.json").exists())

    def test_excluded_and_deferred_records_do_not_need_fulltext_curation(self):
        value = self.review(complete=False)
        deferred = deepcopy(value["records"][0])
        deferred["id"] = "deferred"
        deferred["status"] = "deferred"
        deferred["screening"]["fulltext"]["decision"] = "unscreened"
        excluded = record(title="Excluded")
        excluded["screening"]["abstract"].update(decision="exclude", criteria_version=1)
        value["records"].extend([deferred, excluded])
        self.write("ledger.json", value)
        self.approve()
        handoff.finalize(self.root)
        self.assertEqual(handoff.load_snapshot(self.root)["handoff"]["included_ids"], ["paper-1"])

    def test_fulltext_extraction_integrity_and_abstract_availability(self):
        self.review(fulltext=True, complete=False)
        original = self.read("extraction.json")
        for path, replacement, error in (
            (["pdf_sha256"], "0" * 64, "PDF/extraction mismatch"),
            (["pages", 0, "text"], "   ", "Empty extraction"),
            (["pages", 0, "page"], 2, "Invalid page sequence"),
        ):
            with self.subTest(error=error):
                self.write("extraction.json", changed(original, path, replacement))
                self.approve()
                with self.assertRaisesRegex(ValueError, error):
                    handoff.finalize(self.root)
        value = self.review(complete=False)
        value["records"][0]["abstract"] = " "
        self.write("ledger.json", value)
        self.approve()
        with self.assertRaisesRegex(ValueError, "No usable abstract"):
            handoff.finalize(self.root)

    def test_export_and_concurrent_finalization_failures_keep_current_pointer(self):
        snapshot, _, _ = self.review()
        original = (self.root / ".callimachus/current.json").read_bytes()
        with patch.object(handoff.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"", b"export failed")), self.assertRaisesRegex(ValueError, "Final export failed"):
            handoff.finalize(self.root)
        self.assertEqual((self.root / ".callimachus/current.json").read_bytes(), original)
        inputs = handoff.completion_inputs
        calls = 0

        def mutate_after_validation(root):
            nonlocal calls
            result = inputs(root)
            calls += 1
            if calls == 2:
                value = self.read()
                value["question"] = "Changed mid-finalize"
                self.write("ledger.json", value)
            return result

        with patch.object(handoff, "completion_inputs", side_effect=mutate_after_validation), self.assertRaisesRegex(ValueError, "changed during finalization"):
            handoff.finalize(self.root)
        self.assertEqual((self.root / ".callimachus/current.json").read_bytes(), original)
        self.assertTrue(Path(snapshot["directory"]).is_dir())

    def test_snapshot_rejects_bad_pointers_signatures_revisions_and_artifacts(self):
        snapshot, _, _ = self.review()
        pointers: list[object] = [[], {"revision": 2}, {"revision": "../escape"}]
        for pointer in pointers:
            self.write(".callimachus/current.json", pointer)
            with self.assertRaisesRegex(ValueError, "Invalid completion pointer"):
                handoff.load_snapshot(self.root)
        self.write(".callimachus/current.json", {"revision": snapshot["handoff"]["revision"]})
        with self.assertRaisesRegex(ValueError, "newer Callimachus"):
            handoff.load_snapshot(self.root, "old")
        path = Path(snapshot["directory"]) / "handoff.json"
        original = storage.read_json(path)
        for signature in ("0" * 64, "not-a-signature"):
            storage.atomic_write(path, storage.json_text({**original, "seal": signature}))
            with self.assertRaisesRegex(ValueError, "Untrusted"):
                handoff.load_snapshot(self.root)
        unsigned = {k: v for k, v in original.items() if k != "seal"}
        unsigned["revision"] = "different"
        storage.atomic_write(path, storage.json_text({**unsigned, "seal": handoff.seal(unsigned)}))
        with self.assertRaisesRegex(ValueError, "Revision mismatch"):
            handoff.load_snapshot(self.root)
        storage.atomic_write(path, storage.json_text(original))
        storage.atomic_write(Path(snapshot["directory"]) / "references.csv", "tampered")
        with self.assertRaisesRegex(ValueError, "Modified snapshot artifact"):
            handoff.load_snapshot(self.root)

    def test_upstream_approvals_and_source_changes_require_new_completion(self):
        self.review(fulltext=True)
        self.write(".callimachus/approvals.json", {})
        with self.assertRaisesRegex(ValueError, "Pending or stale"):
            handoff.load_snapshot(self.root)
        self.approve()
        extraction = self.read("extraction.json")
        extraction["warnings"].append("Changed warning")
        self.write("extraction.json", extraction)
        self.approve()
        with self.assertRaisesRegex(ValueError, "Upstream source changed"):
            handoff.load_snapshot(self.root)
        self.review()
        value = self.read()
        value["question"] = "Changed"
        self.write("ledger.json", value)
        with self.assertRaisesRegex(ValueError, "Callimachus has changed"):
            handoff.load_snapshot(self.root)


class EvidenceTests(Sandbox):
    def test_validation_rejects_broken_provenance_and_feasibility(self):
        snapshot, document, context = self.review()
        cases = [
            (["handoff_revision"], "wrong", "different revision"),
            (["findings", 0, "id"], "c1", "Duplicate evidence"),
            (["claims", 0, "quote"], "Never in the source", "Quote not found"),
            (["claims", 0, "page"], 2, "Quote not found"),
            (["claims", 0, "source_id"], "external", "Source is not"),
            (["claims", 0, "verification", "status"], "uncertain", "Unsupported claim"),
            (["findings", 0, "claim_ids"], ["missing"], "Unsupported claim"),
            (["findings", 0, "disagreements"], ["missing"], "Missing disagreement"),
            (["gaps", 0, "claim_ids"], ["c1"], "author-stated gap"),
            (["gaps", 0, "currency", "checked_source_ids"], ["external"], "external source"),
            (["gaps", 0, "currency", "checked_source_ids"], [], "completed corpus"),
            (["gaps", 0, "status"], "addressed", "supporting claims"),
            (["opportunities", 0, "gap_id"], "missing", "missing gap"),
            (["opportunities", 0, "direction_claim_ids"], ["c1"], "author-proposed direction"),
            (["opportunities", 0, "feasibility", "resource_ids"], ["unknown"], "did not supply"),
            (["opportunities", 0, "feasibility", "resource_ids"], [], "Low effort"),
            (["opportunities", 0, "feasibility", "prerequisites"], [], "Low effort"),
            (["opportunities", 0, "feasibility", "unknowns"], ["Cost"], "Low effort"),
            (["gaps", 0, "status"], "unresolved", "Low effort"),
            (["source_reviews"], document["source_reviews"] * 2, "source review coverage"),
            (["source_reviews", 0, "source_id"], "outside", "source review coverage"),
        ]
        for path, replacement, error in cases:
            with self.subTest(path=path, replacement=replacement), self.assertRaisesRegex(ValueError, error):
                evidence.validate_evidence(snapshot, changed(document, path, replacement), context)

    def test_partial_evidence_is_allowed_but_cannot_be_delivered(self):
        snapshot, document, context = self.review()
        document["gaps"][0].update(status="unresolved")
        document["gaps"][0]["currency"]["checked_source_ids"] = []
        document["opportunities"][0]["feasibility"]["effort"] = "unknown"
        document["source_reviews"] = []
        evidence.validate_evidence(snapshot, document, context)
        with self.assertRaisesRegex(ValueError, "Every included source"):
            evidence.validate_delivery(snapshot, document)
        document["source_reviews"] = [{"source_id": "paper-1", "status": "unreadable", "note": "Illegible"}]
        with self.assertRaisesRegex(ValueError, "Unreadable sources"):
            evidence.validate_delivery(snapshot, document)

    def test_source_pagination_unicode_and_invalid_locators(self):
        snapshot, _, _ = self.review()
        long_text = "αβ≤" * 5000
        artifact = Path(snapshot["directory"]) / "source-0.json"
        storage.atomic_write(artifact, storage.json_text({"pages": [{"page": 1, "text": long_text}]}))
        first = evidence.source_passage(snapshot, "paper-1", 1, 0)
        second = evidence.source_passage(snapshot, "paper-1", 1, first["next_offset"])
        self.assertEqual(first["text"] + second["text"], long_text)
        self.assertIsNone(second["next_offset"])
        self.assertEqual(evidence.source_passage(snapshot, "paper-1", 1, 99999)["text"], "")
        for page, offset in ((0, 0), (1, -1), ("1", 0), (1, 1.5), (2, 0), (True, 0), (1, False)):
            with self.subTest(page=page, offset=offset), self.assertRaises(ValueError):
                evidence.source_passage(snapshot, "paper-1", page, offset)

    def test_evidence_history_idempotency_context_digest_and_stale_write_rejection(self):
        snapshot, document, context = self.review()
        directory = evidence.evidence_directory(snapshot)
        initial = evidence.evidence_digest(snapshot)
        first = evidence.save_evidence(snapshot, document)
        second = evidence.save_evidence(snapshot, document)
        self.assertEqual(first, second)
        self.assertEqual(len(list((directory / "history").glob("*.json"))), 1)
        document["findings"][0]["strength"] = "Revised appraisal"
        evidence.save_evidence(snapshot, document)
        self.assertEqual(len(list((directory / "history").glob("*.json"))), 2)
        self.assertNotEqual(evidence.evidence_digest(snapshot), initial)
        current = evidence.evidence_digest(snapshot)
        evidence.save_context(snapshot, {**context, "audience": "General public"})
        self.assertNotEqual(evidence.evidence_digest(snapshot), current)
        before = (directory / "evidence.json").read_bytes()
        self.write("ledger.json", {**self.read(), "question": "Different scope"})
        with self.assertRaisesRegex(ValueError, "Callimachus has changed"):
            evidence.save_evidence(snapshot, document)
        self.assertEqual((directory / "evidence.json").read_bytes(), before)

    def test_schema_contracts_reject_extra_fields_and_wrong_types(self):
        snapshot, document, context = self.review()
        for name, value in (("Evidence", document), ("Context", context), ("Handoff", snapshot["handoff"])):
            self.assertIs(parse(name, value), value)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Invalid data"):
                parse(name, {"unexpected": True})
        self.assertEqual(evidence.source_pages(snapshot, "paper-1")[0]["text"], TEXT)
