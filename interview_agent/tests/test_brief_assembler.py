"""综合模拟面试契约与 BriefAssembler 单元测试（M1）。"""

import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from interview_agent.brief_assembler import BriefAssembler
from interview_agent.comprehensive_contracts import (
    ComprehensiveTurn,
    ExternalReferenceInput,
    JobContextInput,
    StartComprehensiveInterview,
)
from interview_agent.repository import Repository
from interview_hub.career_store import CareerRecords
from interview_hub.store import ConflictError, NotFoundError, Store


class FakeKnowledge:
    """隔离测试用知识库替身，模拟已就绪与未就绪快照。"""

    def __init__(self, sources=None, contexts=None):
        self._sources = sources or []
        self._contexts = contexts or {}

    def all_sources(self):
        return self._sources

    def context(self, snapshot_id):
        if snapshot_id not in self._contexts:
            if any(s["source_id"] == snapshot_id for s in self._sources):
                raise ConflictError("Knowledge is not ready")
            raise NotFoundError("Snapshot not found")
        return self._contexts[snapshot_id]


class FakeNotes:
    """隔离测试用面经收藏替身。"""

    def __init__(self, notes_by_id=None):
        self._notes = notes_by_id or {}

    def note(self, note_id):
        if note_id not in self._notes:
            raise NotFoundError("Note not found")
        return self._notes[note_id]


class ComprehensiveContractsTests(unittest.TestCase):
    def test_turn_requires_nonblank_text_except_control_commands(self):
        with self.assertRaises(ValidationError):
            ComprehensiveTurn(event_id="ev_1", text="   ")
        turn_skip = ComprehensiveTurn(event_id="ev_2", text="", command="skip")
        self.assertEqual(turn_skip.command, "skip")
        turn_asr = ComprehensiveTurn(
            event_id="ev_3",
            text="这是语音转文字的回答",
            input_channel="asr_transcript",
        )
        self.assertEqual(turn_asr.input_channel, "asr_transcript")

    def test_start_rejects_unknown_fields_and_invalid_duration(self):
        with self.assertRaises(ValidationError):
            StartComprehensiveInterview(duration_minutes=25)
        with self.assertRaises(ValidationError):
            StartComprehensiveInterview(extra_field="bad")


class BriefAssemblerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "interview.db"
        self.owner = "user-test"
        self.store = Store(self.db_path)
        self.repo = Repository(self.store, self.owner)
        self.records = CareerRecords(self.db_path, self.owner)

    def tearDown(self):
        self._tmp.cleanup()

    def _seed_project_and_resume(self):
        commit = "a" * 40
        claim_id = "claim_order_cache"
        material = {
            "material_id": "mat_order",
            "schema_version": 1,
            "is_demo": False,
            "resume_version_id": "resume_v1",
            "source_commit": commit,
            "source_repository": "demo/order-service",
            "project_snapshot_id": "psnap_order",
            "claims": [
                {
                    "claim_id": claim_id,
                    "pillar": "缓存与降级",
                    "text": "主导 Redis 缓存穿透防护与本地降级，接口 P99 延迟降低 35%。",
                    "boundary": "独立完成降级模块，压测由团队协同",
                    "risk": "",
                    "personal_contribution": "confirmed",
                    "evidence_ids": ["ev_cache_1"],
                }
            ],
            "evidence": [
                {
                    "evidence_id": "ev_cache_1",
                    "commit_sha": commit,
                    "path": "cache/fallback.py",
                    "line_start": 1,
                    "line_end": 25,
                    "text": "def get_with_fallback(): pass",
                    "source_url": "urn:demo:ev_cache_1",
                }
            ],
            "questions": [
                {
                    "question_id": "q1",
                    "claim_id": claim_id,
                    "text": "缓存穿透如何降级？",
                    "evidence_ids": ["ev_cache_1"],
                    "expected_facts": [],
                }
            ],
            "contribution_statement": "负责核心缓存降级设计",
            "target": {"role": "后端开发"},
            "job_snapshot": {"role": "后端开发", "jd": "熟悉高并发缓存"},
        }
        self.store.put_material(self.owner, "mat_order", material)
        self.records.put(
            "project",
            "proj_order",
            {
                "project_id": "proj_order",
                "status": "ready",
                "source_type": "github",
                "repository": "demo/order-service",
                "source_commit": commit,
                "project_snapshot_id": "psnap_order",
                "project_name": "订单风控服务",
                "summary": "高并发订单与缓存降级服务",
                "contribution": "独立负责缓存与限流模块",
                "claims": material["claims"],
            },
        )
        self.records.put(
            "resume",
            "resume_v1",
            {
                "resume_version_id": "resume_v1",
                "material_id": "mat_order",
                "interview_material_id": "mat_order",
                "claim_ids": [claim_id],
                "markdown": "# 张三\n联系 13800138000 | test@example.com\n## 项目\nP99 延迟降低 35%。",
                "profile_snapshot": {
                    "truth_confirmed": True,
                    "basic": {
                        "name": "张三",
                        "phone": "13800138000",
                        "email": "test@example.com",
                        "wechat": "wx_secret_123",
                    },
                    "education": [{"school": "某大学", "major": "计算机", "degree": "本科", "start": "2022", "end": "2026"}],
                    "experiences": [{"company": "某科技", "title": "后端实习", "start": "2025-06", "end": "2025-09", "summary": "负责接口开发"}],
                    "projects": [
                        {
                            "name": "订单风控服务",
                            "role": "后端",
                            "summary": "接口 P99 延迟降低 60%。",
                        }
                    ],
                    "skills": {"tools": ["Python", "Redis"], "strengths": ["并发排查"]},
                    "summary": "应届后端开发，手机号 13912345678，sk-secretkey123456。",
                },
            },
        )
        self.records.put(
            "ci_debrief",
            "prev_round_1",
            {
                "session_id": "prev_round_1",
                "improvement_tasks": [
                    {
                        "task_id": "task_1",
                        "claim_id": claim_id,
                        "gap_type": "failure_boundary",
                        "action": "补齐缓存雪崩兜底指标",
                        "retest_prompt": "如果 Redis 集群整体不可用，本地降级如何避免内存被打爆？",
                        "completed": False,
                    }
                ],
                "red_flags_and_signals": [
                    {
                        "severity": "red_flag",
                        "category": "responsibility",
                        "summary": "上一轮曾把团队压测归为个人完成",
                    }
                ],
            },
        )
        return claim_id

    def test_full_assembly_redacts_pii_binds_knowledge_and_detects_conflicts(self):
        claim_id = self._seed_project_and_resume()
        knowledge = FakeKnowledge(
            sources=[
                {
                    "source_id": "ksrc_1",
                    "snapshot_id": "ksnap_order",
                    "project_ids": ["proj_order"],
                }
            ],
            contexts={
                "ksnap_order": {
                    "snapshot_id": "ksnap_order",
                    "coverage": {"complete": True, "document_units": 2, "document_ocr_units": 1},
                }
            },
        )
        notes = FakeNotes(
            {
                "note_1": {
                    "id": "note_1",
                    "title": "字节后端一面面经",
                    "content": "重点问了 Redis 缓存穿透与本地缓存淘汰策略。",
                    "source_url": "https://www.xiaohongshu.com/explore/123",
                }
            }
        )
        assembler = BriefAssembler(self.repo, knowledge=knowledge, notes=notes, records=self.records)
        req = StartComprehensiveInterview(
            session_id="ci_session_01",
            role_family="engineering",
            round="second",
            duration_minutes=45,
            resume_version_id="resume_v1",
            project_ids=["proj_order"],
            note_ids=["note_1"],
            job_snapshot=JobContextInput(
                job_id="job_bd_1",
                company="字节跳动",
                role="后端研发工程师",
                jd="负责高并发服务开发，熟悉 Redis 与容灾降级。",
            ),
            previous_session_id="prev_round_1",
            loop_id="loop_bd_1",
        )
        brief = assembler.assemble(req)

        self.assertEqual(brief.resume_binding, "immutable_version")
        self.assertFalse(brief.generic_role)
        self.assertEqual(brief.knowledge_snapshot_ids, ["ksnap_order"])
        self.assertEqual(brief.projects[0].available_source_kinds, ["source_text", "document_text"])
        self.assertTrue(brief.projects[0].has_ocr_units)

        # 脱敏验证：PII 与密钥不得进入冻结简报
        serialized = json.dumps(brief.model_dump(), ensure_ascii=False)
        for secret in ("13800138000", "13912345678", "test@example.com", "wx_secret_123", "sk-secretkey123456"):
            self.assertNotIn(secret, serialized)

        # 跨版本口径冲突验证：简历 35% vs 个人资料 60%
        self.assertEqual(len(brief.source_conflicts), 1)
        self.assertEqual(brief.source_conflicts[0].reason, "metric_mismatch")
        self.assertEqual(brief.source_conflicts[0].primary_source, "选定简历版本")

        # Mock Loop 上一轮未闭环任务与红线进入高优复测议题
        self.assertGreaterEqual(len(brief.history_agenda), 2)
        self.assertEqual(brief.history_agenda[0].priority, "high")
        self.assertEqual(brief.external_references[0].kind, "xhs_note")
        self.assertEqual(brief.external_references[0].source_label, "REF_COMPANY_OR_JINGYAN")
        self.assertEqual(brief.projects[0].claims[0].claim_id, claim_id)

        # 幂等重试返回同一 brief_id；同 session_id 修改参数返回冲突
        brief_again = assembler.assemble(req)
        self.assertEqual(brief_again.brief_id, brief.brief_id)
        mutated = req.model_copy(update={"duration_minutes": 60})
        with self.assertRaises(ConflictError):
            assembler.assemble(mutated)

    def test_generic_role_filters_other_company_jingyan_and_cold_start_policy(self):
        assembler = BriefAssembler(self.repo, records=self.records)
        strict_req = StartComprehensiveInterview(
            session_id="ci_empty_strict",
            profile_snapshot={"summary": "暂无工作经验"},
            cold_start_mode="strict",
        )
        with self.assertRaises(ValueError):
            assembler.assemble(strict_req)

        warmup_req = StartComprehensiveInterview(
            session_id="ci_empty_warmup",
            profile_snapshot={"summary": "大二计算机学生"},
            cold_start_mode="warmup_if_empty",
            external_materials=[
                ExternalReferenceInput(
                    ref_id="ref_other",
                    scope="similar_role_other_company",
                    title="友商后端面经",
                    body="问了秒杀系统设计",
                )
            ],
        )
        brief = assembler.assemble(warmup_req)
        self.assertTrue(brief.generic_role)
        self.assertFalse(brief.has_project_evidence)
        self.assertEqual(brief.resume_binding, "warmup_only")
        self.assertEqual(brief.external_references, [])
        self.assertTrue(any("通用岗位模拟已过滤别家同类面经" in w for w in brief.warnings))


if __name__ == "__main__":
    unittest.main()
