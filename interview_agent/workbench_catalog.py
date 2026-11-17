"""Dependency-free catalog shared by the local UI and bounded Agent adapters."""

# field: (type, default, maximum length/items). None means a required field.
BUSINESS_TOOLS = {
    "record_job": ("录入岗位", "jobs", "write", {"text": ("text", None, 20000)}),
    "import_job_json": ("导入岗位 JSON", "jobs", "write", {"text": ("text", None, 100000)}),
    "collect_jobs": ("采集岗位", "collect", "handoff", {"keywords": ("text", None, 300), "city": ("text", None, 100), "max_pages": ("int", 1, 10)}),
    "collection_status": ("采集状态与结果", "collect", "read", {}),
    "stop_collection": ("停止采集", "collect", "write", {"task_id": ("text", None, 100)}),
    "import_collected_jobs": ("导入采集结果", "jobs", "write", {"ids": ("ids", None, 100)}),
    "enqueue_jobs": ("加入申请队列", "queue", "write", {"ids": ("ids", None, 100)}),
    "approve_jobs": ("确认待审核岗位", "queue", "approval", {"ids": ("ids", None, 100)}),
    "prepare_greetings": ("生成发送文案", "queue", "write", {"ids": ("ids", None, 10)}),
    "review_delivery": ("复核发送", "queue", "handoff", {"ids": ("ids", None, 10)}),
    "parse_hr_mail": ("整理 HR 回复", "mail", "write", {"text": ("text", None, 20000), "received_date": ("text", "", 10)}),
    "export_calendar": ("生成面试日历", "mail", "write", {"mail_id": ("text", None, 100)}),
    "build_worksheet": ("生成面试题单", "interview", "write", {"jd": ("text", "", 20000), "minutes": ("int", 30, 180)}),
    "start_mock_interview": ("开始文字模拟面试", "interview", "write", {"job_id": ("text", "", 100), "round": ("text", "tech", 30), "duration_minutes": ("int", 20, 30)}),
    "reply_mock_interview": ("回答模拟面试", "interview", "write", {"session_id": ("text", None, 100), "text": ("text", None, 12000)}),
    "finish_mock_interview": ("结束并复盘面试", "interview", "write", {"session_id": ("text", None, 100)}),
    "start_version_interview": ("基于简历版本开始面试", "interview", "write", {"resume_version_id": ("text", None, 100)}),
    "reply_project_interview": ("继续项目核验或版本面试", "interview", "write", {"session_id": ("text", None, 100), "text": ("text", None, 12000), "command": ("text", "", 40)}),
    "export_resume_version": ("导出已保存简历", "resume", "read", {"resume_version_id": ("text", None, 100), "format": ("text", "pdf", 10), "template": ("text", "professional", 20)}),
    "review_transcript": ("逐字稿复盘", "interview", "write", {"text": ("text", None, 30000)}),
    "add_interview_question": ("加入题库", "interview", "write", {"question": ("text", None, 3000), "section": ("text", "项目深挖", 100)}),
    "prepare_github_project": ("解读 GitHub 项目", "resume", "handoff", {"repository": ("text", None, 200), "role": ("text", None, 200), "contribution": ("text", None, 4000)}),
    "knowledge_sources": ("查看项目知识库", "resume", "read", {}),
    "search_project_knowledge": ("检索项目证据", "resume", "read", {"snapshot_ids": ("ids", None, 100), "query": ("text", None, 1000)}),
    "collect_note": ("收藏单条面经", "notes", "write", {"url": ("text", None, 4096)}),
    "subscribe_note": ("订阅单条面经更新", "notes", "write", {"url": ("text", None, 4096), "interval_hours": ("int", 24, 168), "keywords": ("strings", [], 10)}),
    "note_subscriptions": ("查看面经订阅", "notes", "read", {}),
    "pause_note_subscription": ("暂停面经订阅", "notes", "write", {"subscription_id": ("text", None, 100)}),
    "resume_note_subscription": ("恢复面经订阅", "notes", "write", {"subscription_id": ("text", None, 100)}),
    "note_inbox": ("查看面经消息", "notes", "read", {"offset": ("offset", 0, 100000)}),
    "read_note": ("阅读收藏正文", "notes", "read", {"note_id": ("text", None, 100)}),
    "mark_note_read": ("标记面经消息已读", "notes", "write", {"message_id": ("text", None, 100)}),
    "note_self_check": ("检查面经服务", "notes", "read", {}),
    "push_preview": ("生成信息推送预览", "push", "read", {"job_id": ("text", None, 100)}),
    "export_workspace": ("导出工作区数据", "data", "write", {}),
    "save_experience_variant": ("保存经历变体", "resume", "write", {"project": ("text", None, 160), "text": ("text", None, 12000)}),
}

CAPABILITIES = [
    ("profile_import", "导入简历", "资料与经历", "profile", "profile-resume-drop", "file"),
    ("profile", "编辑个人资料", "资料与经历", "profile", "profile-form", "form"),
    ("experience", "整理项目与工作经历", "资料与经历", "experience", "", "form"),
    ("github", "GitHub 项目核验", "资料与经历", "resume", "cu-repository-section", "form"),
    ("knowledge", "项目知识库与证据", "资料与经历", "resume", "cu-knowledge-title", "read"),
    ("jobs", "选择或录入岗位", "寻找岗位", "jobs", "", "form"),
    ("collect", "采集平台岗位", "寻找岗位", "collect", "", "form"),
    ("job_import", "导入岗位 JSON", "寻找岗位", "jobs", "import-form", "form"),
    ("application", "准备简历与招呼语", "申请材料", "application", "", "form"),
    ("resume", "简历版本与导出", "申请材料", "resume", "cu-versions", "read"),
    ("ats", "检查 PDF 可读性", "申请材料", "resume", "ats-form", "file"),
    ("variants", "保存经历变体", "申请材料", "resume", "variant-form", "form"),
    ("queue", "审批与发送复核", "申请与回复", "queue", "", "form"),
    ("mail", "处理 HR 回复与日历", "申请与回复", "mail", "", "form"),
    ("interview", "开始模拟面试", "面试与成长", "interview", "interview-chat", "form"),
    ("worksheet", "生成面试题单", "面试与成长", "interview", "worksheet-form", "form"),
    ("debrief", "查看与生成面试复盘", "面试与成长", "interview", "debrief-form", "form"),
    ("library", "管理题库与面经", "面试与成长", "interview", "chat-library-form", "form"),
    ("notes", "面经收藏与更新订阅", "面试与成长", "notes", "", "form"),
    ("push", "信息推送预览", "其他工具", "push", "", "preview"),
    ("overview", "求职流程与统计", "其他工具", "overview", "", "read"),
    ("data", "数据导出与自检", "其他工具", "data", "", "form"),
    ("settings", "连接与必要配置", "其他工具", "settings", "", "form"),
]


def validate_arguments(name, arguments):
    if name not in BUSINESS_TOOLS or not isinstance(arguments, dict):
        raise ValueError("未知工作台能力")
    fields = BUSINESS_TOOLS[name][3]
    if set(arguments) - set(fields):
        raise ValueError("操作包含未知参数")
    result = {}
    for key, (kind, default, maximum) in fields.items():
        value = arguments.get(key, default)
        if value is None:
            raise ValueError("缺少参数：" + key)
        if kind == "text":
            if not isinstance(value, str) or len(value) > maximum or (default is None and not value.strip()):
                raise ValueError("文本参数无效：" + key)
        elif kind in {"int", "offset"}:
            if type(value) is not int or not (0 if kind == "offset" else 1) <= value <= maximum:
                raise ValueError("数字参数无效：" + key)
        elif kind in {"ids", "strings"}:
            if not isinstance(value, list) or len(value) > maximum or (kind == "ids" and not value):
                raise ValueError("列表参数无效：" + key)
            if any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in value):
                raise ValueError("列表内容无效：" + key)
        result[key] = value
    return result
