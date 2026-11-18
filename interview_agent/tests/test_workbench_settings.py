"""No-key startup and configuration changes must preserve running work."""

import asyncio
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
from interview_agent.api import create_app
from interview_agent.model_adapter import ModelError
from interview_agent.note_subscriptions import NoteSubscriptions

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "web")]
from workbench_services import ModelSettings


class ManagedModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_key_starts_full_local_services_and_fails_only_model_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = ModelSettings(root, offline=True)
            model = settings.model()
            await model.start()
            try:
                self.assertFalse(settings.status()["configured"])
                with self.assertRaises(ModelError) as result:
                    await model.decide("workbench_decide", {})
                self.assertEqual(result.exception.code, "missing_model_credential")
            finally:
                await model.close()

    async def test_pending_configuration_waits_for_all_running_work_and_applies_without_restart(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"INTERVIEW_API_KEY": ""}):
            settings = ModelSettings(Path(directory), offline=True)
            first, second = settings.model(), settings.model()
            first.is_busy = lambda: True
            settings.pending_key, settings.revision = "synthetic-new-key", 1
            replacement = Mock(close=AsyncMock())
            adapter = Mock(start=AsyncMock(return_value=replacement))
            with patch("interview_agent.model_adapter.ModelAdapter", return_value=adapter) as factory:
                await first.apply_pending()
                factory.assert_not_called()
                self.assertTrue(settings.status()["pending"])
                first.is_busy = lambda: False
                await first.apply_pending()
                self.assertIs(first.delegate, replacement)
                self.assertTrue(settings.status()["pending"])
                await second.apply_pending()
                self.assertFalse(settings.status()["pending"])
                self.assertEqual(settings.active_key, "synthetic-new-key")
            await first.close();await second.close()

    def test_no_key_http_routes_still_expose_conversations_knowledge_and_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = ModelSettings(root, offline=True)
            app = create_app(root / "business.db", root / "checkpoints.db", "isolated-user", "synthetic-local-token-123456",
                             agent=settings.model(), career_root=root / "career")
            with TestClient(app, headers={"Authorization": "Bearer synthetic-local-token-123456"}) as client:
                self.assertEqual(client.get("/v1/workbench/overview").status_code, 200)
                self.assertEqual(client.get("/v1/knowledge/sources").status_code, 200)
                self.assertEqual(client.get("/v1/notes/subscriptions").status_code, 200)
                self.assertEqual(client.post("/v1/workbench/conversations", json={"title": "无密钥启动"}).status_code, 201)

    def test_note_inbox_paginates_all_messages_without_losing_unread_counts(self):
        class Collector:
            index = 0
            def fetch(self, url):
                self.index += 1
                return {"ok": True, "reason": "success", "title": "虚构面经", "author": "合成作者", "content": "合成更新 " + str(self.index), "images": []}
        with tempfile.TemporaryDirectory() as directory:
            service = NoteSubscriptions(Path(directory), "isolated-user", collector=Collector())
            for _ in range(35):
                service.collect("https://www.xiaohongshu.com/explore/0123456789abcdef01234567")
            page = service.inbox(30, 0)
            self.assertEqual((len(page["items"]), page["total"], page["unread"], page["next_offset"]), (30, 35, 35, 30))
            next_page = service.inbox(30, page["next_offset"])
            self.assertEqual(len(next_page["items"]), 5)
            self.assertIsNone(next_page["next_offset"])

    def test_overview_restores_completed_interviews_as_reopenable_results_without_model(self):
        from interview_agent.tests.test_workbench import fixture_material
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = ModelSettings(root, offline=True)
            app = create_app(root / "business.db", root / "checkpoints.db", "isolated-user", "synthetic-local-token-123456",
                             agent=settings.model(), career_root=root / "career")
            with TestClient(app, headers={"Authorization": "Bearer synthetic-local-token-123456"}) as client:
                store = app.state.workbench.repo.store
                for owner, sid in (("isolated-user", "finished"), ("other-user", "private")):
                    store.put_material(owner, "mat_confirmed", fixture_material())
                    store.create_session(owner, sid, "mat_confirmed", {"target": {"role": "合成后端"}})
                    store.save_result(owner, sid, {"summary": "合成复盘"})
                result = client.get("/v1/workbench/overview").json()
                self.assertEqual(result["tasks"], [])
                self.assertEqual([r["interview_id"] for r in result["results"]], ["finished"])
                self.assertEqual(result["results"][0]["interview_kind"], "project")


if __name__ == "__main__":
    unittest.main()
