from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import tempfile
import unittest

from interview_hub.store import ConflictError, NotFoundError, Store


class InterviewStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "nested" / "interviews.sqlite3"
        self.store = Store(self.path)
        self.material = {"commit_sha": "a" * 40, "claims": [{"claim_id": "claim-1", "text": "Project fact"}],
                         "questions": [{"question_id": "q1"}]}
        self.session = {"mode": "mock_interview", "resume_version_id": "resume-v1"}
        self.result = {"answers": [{"question_id": "q1", "text": "A response"}], "observations": []}

    def tearDown(self):
        self.temp.cleanup()

    def seed_session(self, owner="alice", session_id="session-1", material_id="material-1"):
        self.store.put_material(owner, material_id, self.material)
        return self.store.create_session(owner, session_id, material_id, self.session)

    def test_material_is_immutable_and_canonical_retries_preserve_timestamp(self):
        first = self.store.put_material("alice", "material-1", self.material)
        reordered = {key: self.material[key] for key in reversed(list(self.material))}
        self.assertEqual(self.store.put_material("alice", "material-1", reordered), first)
        changed = copy.deepcopy(self.material)
        changed["commit_sha"] = "b" * 40
        with self.assertRaises(ConflictError):
            self.store.put_material("alice", "material-1", changed)
        self.assertEqual(self.store.get_material("alice", "material-1")["payload"], self.material)

    def test_owner_isolation_in_every_read_and_write_path(self):
        self.seed_session()
        self.store.save_result("alice", "session-1", self.result)
        self.store.save_recap("alice", "session-1", {"summary": "Alice only"})
        for method in (self.store.get_material, self.store.get_session,
                       self.store.get_result, self.store.get_recap):
            identifier = "material-1" if method == self.store.get_material else "session-1"
            with self.subTest(method=method.__name__), self.assertRaises(NotFoundError):
                method("bob", identifier)
        with self.assertRaises(NotFoundError):
            self.store.create_session("bob", "session-1", "material-1", self.session)
        with self.assertRaises(NotFoundError):
            self.store.save_result("bob", "session-1", self.result)
        with self.assertRaises(NotFoundError):
            self.store.save_recap("bob", "session-1", {"summary": "Stolen"})
        self.assertEqual(self.store.history("bob"), [])
        self.assertEqual(self.store.list_materials("bob"), [])

    def test_same_identifiers_are_separate_between_owners(self):
        self.seed_session("alice")
        bob_material = {"claims": [{"claim_id": "claim-2"}]}
        self.store.put_material("bob", "material-1", bob_material)
        self.store.create_session("bob", "session-1", "material-1", self.session)
        self.store.save_result("bob", "session-1", {"answers": []})
        self.assertEqual(self.store.get_session("alice", "session-1")["state"], "in_progress")
        self.assertEqual(self.store.get_material("alice", "material-1")["payload"], self.material)
        self.assertEqual(self.store.history("bob")[0]["material"]["payload"], bob_material)
        self.assertEqual(self.store.history("alice")[0]["result"], None)

    def test_session_cannot_change_its_material_or_initial_configuration(self):
        first = self.seed_session()
        self.store.put_material("alice", "material-2", {"claims": []})
        self.assertEqual(self.store.create_session("alice", "session-1", "material-1", self.session), first)
        with self.assertRaises(ConflictError):
            self.store.create_session("alice", "session-1", "material-2", self.session)
        with self.assertRaises(ConflictError):
            self.store.create_session("alice", "session-1", "material-1", {"mode": "resume_readiness"})

    def test_result_finalization_is_atomic_and_retries_cannot_replace_answers(self):
        self.seed_session()
        first = self.store.save_result("alice", "session-1", self.result)
        self.assertEqual(self.store.get_session("alice", "session-1")["state"], "completed")
        self.assertEqual(self.store.save_result("alice", "session-1", self.result), first)
        with self.assertRaises(ConflictError):
            self.store.save_result("alice", "session-1", {"answers": []})
        self.assertEqual(self.store.get_result("alice", "session-1"), first)

    def test_recap_requires_result_and_is_saved_without_overwriting_prior_record(self):
        self.seed_session()
        with self.assertRaises(ConflictError):
            self.store.save_recap("alice", "session-1", {"summary": "Too soon"})
        self.store.save_result("alice", "session-1", self.result)
        first = self.store.save_recap("alice", "session-1", {"review_status": "pending", "tasks": []})
        self.assertEqual(self.store.save_recap("alice", "session-1", {"tasks": [], "review_status": "pending"}), first)
        with self.assertRaises(ConflictError):
            self.store.save_recap("alice", "session-1", {"review_status": "confirmed"})
        self.assertEqual(self.store.get_recap("alice", "session-1"), first)

    def test_unknown_references_leave_no_partial_records(self):
        with self.assertRaises(NotFoundError):
            self.store.create_session("alice", "session-1", "missing-material", {})
        with self.assertRaises(NotFoundError):
            self.store.save_result("alice", "missing-session", {})
        with self.assertRaises(NotFoundError):
            self.store.save_recap("alice", "missing-session", {})
        self.assertEqual(self.store.history("alice"), [])

    def test_history_joins_frozen_material_and_filters_before_pagination(self):
        self.seed_session(session_id="old-session")
        self.store.save_result("alice", "old-session", self.result)
        self.store.save_recap("alice", "old-session", {"tasks": ["Read source"]})
        self.store.put_material("alice", "unrelated-material", {"claims": [{"claim_id": "other"}]})
        self.store.create_session("alice", "unrelated-session", "unrelated-material", {})
        self.seed_session(session_id="new-session")
        first = self.store.history("alice", claim_id="claim-1", limit=1)
        second = self.store.history("alice", claim_id="claim-1", limit=1, offset=1)
        self.assertEqual(first[0]["session"]["session_id"], "new-session")
        self.assertIsNone(first[0]["result"])
        self.assertEqual(second[0]["session"]["session_id"], "old-session")
        self.assertEqual(second[0]["material"]["payload"]["commit_sha"], "a" * 40)
        self.assertEqual(second[0]["recap"]["payload"]["tasks"], ["Read source"])
        self.assertEqual(second[0]["result"]["payload"], self.result)

    def test_records_survive_reopening_database_and_return_detached_payloads(self):
        self.seed_session()
        self.store.save_result("alice", "session-1", self.result)
        record = self.store.get_material("alice", "material-1")
        record["payload"]["claims"][0]["text"] = "Mutated local copy"
        reopened = Store(self.path)
        self.assertEqual(reopened.get_material("alice", "material-1")["payload"], self.material)
        self.assertEqual(reopened.get_result("alice", "session-1")["payload"], self.result)

    def test_parallel_identical_result_retries_create_one_stable_record(self):
        self.seed_session()
        with ThreadPoolExecutor(max_workers=4) as workers:
            saved = list(workers.map(lambda _: self.store.save_result("alice", "session-1", self.result), range(8)))
        self.assertTrue(all(record == saved[0] for record in saved))
        self.assertEqual(len(self.store.history("alice")), 1)

    def test_payload_and_query_validation_does_not_mutate_history(self):
        with self.assertRaises(ValueError):
            self.store.put_material("alice", "material-1", {"number": float("nan")})
        with self.assertRaises(ValueError):
            self.store.put_material("", "material-1", {})
        for limit, offset in [(0, 0), (101, 0), (True, 0), (1, -1), (1, False)]:
            with self.subTest(limit=limit, offset=offset), self.assertRaises(ValueError):
                self.store.history("alice", limit=limit, offset=offset)
        self.assertEqual(self.store.history("alice"), [])


if __name__ == "__main__":
    unittest.main()
