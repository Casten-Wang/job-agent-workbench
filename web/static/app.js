'use strict';

/* Local-only workbench. All dynamic text is written with textContent or DOM
   attributes; API data is never interpolated into HTML. */

const SVG_NS = 'http://www.w3.org/2000/svg';
const CHANNEL_LABELS = {
  all: '全部渠道',
  manual_paste: '手动粘贴',
  offerpilot_manual_export: '岗位自动化导出',
  boss: 'Boss直聘',
  liepin: '猎聘',
  '51job': '前程无忧',
  zhilian: '智联招聘',
  zhilian_campus: '智联校园',
  unknown: '未知渠道'
};
const INTENT_LABELS = {
  interview_invite: '面试邀请',
  assessment: '笔试/测评',
  rejection: '淘汰',
  offer: 'Offer',
  other: '其他'
};
const BOUNDARY_LABELS = {
  auto_submit: '自动提交',
  platform_scraping: '平台抓取',
  browser_takeover: '浏览器接管',
  wechat_hook: '微信 Hook',
  external_api: '外部 API',
  real_imap: '真实 IMAP',
  real_feishu_http: '真实飞书 HTTP',
  real_asr: '真实 ASR',
  offerpilot_integration: '内嵌岗位自动化'
};
const BOUNDARY_VALUES = {
  embedded_offerpilot_only: '岗位自动化（仅本机、人工确认投递）',
  not_implemented_offline_build: '未实现（离线版本）',
  dry_run_only: '只生成预览',
  embedded: '已内嵌',
  unavailable: '不可用'
};
const OFFERPILOT_MODE_LABELS = {
  collect: '仅采集',
  monitor: '仅监控',
  full: '完整流程'
};
const OFFERPILOT_TASK_STATUS_LABELS = {
  running: '运行中',
  stopping: '停止中',
  stopped: '已停止',
  completed: '已完成',
  succeeded: '成功',
  failed: '失败',
  queued: '排队中',
  pending: '等待中'
};
const OFFERPILOT_CAPABILITY_LABELS = {
  collect_without_ai: '无 AI 采集',
  evaluate_with_local_agent_without_ai: '本地评分',
  monitor_without_ai: '无 AI 监控',
  start_full_flow: '完整流程',
  human_confirmation_before_delivery: '投递前人工确认'
};
const HUB_FOR_VIEW = {
  workbench: 'workbench',
  agent: 'agent',
  collect: 'find',
  jobs: 'find',
  queue: 'find',
  mail: 'find',
  profile: 'profile',
  resume: 'resume',
  interview: 'interview',
  data: 'data',
  push: 'push'
};
const VIEW_TITLES = {
  workbench: '首页',
  agent: '对话助理',
  collect: '岗位流水线 · 采集',
  jobs: '岗位流水线 · 筛选',
  queue: '岗位流水线 · 通过',
  mail: '岗位流水线 · 回复',
  profile: '个人资料',
  resume: '定制简历',
  interview: '模拟面试',
  push: '信息推送',
  data: '设置'
};
// 与 web/backend.py 的默认模型、vendor/offerpilot 的 AI_SERVICE_PRESETS 保持一致；
// 没有预设模型的服务商留空，由用户填写。
const AI_PROVIDER_DEFAULTS = {
  anthropic: { model: 'claude-sonnet-4-6', base_url: '' },
  deepseek: { model: '', base_url: 'https://api.deepseek.com' },
  doubao: { model: '', base_url: 'https://ark.cn-beijing.volces.com/api/v3' },
  custom: { model: '', base_url: '' }
};
const OFFERPILOT_IMPORTED_TASKS_KEY = 'offerpilot.importedTasks';
const OFFERPILOT_PACE = {
  cautious: { label: '稳健', multiplier: 3.0 },
  standard: { label: '标准', multiplier: 1.5 },
  fast: { label: '快速', multiplier: 1.0 }
};
const OFFERPILOT_MODE_HINTS = {
  collect: '采集岗位并按你的简历评分，不投递、不发消息。',
  monitor: '只检查已有会话中的 HR 回复，不采集新岗位、不发送消息。',
  full: '采集后自动评分、放进待确认队列并生成招呼语，停在发送确认前；发送仍需你确认。'
};
const OFFERPILOT_JOB_STATUS_LABELS = {
  pending: '待评分',
  scored: '已评分',
  filtered: '已过滤',
  ready: '可投递',
  approved: '已确认',
  greeted: '已生成招呼语',
  sent: '已发送',
  replied: '已回复',
  resume_sent: '已发简历',
  needs_resume: '待补简历',
  follow_up_sent: '已跟进',
  error: '发送失败',
  skipped: '已跳过',
  rejected: '已拒绝',
  interview: '面试中',
  offer: 'Offer',
  deleted: '已删除'
};

function safeLocalGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function safeLocalSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (error) {
    /* Local storage can be unavailable; the workbench still works. */
  }
}

const state = {
  // 工作台只有真实数据一种模式；接口仍带 mode 参数以兼容后端契约。
  mode: 'user',
  theme: ['auto', 'light', 'dark'].includes(safeLocalGet('job-workbench-theme'))
    ? safeLocalGet('job-workbench-theme')
    : 'auto',
  jobState: 'all',
  snapshot: null,
  fetchSeq: 0,
  refreshing: false,
  queueSelection: new Set(),
  offerpilotJobsLoaded: false,
  offerpilotJobsLoading: false,
  offerpilotJobsMode: null,
  offerpilotConnected: false,
  offerpilotCanStart: false,
  offerpilotJobs: [],
  offerpilotJobsTotal: 0,
  offerpilotSelection: new Set(),
  offerpilotPreflight: null,
  offerpilotPreflightKey: '',
  offerpilotTaskActive: false,
  offerpilotAutoImporting: false,
  offerpilotPrefsMode: null,
  offerpilotPollTimer: null,
  offerpilotResume: null,
  offerpilotAutoScoreTouched: false,
  offerpilotPipeline: null,
  jobsSelection: new Set(),
  jobsEnqueueNotes: {},
  jobsDossierId: null,
  queueReviewId: null,
  queueApprovedSelection: new Set(),
  queueDeliveryIds: [],
  queueDeliveryOpen: false,
  queueDeliveryBusy: false,
  queueDeliverySubmitted: false,
  queueDeliveryBatchId: null,
  queueDeliveryReturnFocus: null,
  queueGreetingWatch: null,
  profileDirty: false,
  profileImportBusy: false,
  profileAutoPrefillTried: false,
  profilePrefillCount: 0,
  hrConversations: [],
  hrConversationsLoaded: false,
  hrConversationsLoading: false,
  hrAvailable: null,
  hrReason: '',
  hrMode: null,
  hrSelectedId: '',
  hrThread: null,
  hrThreadLoading: false,
  hrThreads: {},
  hrSearch: '',
  hrFilter: 'all',
  hrPlatform: 'all',
  hrPlatformErrors: {},
  hrDrafts: {},
  hrReplyModalOpen: false,
  hrReplyBusy: false,
  hrReplyReturnFocus: null,
  hrSeq: 0,
  // HR 会话页：本地列表即时显示，平台增量同步静默在后台跑。
  hrSummary: null,
  hrSummaryLoading: false,
  hrPlatformSummary: {},
  hrUnreadTotal: 0,
  hrLastSyncedAt: '',
  hrSyncSupported: null,
  hrSyncing: false,
  hrSyncBaseline: '',
  hrNoticeTimer: 0,
  hrSyncTriggeredAt: 0,
  hrPollTimer: null,
  hrPollBusy: false,
  hrMobilePane: 'list',
  hrThreadRenderedKey: '',
  hrThreadRenderedMessages: null,
  hrConversationListSignature: '',
  hrConversationListCount: -1,
  interviewChat: {
    session: null,
    internal: null,
    materials: [],
    interruptNext: false,
    streamAbort: null,
    timerId: null,
    materialSeq: 1,
    libraryEditingId: null,
    card: null,
    debriefHistory: [],
    drill: null,
    profileBackup: null,
    webSearch: {
      configured: false,
      results: []
    }
  },
  interviewModule: null
};

const dom = {
  html: document.documentElement,
  views: document.getElementById('views'),
  status: document.getElementById('status'),
  generatedAt: document.getElementById('generated-at'),
  loadingNote: document.getElementById('loading-note'),
  refreshButton: document.getElementById('refresh-button'),
  topbarTitle: document.getElementById('topbar-title'),
  homeDate: document.getElementById('home-date'),
  homeLede: document.getElementById('home-lede'),
  homeJobsCount: document.getElementById('home-jobs-count'),
  homeGreetingsCount: document.getElementById('home-greetings-count'),
  homeRepliesCount: document.getElementById('home-replies-count'),
  homeRepliesSub: document.getElementById('home-replies-sub'),
  homeSendSummary: document.getElementById('home-send-summary'),
  sgHomeDay: document.getElementById('sg-home-day'),
  sgHomeLiveText: document.getElementById('sg-home-live-text'),
  sgPipeTotal: document.getElementById('sg-pipe-total'),
  sgPipeList: document.getElementById('sg-pipe-list'),
  sgActivityCount: document.getElementById('sg-activity-count'),
  sgHomeActivity: document.getElementById('sg-home-activity'),
  belt: document.getElementById('belt'),
  beltFocus: document.getElementById('belt-focus'),
  pipeline: document.getElementById('pipeline'),
  pipelineEvents: document.getElementById('pipeline-events'),
  kpiRow: document.getElementById('kpi-row'),
  channelChart: document.getElementById('channel-chart'),
  channelTable: document.getElementById('channel-table'),
  quarterChart: document.getElementById('quarter-chart'),
  quarterTable: document.getElementById('quarter-table'),
  weaknessChart: document.getElementById('weakness-chart'),
  weaknessTable: document.getElementById('weakness-table'),
  mailChart: document.getElementById('mail-chart'),
  mailTable: document.getElementById('mail-table'),
  activityData: document.getElementById('activity-data'),
  jdForm: document.getElementById('jd-form'),
  jdText: document.getElementById('jd-text'),
  jdChannel: document.getElementById('jd-channel'),
  jdSubmit: document.getElementById('jd-submit'),
  jdResult: document.getElementById('jd-result'),
  importForm: document.getElementById('import-form'),
  importJson: document.getElementById('import-json'),
  importResult: document.getElementById('import-result'),
  jobsCount: document.getElementById('jobs-count'),
  jobsEmptyHint: document.getElementById('jobs-empty-hint'),
  jobsFilterEmptyHint: document.getElementById('jobs-filter-empty-hint'),
  jobsTable: document.getElementById('jobs-table'),
  jobsDossier: document.getElementById('jobs-dossier'),
  jobsDossierBody: document.getElementById('jobs-dossier-body'),
  jobsDossierClose: document.getElementById('jobs-dossier-close'),
  queueReview: document.getElementById('queue-review'),
  queueReviewBody: document.getElementById('queue-review-body'),
  queueReviewClose: document.getElementById('queue-review-close'),
  jobsActionResult: document.getElementById('jobs-action-result'),
  jobsSelectAll: document.getElementById('jobs-select-all'),
  jobsSelectionCount: document.getElementById('jobs-selection-count'),
  jobsBulkEnqueue: document.getElementById('jobs-bulk-enqueue'),
  jobsBulkDelete: document.getElementById('jobs-bulk-delete'),
  offerpilotConnection: document.getElementById('offerpilot-connection'),
  offerpilotState: document.getElementById('offerpilot-state'),
  offerpilotError: document.getElementById('offerpilot-error'),
  offerpilotTask: document.getElementById('offerpilot-task'),
  offerpilotRefresh: document.getElementById('offerpilot-refresh'),
  offerpilotForm: document.getElementById('offerpilot-form'),
  offerpilotMode: document.getElementById('offerpilot-mode'),
  offerpilotRisk: document.getElementById('offerpilot-risk'),
  offerpilotConfirm: document.getElementById('offerpilot-confirm'),
  offerpilotStart: document.getElementById('offerpilot-start'),
  offerpilotResult: document.getElementById('offerpilot-result'),
  offerpilotJobsCount: document.getElementById('offerpilot-jobs-count'),
  offerpilotJobsTable: document.getElementById('offerpilot-jobs-table'),
  offerpilotSelectAll: document.getElementById('offerpilot-select-all'),
  offerpilotImport: document.getElementById('offerpilot-import'),
  offerpilotOpenJobs: document.getElementById('offerpilot-open-jobs'),
  collectKeywords: document.getElementById('collect-keywords'),
  collectCities: document.getElementById('collect-cities'),
  collectPages: document.getElementById('collect-pages'),
  collectPace: document.getElementById('collect-pace'),
  collectPlatform: document.getElementById('collect-platform'),
  collectPlatformHint: document.getElementById('collect-platform-hint'),
  collectAutoScore: document.getElementById('collect-auto-score'),
  collectResumeFile: document.getElementById('collect-resume-file'),
  collectResumeUpload: document.getElementById('collect-resume-upload'),
  collectResumeStatus: document.getElementById('collect-resume-status'),
  collectSummary: document.getElementById('collect-summary'),
  collectChecks: document.getElementById('collect-checks'),
  collectCriteria: document.getElementById('collect-criteria'),
  collectCriteriaHint: document.getElementById('collect-criteria-hint'),
  collectPreflight: document.getElementById('collect-preflight'),
  profileForm: document.getElementById('profile-form'),
  profileName: document.getElementById('profile-name'),
  profileCity: document.getElementById('profile-city'),
  profileEmail: document.getElementById('profile-email'),
  profilePhone: document.getElementById('profile-phone'),
  profileWechat: document.getElementById('profile-wechat'),
  profileLinks: document.getElementById('profile-links'),
  profileTitles: document.getElementById('profile-titles'),
  profileTargetCities: document.getElementById('profile-target-cities'),
  profileSalaryMin: document.getElementById('profile-salary-min'),
  profileSalaryMax: document.getElementById('profile-salary-max'),
  profileJobType: document.getElementById('profile-job-type'),
  profileAvailability: document.getElementById('profile-availability'),
  profileTools: document.getElementById('profile-tools'),
  profileStrengths: document.getElementById('profile-strengths'),
  profileSummary: document.getElementById('profile-summary'),
  profileExcluded: document.getElementById('profile-excluded'),
  profileTruth: document.getElementById('profile-truth'),
  profileEducation: document.getElementById('profile-education'),
  profileExperiences: document.getElementById('profile-experiences'),
  profileProjects: document.getElementById('profile-projects'),
  profileMeter: document.getElementById('profile-meter'),
  profileBadge: document.getElementById('profile-completeness-badge'),
  profileImport: document.getElementById('profile-import'),
  profileImportFile: document.getElementById('profile-import-file'),
  profileImportPreview: document.getElementById('profile-import-preview'),
  profileImportText: document.getElementById('profile-import-text'),
  profileDrop: document.getElementById('profile-resume-drop'),
  profileSave: document.getElementById('profile-save'),
  profileResult: document.getElementById('profile-result'),
  profileDraftBanner: document.getElementById('profile-draft-banner'),
  atsForm: document.getElementById('ats-form'),
  atsFile: document.getElementById('ats-file'),
  atsKeywords: document.getElementById('ats-keywords'),
  atsSubmit: document.getElementById('ats-submit'),
  atsResult: document.getElementById('ats-result'),
  queuePendingCount: document.getElementById('queue-pending-count'),
  queueSelectAll: document.getElementById('queue-select-all'),
  queueSelectionCount: document.getElementById('queue-selection-count'),
  queuePendingTable: document.getElementById('queue-pending-table'),
  queueConfirmButton: document.getElementById('queue-confirm-button'),
  queueApprovedCount: document.getElementById('queue-approved-count'),
  queueApprovedTable: document.getElementById('queue-approved-table'),
  queueApprovedSelectAll: document.getElementById('queue-approved-select-all'),
  queueApprovedSelectionCount: document.getElementById('queue-approved-selection-count'),
  queueGenerateGreetings: document.getElementById('queue-generate-greetings'),
  queueSendGreetings: document.getElementById('queue-send-greetings'),
  queueGreetings: document.getElementById('queue-greetings'),
  queuePipelineStatus: document.getElementById('queue-pipeline-status'),
  queueDeliveryPanel: document.getElementById('queue-delivery-panel'),
  queueDeliverySummary: document.getElementById('queue-delivery-summary'),
  queueDeliveryPlatform: document.getElementById('sg-queue-delivery-platform'),
  queueDeliveryList: document.getElementById('queue-delivery-list'),
  queueDeliveryRisk: document.getElementById('queue-delivery-risk'),
  queueDeliveryProgress: document.getElementById('queue-delivery-progress'),
  jobsOverrideReason: document.getElementById('jobs-override-reason'),
  queueDeliveryStart: document.getElementById('queue-delivery-start'),
  queueDeliveryCancel: document.getElementById('queue-delivery-cancel'),
  queueDeliveryResults: document.getElementById('queue-delivery-results'),
  mailForm: document.getElementById('mail-form'),
  mailSubject: document.getElementById('mail-subject'),
  mailBody: document.getElementById('mail-body'),
  mailFrom: document.getElementById('mail-from'),
  mailDate: document.getElementById('mail-date'),
  mailMessageId: document.getElementById('mail-message-id'),
  mailSubmit: document.getElementById('mail-submit'),
  mailResult: document.getElementById('mail-result'),
  mailList: document.getElementById('mail-list'),
  mailActionResult: document.getElementById('mail-action-result'),
  hrRefresh: document.getElementById('hr-refresh'),
  hrSyncStatus: document.getElementById('hr-sync-status'),
  hrSyncText: document.getElementById('hr-sync-text'),
  hrStatus: document.getElementById('hr-status'),
  hrLayout: document.getElementById('hr-layout'),
  hrThreadView: document.getElementById('hr-thread'),
  hrMobileBack: document.getElementById('hr-mobile-back'),
  hrPlatformStatus: document.getElementById('hr-platform-status'),
  hrNavUnread: document.getElementById('hr-nav-unread'),
  hrSearch: document.getElementById('hr-search'),
  hrFilterButtons: Array.from(document.querySelectorAll('[data-hr-filter]')),
  hrPlatformSelect: document.getElementById('hr-platform'),
  hrPlatformErrors: document.getElementById('hr-platform-errors'),
  hrConversationCount: document.getElementById('hr-conversation-count'),
  hrConversationList: document.getElementById('hr-conversation-list'),
  hrDetailTitle: document.getElementById('hr-detail-title'),
  hrDetailMeta: document.getElementById('hr-detail-meta'),
  hrDetailJob: document.getElementById('hr-detail-job'),
  hrMessages: document.getElementById('hr-messages'),
  hrReplyBlockReason: document.getElementById('hr-reply-block-reason'),
  hrReplyForm: document.getElementById('hr-reply-form'),
  hrReplyInput: document.getElementById('hr-reply-input'),
  hrReplySend: document.getElementById('hr-reply-send'),
  hrDraftCount: document.getElementById('hr-draft-count'),
  hrReplyConfirmPanel: document.getElementById('hr-reply-confirm-panel'),
  hrReplyDialog: document.getElementById('hr-reply-dialog'),
  hrReplyWho: document.getElementById('hr-reply-who'),
  hrReplyPlatform: document.getElementById('sg-hr-reply-platform'),
  hrReplyModalText: document.getElementById('hr-reply-modal-text'),
  hrReplyModalProgress: document.getElementById('hr-reply-modal-progress'),
  hrReplyModalRisk: document.getElementById('hr-reply-modal-risk'),
  hrReplyModalCancel: document.getElementById('hr-reply-modal-cancel'),
  hrReplyConfirm: document.getElementById('hr-reply-confirm'),
  worksheetForm: document.getElementById('worksheet-form'),
  worksheetMinutes: document.getElementById('worksheet-minutes'),
  worksheetJd: document.getElementById('worksheet-jd'),
  worksheetSubmit: document.getElementById('worksheet-submit'),
  worksheetResult: document.getElementById('worksheet-result'),
  debriefForm: document.getElementById('debrief-form'),
  debriefTranscript: document.getElementById('debrief-transcript'),
  debriefSubmit: document.getElementById('debrief-submit'),
  debriefResult: document.getElementById('debrief-result'),
  debriefList: document.getElementById('debrief-list'),
  bankForm: document.getElementById('bank-form'),
  bankQuestion: document.getElementById('bank-question'),
  bankSection: document.getElementById('bank-section'),
  bankSubmit: document.getElementById('bank-submit'),
  bankResult: document.getElementById('bank-result'),
  bankList: document.getElementById('bank-list'),
  interviewHub: document.getElementById('interview-hub'),
  chatPanel: document.getElementById('interview-chat'),
  chatProgress: document.getElementById('chat-progress'),
  chatJob: document.getElementById('chat-job'),
  chatJd: document.getElementById('chat-jd'),
  chatLibrary: document.getElementById('chat-library'),
  chatLibraryError: document.getElementById('chat-library-error'),
  chatLibraryForm: document.getElementById('chat-library-form'),
  chatLibraryKind: document.getElementById('chat-library-kind'),
  chatLibraryTitle: document.getElementById('chat-library-title'),
  chatLibraryCompany: document.getElementById('chat-library-company'),
  chatLibraryRole: document.getElementById('chat-library-role'),
  chatLibraryBody: document.getElementById('chat-library-body'),
  chatLibrarySave: document.getElementById('chat-library-save'),
  chatLibraryCancel: document.getElementById('chat-library-cancel'),
  chatJingyanList: document.getElementById('chat-jingyan-list'),
  chatKnowledgeList: document.getElementById('chat-knowledge-list'),
  chatGenericNote: document.getElementById('chat-generic-note'),
  chatRoleLine: document.getElementById('chat-role-line'),
  chatWebNotice: document.getElementById('chat-web-notice'),
  chatError: document.getElementById('chat-error'),
  chatRules: document.getElementById('chat-rules'),
  chatLog: document.getElementById('chat-log'),
  chatAnswer: document.getElementById('chat-answer'),
  chatPrimary: document.getElementById('chat-primary'),
  chatRestart: document.getElementById('chat-restart'),
  chatDebrief: document.getElementById('chat-debrief'),
  chatDebriefHistory: document.getElementById('chat-debrief-history'),
  chatDebriefHistoryList: document.getElementById('chat-debrief-history-list'),
  chatMockInterrupt: document.getElementById('chat-mock-interrupt'),
  chatMockTimeup: document.getElementById('chat-mock-timeup'),
  variantForm: document.getElementById('variant-form'),
  variantProject: document.getElementById('variant-project'),
  variantText: document.getElementById('variant-text'),
  variantSubmit: document.getElementById('variant-submit'),
  variantResult: document.getElementById('variant-result'),
  variantList: document.getElementById('variant-list'),
  variantCompareResult: document.getElementById('resume-compare-result'),
  runTestsButton: document.getElementById('run-tests-button'),
  webReportButton: document.getElementById('web-report-button'),
  exportButton: document.getElementById('export-button'),
  opsResult: document.getElementById('ops-result'),
  aiSettingsForm: document.getElementById('ai-settings-form'),
  aiSettingsService: document.getElementById('ai-settings-service'),
  aiSettingsModel: document.getElementById('ai-settings-model'),
  aiSettingsBaseUrl: document.getElementById('ai-settings-base-url'),
  aiSettingsKey: document.getElementById('ai-settings-key'),
  aiSettingsSave: document.getElementById('ai-settings-save'),
  aiSettingsTest: document.getElementById('ai-settings-test'),
  aiSettingsBadge: document.getElementById('ai-settings-badge'),
  aiSettingsResult: document.getElementById('ai-settings-result'),
  dryRunForm: document.getElementById('dry-run-form'),
  dryJobId: document.getElementById('dry-job-id'),
  dryCompany: document.getElementById('dry-company'),
  dryTitle: document.getElementById('dry-title'),
  dryStatus: document.getElementById('dry-status'),
  dryChannel: document.getElementById('dry-channel'),
  dryRunButton: document.getElementById('dry-run-button'),
  dryRunResult: document.getElementById('dry-run-result'),
  downloadsTable: document.getElementById('downloads-table'),
  boundariesTable: document.getElementById('boundaries-table'),
  configSummary: document.getElementById('config-summary'),
  navItems: Array.from(document.querySelectorAll('.nav-item')),
  themeButtons: Array.from(document.querySelectorAll('[data-theme-choice]')),
  viewPanels: Array.from(document.querySelectorAll('[data-view-panel]'))
};

/* DOM helpers */

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined && options.text !== null) node.textContent = String(options.text);
  if (options.attrs) {
    Object.keys(options.attrs).forEach((key) => {
      const value = options.attrs[key];
      if (value === undefined || value === null || value === false) return;
      node.setAttribute(key, String(value));
    });
  }
  if (options.props) {
    Object.keys(options.props).forEach((key) => {
      node[key] = options.props[key];
    });
  }
  appendChildren(node, children);
  return node;
}

function svgEl(tag, attrs = {}, children = []) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.keys(attrs).forEach((key) => {
    const value = attrs[key];
    if (value === undefined || value === null || value === false) return;
    node.setAttribute(key, String(value));
  });
  appendChildren(node, children);
  return node;
}

function appendChildren(node, children) {
  if (children === undefined || children === null) return;
  const list = Array.isArray(children) ? children : [children];
  list.forEach((child) => {
    if (child === undefined || child === null || child === false) return;
    if (Array.isArray(child)) {
      appendChildren(node, child);
    } else if (child instanceof Node) {
      node.append(child);
    } else {
      node.append(document.createTextNode(String(child)));
    }
  });
}

function clear(node) {
  if (node) node.replaceChildren();
}

/* Formatting and labels */

function toInt(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.trunc(number) : 0;
}

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function formatScore(value) {
  if (value === null || value === undefined || value === '') return '未评分';
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(1) : '未评分';
}

// 采集结果与审批队列共用：带分母显示，避免 4.0 与 49/100 混读。
// 文档评分（>5）按 100 分制取整；旧的 5 分制保留 /5，不擅自换算。
function formatJobScoreValue(value) {
  if (value === null || value === undefined || value === '') return '待评分';
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return '待评分';
  return number > 5 ? `${Math.round(number)}/100` : `${number}/5`;
}

// 招呼语来源：接口里的枚举值按中文显示，未知值原样保留。
function greetingSourceLabel(value) {
  const key = String(value || '');
  if (key === 'generated') return '自动生成';
  if (key === 'manual') return '手动';
  return key;
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  const percent = Math.round(number * 1000) / 10;
  return `${Number.isInteger(percent) ? percent.toFixed(0) : percent.toFixed(1)}%`;
}

function formatDateTime(value) {
  if (!value) return '—';
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  try {
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });
  } catch (error) {
    return text;
  }
}

function formatBytes(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return '—';
  if (number < 1024) return `${number} B`;
  if (number < 1024 * 1024) return `${(number / 1024).toFixed(1)} KB`;
  return `${(number / 1024 / 1024).toFixed(1)} MB`;
}

function truncate(value, maxLength) {
  const text = String(value === undefined || value === null ? '' : value);
  return text.length > maxLength ? `${text.slice(0, maxLength)}…` : text;
}

function channelLabel(value) {
  if (value === undefined || value === null || value === '') return CHANNEL_LABELS.unknown;
  const key = String(value);
  return CHANNEL_LABELS[key] || key;
}

function intentLabel(value) {
  const key = String(value || 'other');
  return INTENT_LABELS[key] || key;
}

function boundaryLabel(key) {
  return BOUNDARY_LABELS[key] || String(key);
}

function boundaryValue(value) {
  if (value === false) return '否';
  if (value === true) return '是';
  const key = String(value);
  return BOUNDARY_VALUES[key] || key;
}

function verdictLabel(value) {
  if (value === 'pass') return 'pass（自动检查通过）';
  if (value === 'fail') return 'fail（未通过）';
  if (value === 'needs_manual_check') return 'needs_manual_check（需人工检查）';
  return String(value || 'unknown');
}

function textLayerLabel(value) {
  if (value === 'available') return 'available（可提取）';
  if (value === 'unavailable') return 'unavailable（不可用）';
  return String(value || 'unknown');
}

function keywordMatchLabel(value) {
  if (value === true) return '命中';
  if (value === false) return '未命中';
  if (value === null) return '未检查（无文字层）';
  return '未检查';
}

function todayIso() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

/* Status, loading and API */

let statusToastTimer = null;

function setStatus(message, kind = 'ok') {
  const safeKind = ['ok', 'warn', 'error', 'info'].includes(kind) ? kind : 'info';
  const text = String(message || '');
  if (statusToastTimer) {
    window.clearTimeout(statusToastTimer);
    statusToastTimer = null;
  }
  dom.status.textContent = text;
  dom.status.className = `status status-${safeKind}`;
  if (!text) return;
  // 错误常驻，直到下一次操作覆盖；其余三类 3 秒后自动消失。
  if (safeKind === 'error') return;
  statusToastTimer = window.setTimeout(() => {
    dom.status.textContent = '';
    dom.status.className = 'status status-info';
    statusToastTimer = null;
  }, 3000);
}

// 切页时清掉上一页的提示：成功/信息类不再残留，错误也不再带进新页面。
function clearStatus() {
  if (statusToastTimer) {
    window.clearTimeout(statusToastTimer);
    statusToastTimer = null;
  }
  dom.status.textContent = '';
  dom.status.className = 'status status-info';
}

function setRefreshing(active) {
  state.refreshing = Boolean(active);
  dom.views.classList.toggle('is-loading', Boolean(active));
  dom.views.setAttribute('aria-busy', active ? 'true' : 'false');
  dom.loadingNote.hidden = !active;
  dom.refreshButton.disabled = Boolean(active);
}

function friendlyError(error) {
  if (error instanceof TypeError) {
    return '连不上本地服务；请确认工作台服务还在运行，然后点「刷新数据」重试。';
  }
  if (error && error.message) return error.message;
  return '未知错误。';
}

async function parseResponse(response) {
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error(`服务返回的内容无法解析（HTTP ${response.status}）。请刷新后重试。`);
  }
  if (!response.ok) {
    const message = data && data.error ? data.error : `请求没有成功（HTTP ${response.status}）。请稍后重试。`;
    throw new Error(message);
  }
  return data;
}

async function loadState(options = {}) {
  const announce = Boolean(options.announce);
  const seq = ++state.fetchSeq;
  setRefreshing(true);
  try {
    const params = new URLSearchParams({
      mode: state.mode,
      state: state.jobState
    });
    const response = await fetch(`/api/state?${params.toString()}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });
    const data = await parseResponse(response);
    if (seq !== state.fetchSeq) return;
    state.snapshot = data;
    renderAll(data);
    if (announce) {
      setStatus(`已载入本地数据；更新于 ${formatDateTime(data.generated_at)}。`, 'ok');
    }
  } catch (error) {
    if (seq !== state.fetchSeq) return;
    setStatus(`数据没有载入：${friendlyError(error)}`, 'error');
  } finally {
    if (seq === state.fetchSeq) setRefreshing(false);
  }
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json'
    },
    body: JSON.stringify(payload)
  });
  return parseResponse(response);
}

function postAction(action, payload = {}) {
  return postJson('/api/action', { action, mode: state.mode, ...payload });
}

async function runAction(button, operation) {
  if (button) {
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
  }
  try {
    return await operation();
  } catch (error) {
    setStatus(`没有完成：${friendlyError(error)}`, 'error');
    return null;
  } finally {
    if (button) {
      button.removeAttribute('aria-busy');
      button.disabled = false;
    }
  }
}

function announceActionResult(data, fallback = '操作完成。') {
  if (!data) return false;
  if (data.ok === false) {
    setStatus(data.message || '操作未完成。', data.duplicate ? 'warn' : 'error');
    return false;
  }
  setStatus(data.message || fallback, 'ok');
  return true;
}

function downloadUrl(name) {
  return `/api/download/${encodeURIComponent(state.mode)}/${encodeURIComponent(name)}`;
}

function downloadLink(name, label) {
  const link = el('a', {
    className: 'download-link',
    text: label || name,
    attrs: { href: downloadUrl(name) }
  });
  link.setAttribute('download', '');
  return link;
}

function showInline(container, message, kind = 'ok', downloadNames = []) {
  if (!container) return;
  clear(container);
  container.hidden = false;
  container.className = `action-result action-result-${kind}`;
  container.append(el('p', { text: message }));
  if (downloadNames.length) {
    const row = el('p', { className: 'download-row' });
    row.append(el('span', { text: '下载：' }));
    downloadNames.forEach((name) => row.append(downloadLink(name)));
    container.append(row);
  }
}

function showTextResult(container, options) {
  if (!container) return;
  clear(container);
  container.hidden = false;
  container.className = `action-result action-result-${options.kind || 'ok'}`;
  container.append(el('p', { className: 'result-title', text: options.message || '操作完成。' }));
  if (options.meta) container.append(el('p', { className: 'card-meta', text: options.meta }));
  if (options.downloadNames && options.downloadNames.length) {
    const row = el('p', { className: 'download-row' });
    row.append(el('span', { text: '下载：' }));
    options.downloadNames.forEach((name) => row.append(downloadLink(name)));
    container.append(row);
  }
  if (options.text) {
    container.append(el('pre', { className: 'code-block', text: options.text }));
  }
}

function resetContainer(container) {
  if (!container) return;
  clear(container);
  container.hidden = true;
  container.className = 'action-result';
}

function appendVariantQualityHints(container, quality) {
  if (!container || !quality) return;
  const hints = Array.isArray(quality.hints) ? quality.hints : [];
  if (hints.length) {
    const list = el('ul', { className: 'variant-quality-hints' });
    hints.forEach((hint) => list.append(el('li', { text: hint })));
    container.append(list);
  } else {
    container.append(el('p', { className: 'variant-quality-ok', text: '结构（背景-问题-动作-结果）与量化结果均已覆盖，未发现缺失项。' }));
  }
}

/* Theme, mode, navigation */

function applyTheme(choice) {
  const safeChoice = ['auto', 'light', 'dark'].includes(choice) ? choice : 'auto';
  state.theme = safeChoice;
  safeLocalSet('job-workbench-theme', safeChoice);
  if (safeChoice === 'auto') {
    dom.html.removeAttribute('data-theme');
  } else {
    dom.html.setAttribute('data-theme', safeChoice);
  }
  dom.themeButtons.forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === safeChoice));
  });
}

function showView(name) {
  clearStatus();
  const hub = HUB_FOR_VIEW[name] || name;
  if (dom.topbarTitle) dom.topbarTitle.textContent = VIEW_TITLES[name] || '首页';
  dom.navItems.forEach((button) => {
    const active = button.dataset.hub === hub;
    button.classList.toggle('is-active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  document.querySelectorAll('.ui-hub-tab').forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle('is-active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  dom.viewPanels.forEach((panel) => {
    panel.hidden = panel.dataset.viewPanel !== name;
  });
  window.scrollTo({ top: 0, behavior: 'auto' });
  if (name === 'interview') showInterviewModule(null);
  if (name === 'collect') {
    if (state.offerpilotConnected && !state.offerpilotJobsLoaded) loadOfferPilotJobs();
    if (state.offerpilotConnected) maybeRunOfferPilotPreflight();
  }
  if (name === 'profile') {
    state.profileAutoPrefillTried = false;
    maybeAutoPrefillProfile();
  }
  if (name === 'mail') {
    ensureHrConversationsLoaded();
    hrEnterPage();
  }
  // 会话区自身也是一个滚动容器，切页时一并回到顶部，并把焦点交给新页标题。
  if (dom.views) dom.views.scrollTop = 0;
  const panel = dom.viewPanels.find((item) => item.dataset.viewPanel === name);
  const heading = panel ? panel.querySelector('h2') : null;
  if (heading) {
    if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
    heading.focus({ preventScroll: true });
  }
}

const INTERVIEW_MODULES = ['chat', 'worksheet', 'debrief', 'library'];

function interviewHubCards() {
  const snapshot = state.snapshot || {};
  const bank = snapshot.question_bank && Array.isArray(snapshot.question_bank.questions)
    ? snapshot.question_bank.questions
    : [];
  const debriefs = Array.isArray(snapshot.debriefs) ? snapshot.debriefs : [];
  const history = Array.isArray(state.interviewChat.debriefHistory) ? state.interviewChat.debriefHistory : [];
  const session = state.interviewChat.session;
  const active = Boolean(session && session.user_status && session.user_status !== 'idle');
  const remaining = remainingMinutesFromSession(session);
  return [
    {
      id: 'chat',
      title: '模拟面试',
      owner: '本场对话',
      description: '选择轮次、时长、岗位或 JD 后开始文字模拟。',
      count: active ? remaining : 0,
      unit: '分钟',
      status: active ? 'connected' : 'ready'
    },
    {
      id: 'worksheet',
      title: 'Mock 题单',
      owner: '本地题库',
      description: '只从本机题库取题，题目不进入模拟面试对话。',
      count: bank.length,
      unit: '题',
      status: 'ready'
    },
    {
      id: 'debrief',
      title: '面试复盘',
      owner: '本机复盘',
      description: '准备度复盘和逐字稿复盘都在这里，不堆在模拟面试对话下面。',
      count: debriefs.length + history.length + (state.interviewChat.card ? 1 : 0),
      unit: '份',
      status: (state.interviewChat.card || history.length) ? 'connected' : 'ready'
    },
    {
      id: 'library',
      title: '题库与面经',
      owner: '本机知识库',
      description: '新增、修改或删除面经和岗位知识，开始面试时不必勾选。',
      count: Array.isArray(state.interviewChat.materials) ? state.interviewChat.materials.length : 0,
      unit: '条',
      status: 'ready'
    }
  ];
}

function renderInterviewHub() {
  if (!dom.interviewHub) return;
  clear(dom.interviewHub);
  interviewHubCards().forEach((card, index) => {
    const statusLabel = PIPELINE_STATUS_LABELS[card.status] || '本地可用';
    const node = el('button', {
      className: `pipeline-node owner-local status-${card.status}`,
      attrs: {
        type: 'button',
        'data-interview-module': card.id,
        'aria-label': `${card.title}，${card.count} ${card.unit}，${statusLabel}；进入${card.title}`
      }
    }, [
      el('span', { className: 'pipeline-top' }, [
        el('span', { className: 'pipeline-index', text: String(index + 1).padStart(2, '0') }),
        el('span', { className: 'pipeline-owner', text: card.owner })
      ]),
      el('span', { className: 'pipeline-name', text: card.title }),
      el('span', { className: 'sg-card-count' }, [
        el('strong', { text: String(card.count) }),
        el('span', { text: card.unit })
      ]),
      el('span', { className: 'pipeline-desc', text: card.description }),
      el('span', { className: 'sg-card-foot' }, [
        el('span', { className: 'pipeline-status', text: statusLabel }),
        el('span', { className: 'sg-card-enter', text: '进入' })
      ])
    ]);
    node.addEventListener('click', () => showInterviewModule(card.id));
    dom.interviewHub.append(node);
  });
}

function showInterviewModule(module) {
  const next = INTERVIEW_MODULES.includes(module) ? module : null;
  state.interviewModule = next;
  if (dom.interviewHub) dom.interviewHub.hidden = Boolean(next);
  INTERVIEW_MODULES.forEach((name) => {
    const node = document.getElementById(`interview-module-${name}`);
    if (node) node.hidden = next !== name;
  });
  if (!next) renderInterviewHub();
}

function clearTransientResults() {
  [
    dom.jdResult,
    dom.importResult,
    dom.jobsActionResult,
    dom.atsResult,
    dom.mailResult,
    dom.mailActionResult,
    dom.worksheetResult,
    dom.debriefResult,
    dom.bankResult,
    dom.variantResult,
    dom.variantCompareResult,
    dom.profileResult,
    dom.opsResult
  ].forEach(resetContainer);
  dom.dryRunResult.hidden = true;
  dom.dryRunResult.textContent = '';
  dom.atsFile.value = '';
  state.queueSelection.clear();
}

/* Generic table and chart rendering */

function renderTable(container, options) {
  if (!container) return;
  const previousWrap = container.querySelector('.table-wrap');
  const previousScroll = previousWrap ? previousWrap.scrollLeft : 0;
  clear(container);
  const wrap = el('div', { className: 'table-wrap' });
  const table = el('table', {
    className: `data-table${options.className ? ` ${options.className}` : ''}`
  });
  if (options.caption) table.append(el('caption', { text: options.caption }));
  const thead = el('thead');
  const headRow = el('tr');
  options.columns.forEach((column) => {
    headRow.append(el('th', { text: column, attrs: { scope: 'col' } }));
  });
  thead.append(headRow);
  table.append(thead);
  const tbody = el('tbody');
  if (!options.rows || !options.rows.length) {
    const row = el('tr');
    const cell = el('td', { className: 'empty-cell' });
    cell.setAttribute('colspan', String(options.columns.length));
    // 空状态需要带下一步按钮时传 emptyNode；纯文本仍走 emptyText。
    if (options.emptyNode) cell.append(options.emptyNode);
    else cell.textContent = options.emptyText || '暂无数据。';
    row.append(cell);
    tbody.append(row);
  } else {
    options.rows.forEach((cells) => {
      const row = el('tr');
      cells.forEach((cellValue) => {
        const cell = el('td');
        if (cellValue instanceof Node) {
          cell.append(cellValue);
        } else if (cellValue === undefined || cellValue === null || cellValue === '') {
          cell.textContent = '—';
        } else {
          cell.textContent = String(cellValue);
        }
        if (typeof cellValue === 'number') cell.classList.add('num');
        row.append(cell);
      });
      tbody.append(row);
    });
  }
  table.append(tbody);
  wrap.append(table);
  container.append(wrap);
  wrap.scrollLeft = previousScroll;
}

function niceStep(value) {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const exponent = Math.floor(Math.log10(value));
  const fraction = value / Math.pow(10, exponent);
  let nice = 10;
  if (fraction <= 1) nice = 1;
  else if (fraction <= 2) nice = 2;
  else if (fraction <= 5) nice = 5;
  return Math.max(1, Math.ceil(nice * Math.pow(10, exponent)));
}

function attachChartTip(target, tooltip, text) {
  const show = () => {
    tooltip.textContent = text;
    tooltip.hidden = false;
  };
  const hide = () => {
    tooltip.hidden = true;
  };
  target.addEventListener('mouseenter', show);
  target.addEventListener('mouseleave', hide);
  target.addEventListener('focus', show);
  target.addEventListener('blur', hide);
}

function renderGroupedBar(container, options) {
  clear(container);
  if (!options.categories.length) {
    container.append(el('p', { className: 'chart-empty', text: options.emptyText }));
    return;
  }
  const inner = el('div', { className: 'chart-inner' });
  const legend = el('div', { className: 'legend' });
  options.series.forEach((series) => {
    legend.append(el('span', { className: 'legend-item' }, [
      el('span', {
        className: `swatch ${series.cls}`,
        attrs: { 'aria-hidden': 'true' }
      }),
      el('span', { text: series.label })
    ]));
  });
  inner.append(legend);

  const tooltip = el('p', {
    className: 'chart-tooltip',
    attrs: { role: 'tooltip' }
  });
  tooltip.hidden = true;

  const width = Math.max(640, options.categories.length * 118 + 100);
  const height = 300;
  const margin = { top: 26, right: 18, bottom: 64, left: 50 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = [];
  options.series.forEach((series) => {
    series.values.forEach((value) => values.push(toInt(value)));
  });
  const maxValue = Math.max(1, ...values);
  const step = niceStep(maxValue / 4);
  const scaleMax = Math.max(step, Math.ceil(maxValue / step) * step);

  const chart = svgEl('svg', {
    viewBox: `0 0 ${width} ${height}`,
    width,
    height,
    role: 'img',
    'aria-label': options.ariaLabel,
    class: 'chart-svg',
    xmlns: SVG_NS
  });

  for (let tick = 0; tick <= scaleMax; tick += step) {
    const y = margin.top + plotHeight - (tick / scaleMax) * plotHeight;
    chart.append(svgEl('line', {
      x1: margin.left,
      y1: y,
      x2: width - margin.right,
      y2: y,
      class: 'chart-grid-line'
    }));
    const label = svgEl('text', {
      x: margin.left - 8,
      y: y + 3,
      class: 'chart-axis-text',
      'text-anchor': 'end'
    });
    label.textContent = String(tick);
    chart.append(label);
  }

  const groupWidth = plotWidth / options.categories.length;
  const barGap = 4;
  const barWidth = Math.max(
    5,
    Math.min(30, (groupWidth * 0.68 - barGap * (options.series.length - 1)) / options.series.length)
  );
  const barsWidth = barWidth * options.series.length + barGap * (options.series.length - 1);

  options.categories.forEach((category, categoryIndex) => {
    const center = margin.left + groupWidth * categoryIndex + groupWidth / 2;
    options.series.forEach((series, seriesIndex) => {
      const value = toInt(series.values[categoryIndex]);
      const barHeight = scaleMax ? (value / scaleMax) * plotHeight : 0;
      const x = center - barsWidth / 2 + seriesIndex * (barWidth + barGap);
      const y = margin.top + plotHeight - barHeight;
      const labelText = `${category}，${series.label}：${value}`;
      const bar = svgEl('rect', {
        x,
        y,
        width: barWidth,
        height: Math.max(barHeight, 0.5),
        class: `chart-bar ${series.cls}`,
        tabindex: '0',
        role: 'img',
        'aria-label': labelText
      });
      bar.append(svgEl('title', {}, [labelText]));
      attachChartTip(bar, tooltip, labelText);
      chart.append(bar);
      if (value > 0) {
        const valueLabel = svgEl('text', {
          x: x + barWidth / 2,
          y: Math.max(margin.top + 9, y - 5),
          class: 'chart-bar-label',
          'text-anchor': 'middle'
        });
        valueLabel.textContent = String(value);
        chart.append(valueLabel);
      }
    });
    const categoryLabel = svgEl('text', {
      x: center,
      y: margin.top + plotHeight + 19,
      class: 'chart-category-text',
      'text-anchor': 'middle'
    });
    categoryLabel.textContent = truncate(category, 10);
    categoryLabel.append(svgEl('title', {}, [category]));
    chart.append(categoryLabel);
  });

  const scroll = el('div', { className: 'chart-scroll' });
  scroll.append(chart);
  const stage = el('div', { className: 'chart-stage' });
  stage.append(scroll, tooltip);
  inner.append(stage);
  container.append(inner);
}

function renderHorizontalBar(container, options) {
  clear(container);
  if (!options.rows.length) {
    container.append(el('p', { className: 'chart-empty', text: options.emptyText }));
    return;
  }
  const width = 640;
  const labelWidth = 100;
  const valueWidth = 46;
  const rowHeight = 30;
  const top = 8;
  const bottom = 8;
  const plotWidth = width - labelWidth - valueWidth - 16;
  const height = top + bottom + options.rows.length * rowHeight;
  const maxValue = Math.max(1, ...options.rows.map((row) => toInt(row.value)));
  const chart = svgEl('svg', {
    viewBox: `0 0 ${width} ${height}`,
    width,
    height,
    role: 'img',
    'aria-label': options.ariaLabel,
    class: 'chart-svg is-horizontal',
    xmlns: SVG_NS
  });
  const tooltip = el('p', {
    className: 'chart-tooltip',
    attrs: { role: 'tooltip' }
  });
  tooltip.hidden = true;

  options.rows.forEach((row, index) => {
    const value = toInt(row.value);
    const y = top + index * rowHeight;
    const barHeight = 14;
    const barY = y + (rowHeight - barHeight) / 2;
    const label = svgEl('text', {
      x: labelWidth - 8,
      y: barY + barHeight - 3,
      class: 'chart-category-text',
      'text-anchor': 'end'
    });
    label.textContent = truncate(row.label, 10);
    label.append(svgEl('title', {}, [String(row.label)]));
    chart.append(label);
    chart.append(svgEl('rect', {
      x: labelWidth,
      y: barY,
      width: plotWidth,
      height: barHeight,
      class: 'chart-track'
    }));
    const bar = svgEl('rect', {
      x: labelWidth,
      y: barY,
      width: Math.max((value / maxValue) * plotWidth, 0.5),
      height: barHeight,
      class: 'chart-bar single',
      tabindex: '0',
      role: 'img',
      'aria-label': `${row.label}：${value}`
    });
    const labelText = `${row.label}：${value}`;
    bar.append(svgEl('title', {}, [labelText]));
    attachChartTip(bar, tooltip, labelText);
    chart.append(bar);
    const valueLabel = svgEl('text', {
      x: labelWidth + plotWidth + 8,
      y: barY + barHeight - 3,
      class: 'chart-bar-label',
      'text-anchor': 'start'
    });
    valueLabel.textContent = String(value);
    chart.append(valueLabel);
  });

  const stage = el('div', { className: 'chart-stage' });
  stage.append(chart, tooltip);
  container.append(stage);
}

/* Render: header, filters, belt, KPI */

function renderMeta(snapshot) {
  dom.generatedAt.textContent = `更新于 ${formatDateTime(snapshot.generated_at)}`;
}

/* 首页「今天」：只回答今天要做什么，数据全部来自本地快照。 */
/* home-today:start（tools/tests/test_home_today.py 会截取本段用 node 执行） */
function homeGreetingText(row) {
  const greeting = row && row.greeting && typeof row.greeting === 'object' ? row.greeting : null;
  return greeting ? String(greeting.greeting || '').trim() : '';
}

function homeAlreadySent(row) {
  const delivery = row && row.delivery && typeof row.delivery === 'object' ? row.delivery : null;
  return Boolean(delivery && delivery.status === 'sent');
}

function homeMailNeedsReply(row) {
  const classification = row && row.classification && typeof row.classification === 'object'
    ? row.classification
    : {};
  return ['interview_invite', 'assessment', 'offer'].includes(String(classification.intent || ''));
}

function homeTaskCounts(snapshot) {
  const snap = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const queue = Array.isArray(snap.queue) ? snap.queue : [];
  const mails = Array.isArray(snap.mails) ? snap.mails : [];
  return {
    jobs: queue.filter((row) => row && row.status === 'pending').length,
    greetings: queue.filter((row) => row && row.status === 'approved'
      && homeGreetingText(row) && !homeAlreadySent(row)).length,
    replies: mails.filter(homeMailNeedsReply).length
  };
}

function homeParseDate(raw) {
  const text = String(raw || '').trim();
  if (!text) return null;
  const normalized = text.includes(' ') && !text.includes('T') ? text.replace(' ', 'T') : text;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function homeBatchCounts(batch) {
  const items = Array.isArray(batch && batch.items) ? batch.items : [];
  return items.reduce((total, item) => {
    const status = String((item && item.status) || '');
    if (status === 'sent') total.sent += 1;
    else if (status === 'failed') total.failed += 1;
    return total;
  }, { sent: 0, failed: 0 });
}

function homeBatchIsToday(batch, now) {
  const stamp = homeParseDate(batch && (batch.finished_at || batch.created_at || batch.started_at));
  if (!stamp) return false;
  const today = now instanceof Date ? now : new Date();
  return stamp.getFullYear() === today.getFullYear()
    && stamp.getMonth() === today.getMonth()
    && stamp.getDate() === today.getDate();
}

function homeDeliveryLine(snapshot, now) {
  const delivery = snapshot && snapshot.pipeline && snapshot.pipeline.delivery;
  const batches = delivery && Array.isArray(delivery.batches) ? delivery.batches : [];
  if (!batches.length) return '还没有发送记录。';
  const today = now instanceof Date ? now : new Date();
  const dated = batches.filter((batch) => homeBatchIsToday(batch, today));
  if (dated.length) {
    const total = dated.reduce((sum, batch) => {
      const counts = homeBatchCounts(batch);
      sum.sent += counts.sent;
      sum.failed += counts.failed;
      return sum;
    }, { sent: 0, failed: 0 });
    return `今天已发送 ${total.sent} 条，失败 ${total.failed} 条。`;
  }
  const latest = homeBatchCounts(batches[batches.length - 1]);
  return `最近一次发送：成功 ${latest.sent} 条，失败 ${latest.failed} 条。`;
}
/* home-today:end */

const SG_MONTHS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二'];

function homePipelineStageCount(snapshot, key) {
  const stages = snapshot && snapshot.pipeline && Array.isArray(snapshot.pipeline.stages)
    ? snapshot.pipeline.stages
    : [];
  const stage = stages.find((row) => row && row.key === key);
  const count = stage ? Number(stage.count) : 0;
  return Number.isFinite(count) ? Math.trunc(count) : 0;
}

function homeShortTime(value) {
  const date = new Date(String(value || ''));
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function homeTaskAction(id, count, active, quiet) {
  const button = document.getElementById(id);
  if (!button) return;
  const target = count === 0 ? quiet : active;
  button.classList.toggle('button-quiet', count === 0);
  if (button.textContent !== target.label) button.textContent = target.label;
  if (button.dataset.viewLink !== target.view) button.dataset.viewLink = target.view;
}

function renderHomeSide(snapshot) {
  if (!dom.sgPipeList) return;
  clear(dom.sgPipeList);
  [
    ['采集', 'intake'],
    ['筛选', 'screening'],
    ['通过', 'approval'],
    ['回复', 'monitor']
  ].forEach(([label, key]) => {
    const item = el('li', { className: 'sg-side-row' });
    item.append(el('span', { text: label }));
    item.append(el('span', { className: 'sg-side-num', text: String(homePipelineStageCount(snapshot, key)) }));
    dom.sgPipeList.append(item);
  });
  if (dom.sgPipeTotal) {
    const jobs = snapshot && Array.isArray(snapshot.jobs) ? snapshot.jobs.length : 0;
    dom.sgPipeTotal.textContent = `岗位池 ${jobs} 个`;
  }
  const rows = groupActivityRows(snapshot && Array.isArray(snapshot.activity) ? snapshot.activity : []).slice(0, 5);
  if (dom.sgActivityCount) dom.sgActivityCount.textContent = rows.length ? `最近 ${rows.length} 条` : '';
  if (!dom.sgHomeActivity) return;
  clear(dom.sgHomeActivity);
  if (!rows.length) {
    dom.sgHomeActivity.append(el('li', {
      className: 'sg-side-empty',
      text: '还没有操作记录。采集岗位后会出现在这里。'
    }));
    return;
  }
  rows.forEach((group) => {
    const item = el('li', { className: 'sg-activity-row' });
    item.append(el('span', { className: 'sg-activity-time', text: homeShortTime(group.row && group.row.at) }));
    item.append(el('span', {
      className: 'sg-activity-title',
      text: group.count > 1 ? `${group.title} ×${group.count}` : group.title
    }));
    dom.sgHomeActivity.append(item);
  });
}

function renderHomeToday(snapshot) {
  const counts = homeTaskCounts(snapshot);
  // 第三行是「HR 消息」：本地待回邮件 + 平台未读会话，与左侧导航徽标同一数据源。
  const hrUnread = Math.max(0, Number(state.hrUnreadTotal) || 0);
  const replies = counts.replies + hrUnread;
  const now = new Date();
  const weekday = '日一二三四五六'[now.getDay()];
  const total = counts.jobs + counts.greetings + replies;
  if (dom.homeDate) dom.homeDate.textContent = `${SG_MONTHS[now.getMonth()]}月 · 星期${weekday}`;
  if (dom.sgHomeDay) dom.sgHomeDay.textContent = String(now.getDate());
  if (dom.sgHomeLiveText) {
    dom.sgHomeLiveText.textContent = total
      ? `本机在线 · 还有 ${total} 件待办`
      : '本机在线 · 今天没有待办';
  }
  if (dom.homeJobsCount) dom.homeJobsCount.textContent = `${counts.jobs} 个`;
  if (dom.homeGreetingsCount) dom.homeGreetingsCount.textContent = `${counts.greetings} 条`;
  if (dom.homeRepliesCount) dom.homeRepliesCount.textContent = `${replies} 条`;
  homeTaskAction(
    'home-jobs-action',
    counts.jobs,
    { label: '去确认', view: 'queue' },
    { label: '去采集岗位', view: 'collect' }
  );
  homeTaskAction(
    'home-greetings-action',
    counts.greetings,
    { label: '去发送', view: 'queue' },
    { label: '去发送', view: 'queue' }
  );
  homeTaskAction(
    'home-replies-action',
    replies,
    { label: '去回复', view: 'mail' },
    { label: '去看收件箱', view: 'mail' }
  );
  if (dom.homeRepliesSub) {
    const summary = state.hrSummary && typeof state.hrSummary === 'object' ? state.hrSummary : null;
    const unread = summary ? Number(summary.unread_total) || 0 : null;
    dom.homeRepliesSub.textContent = unread === null
      ? '平台会话在「回复」页；本地邮件按意图计'
      : `平台会话未读 ${unread} 条；本地邮件 ${counts.replies} 封待回`;
  }
  if (dom.homeLede) {
    dom.homeLede.textContent = total
      ? `还有 ${total} 件待办，先做下面这些。`
      : '今天没有待办，可以去采集新岗位。';
  }
  if (dom.homeSendSummary) dom.homeSendSummary.textContent = homeDeliveryLine(snapshot);
  renderHomeSide(snapshot);
}

/* 六段契约只在前端合并成用户要做的四步：后端 PIPELINE_STAGES 与 /api/pipeline 的键都不变。 */
/* workbench-four-stages:start（tools/tests/test_web_backend.py 会截取本段用 node 执行） */
function workbenchFourStages(snapshot) {
  const snap = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const pipeline = snap.pipeline && typeof snap.pipeline === 'object' ? snap.pipeline : {};
  const stages = Array.isArray(pipeline.stages) ? pipeline.stages : [];
  const queue = Array.isArray(snap.queue) ? snap.queue : [];
  const countOf = (key) => {
    const stage = stages.find((item) => item && item.key === key);
    const count = stage ? Number(stage.count) : 0;
    return Number.isFinite(count) ? Math.trunc(count) : 0;
  };
  const intake = countOf('intake');
  const queued = queue.length;
  const greetings = queue.filter((row) => row && row.greeting
    && String(row.greeting.greeting || '').trim()).length;
  // 按岗位文档评分与必备条件自动 approved；「等你确认」只数最终投递确认门上的已通过岗位。
  const confirm = queue.filter((row) => row && row.status === 'approved').length;
  // 入队不再比较数字阈值，因此这里只解释「为什么还没有待确认岗位」。
  let reason = null;
  if (confirm === 0) {
    reason = intake === 0 ? '还没有采集到岗位' : '暂时没有需要你确认的岗位';
  }
  return [
    {
      key: 'intake',
      index: '01',
      title: '采集',
      unit: '个岗位',
      count: intake,
      description: '自动采集岗位，写入本地岗位池。',
      action: false,
      reason: null
    },
    {
      key: 'queue',
      index: '02',
      title: '评分筛选',
      unit: '个岗位',
      count: queued,
      description: '按岗位要求与简历证据自动筛选，合适的岗位进入审批队列。',
      action: false,
      reason: null
    },
    {
      key: 'greeting',
      index: '03',
      title: '招呼语已生成',
      unit: '条',
      count: greetings,
      description: '只为待确认岗位生成草稿，不会发送。',
      action: false,
      reason: null
    },
    {
      key: 'confirm',
      index: '04',
      title: '等你确认',
      unit: '个岗位',
      count: confirm,
      description: '确认后才会开始投递；未确认前不会发出任何消息。',
      action: true,
      reason
    }
  ];
}
/* workbench-four-stages:end */

const PIPELINE_STATUS_LABELS = {
  ready: '本地可用',
  local: '本地可用',
  connected: '已接入回报',
  waiting: '待接入'
};

const PIPELINE_STAGE_LABELS = { send: '发送', monitor: '监控' };
const PIPELINE_EVENT_LABELS = {
  started: '开始',
  succeeded: '成功',
  failed: '失败',
  skipped: '跳过'
};

function renderPipeline(snapshot) {
  if (!dom.pipeline) return;
  clear(dom.pipeline);
  const stages = workbenchFourStages(snapshot);
  stages.forEach((stage) => {
    const card = el('div', {
      className: `pipeline-node workbench-stage${stage.action ? ' is-confirm' : ' is-readonly'}`,
      attrs: {
        'data-workbench-stage': stage.key,
        'aria-label': `${stage.title}，${stage.count} ${stage.unit}${stage.reason ? `；${stage.reason}` : ''}`
      }
    }, [
      el('span', { className: 'pipeline-top' }, [
        el('span', { className: 'pipeline-index', text: stage.index }),
        el('span', { className: 'pipeline-owner', text: stage.action ? '需要你' : '自动' })
      ]),
      el('span', { className: 'pipeline-name', text: stage.title }),
      el('span', { className: 'pipeline-desc', text: stage.description }),
      el('span', { className: 'pipeline-count' }, [
        el('strong', { text: String(stage.count) }),
        el('span', { text: stage.unit })
      ])
    ]);
    if (stage.reason) {
      card.append(el('span', { className: 'workbench-reason', text: stage.reason }));
    }
    if (stage.action) {
      const button = el('button', {
        className: 'button button-small workbench-confirm-button',
        attrs: { type: 'button' },
        text: '去确认岗位'
      });
      button.addEventListener('click', () => {
        showView('queue');
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
      card.append(button);
    }
    dom.pipeline.append(card);
  });

  const pipeline = snapshot && snapshot.pipeline ? snapshot.pipeline : null;
  if (dom.pipelineEvents) {
    const events = pipeline && Array.isArray(pipeline.external_events) ? pipeline.external_events : [];
    clear(dom.pipelineEvents);
    dom.pipelineEvents.hidden = events.length === 0;
    if (events.length) {
      dom.pipelineEvents.append(el('p', { className: 'subhead', text: '最近外部回报' }));
      events.forEach((row) => {
        const stage = PIPELINE_STAGE_LABELS[row.stage] || row.stage || '外部';
        const status = PIPELINE_EVENT_LABELS[row.status] || row.status || '';
        const detail = row.message || row.job_id || '无附加说明';
        dom.pipelineEvents.append(el('div', { className: 'external-event' }, [
          el('span', { className: `badge badge-${row.status === 'failed' ? 'bad' : 'neutral'}`, text: `${stage}，${status}` }),
          el('span', { className: 'external-event-detail', text: detail }),
          el('span', { className: 'external-event-time', text: formatDateTime(row.received_at) })
        ]));
      });
    }
  }
}

function renderBelt(snapshot) {
  clear(dom.belt);
  const states = Array.isArray(snapshot.states) ? snapshot.states : [];
  const counts = snapshot.state_counts || {};
  const transitions = snapshot.transitions || {};

  states.forEach((stateName, index) => {
    if (index > 0) {
      const previous = states[index - 1];
      const allowed = Array.isArray(transitions[previous]) ? transitions[previous] : [];
      const direct = allowed.includes(stateName);
      const arrow = el('span', {
        className: `belt-arrow${direct ? '' : ' is-branch'}`,
        text: '→',
        attrs: {
          'aria-hidden': 'true',
          title: direct
            ? `${previous} 可流转至 ${stateName}`
            : `${previous} 与 ${stateName} 之间无直接流转`
        }
      });
      dom.belt.append(arrow);
    }
    const count = toInt(counts[stateName]);
    const outgoing = Array.isArray(transitions[stateName]) ? transitions[stateName] : [];
    const node = el('button', {
      className: `belt-node stage-${Math.floor((index * 4) / Math.max(1, states.length - 1))}`,
      attrs: {
        type: 'button',
        'aria-pressed': String(state.jobState === stateName),
        'aria-label': `${stateName}，${count} 个岗位；可流转至 ${outgoing.length ? outgoing.join('、') : '无，已是最终状态'}`
      }
    }, [
      el('span', { className: 'belt-index', text: String(index + 1) }),
      el('span', { className: 'belt-name', text: stateName }),
      el('span', { className: 'belt-count', text: String(count) }),
      el('span', { className: 'belt-unit', text: '个岗位' })
    ]);
    node.classList.toggle('is-current', state.jobState === stateName);
    node.addEventListener('click', () => {
      state.jobState = state.jobState === stateName ? 'all' : stateName;
      loadState();
    });
    dom.belt.append(node);
  });

  if (state.jobState === 'all') {
    const scope = snapshot.scope || {};
    dom.beltFocus.textContent = `当前焦点：全部状态，显示 ${toInt(scope.jobs)} 个岗位，共 ${toInt(scope.all_jobs)} 个。`;
  } else {
    const count = toInt(counts[state.jobState]);
    const outgoing = Array.isArray(transitions[state.jobState]) ? transitions[state.jobState] : [];
    dom.beltFocus.textContent = `当前焦点：${state.jobState}，${count} 个岗位；可以转到：${outgoing.length ? outgoing.join('、') : '已是最终状态'}`;
  }
}

function renderKpis(snapshot) {
  const kpis = snapshot.kpis || {};
  const definitions = [
    ['jobs', '岗位'],
    ['pending', '待确认'],
    ['applied', '投递'],
    ['interviews', '面试'],
    ['offers', 'Offer'],
    ['warnings', '警告']
  ];
  clear(dom.kpiRow);
  definitions.forEach(([key, label]) => {
    const value = toInt(kpis[key]);
    const card = el('article', {
      className: `kpi${key === 'warnings' && value > 0 ? ' is-alert' : ''}`
    }, [
      el('p', { className: 'kpi-label', text: label }),
      el('p', { className: 'kpi-value', text: String(value) })
    ]);
    dom.kpiRow.append(card);
  });
}

/* Render: charts and their tables */

function renderChannelChart(snapshot) {
  const rows = Array.isArray(snapshot.channel_rows) ? snapshot.channel_rows : [];
  const categories = rows.map((row) => channelLabel(row.Source_Channel));
  const series = [
    { label: '投递数', cls: 's1', values: rows.map((row) => toInt(row['投递数'])) },
    { label: '面试数', cls: 's2', values: rows.map((row) => toInt(row['面试数'])) },
    { label: 'Offer数', cls: 's3', values: rows.map((row) => toInt(row['Offer数'])) }
  ];
  renderGroupedBar(dom.channelChart, {
    categories,
    series,
    ariaLabel: '渠道转化分组柱图：投递数、面试数、Offer数',
    emptyText: '当前筛选下暂无渠道转化数据。'
  });
  renderTable(dom.channelTable, {
    caption: '表：渠道转化计数与转化率',
    columns: ['渠道', '投递数', '面试数', 'Offer数', '面试转化率', 'Offer转化率'],
    rows: rows.map((row) => [
      channelLabel(row.Source_Channel),
      toInt(row['投递数']),
      toInt(row['面试数']),
      toInt(row['Offer数']),
      formatPercent(row['面试转化率']),
      formatPercent(row['Offer转化率'])
    ]),
    emptyText: '当前筛选下暂无渠道数据。',
    className: 'data-table-wide'
  });
}

function renderQuarterChart(snapshot) {
  const radar = snapshot.quarterly_radar || {};
  const quarterMap = radar.quarters && typeof radar.quarters === 'object' ? radar.quarters : {};
  const quarters = Object.keys(quarterMap).sort();
  const axes = Array.isArray(radar.axes) ? radar.axes : [
    '投递数', '面试数', 'Offer数', '逻辑漏洞', '量化不足', 'STAR缺失', '业务理解', '表达冗余'
  ];
  const countAxes = ['投递数', '面试数', 'Offer数'];
  const series = countAxes.map((axis, index) => ({
    label: axis,
    cls: `s${index + 1}`,
    values: quarters.map((quarter) => {
      const row = quarterMap[quarter] || {};
      return toInt(row[axis]);
    })
  }));
  renderGroupedBar(dom.quarterChart, {
    categories: quarters,
    series,
    ariaLabel: '季度分组柱图：投递数、面试数、Offer数',
    emptyText: '当前筛选下暂无季度计数。'
  });
  renderTable(dom.quarterTable, {
    caption: '表：季度计数与弱点标签原始数据（8 轴）',
    columns: ['季度', ...axes],
    rows: quarters.map((quarter) => {
      const row = quarterMap[quarter] || {};
      return [quarter, ...axes.map((axis) => toInt(row[axis]))];
    }),
    emptyText: '当前筛选下暂无季度数据。',
    className: 'data-table-wide'
  });
}

function renderWeaknessChart(snapshot) {
  const rows = Array.isArray(snapshot.weakness_rows) ? snapshot.weakness_rows : [];
  renderHorizontalBar(dom.weaknessChart, {
    rows: rows.map((row) => ({
      label: String(row.label || '未标注'),
      value: toInt(row.value)
    })),
    ariaLabel: '弱点标签单系列条形图',
    emptyText: '当前筛选下暂无弱点标签。'
  });
  renderTable(dom.weaknessTable, {
    caption: '表：弱点标签计数',
    columns: ['弱点标签', '次数'],
    rows: rows.map((row) => [String(row.label || '未标注'), toInt(row.value)]),
    emptyText: '当前筛选下暂无弱点数据。'
  });
}

function renderMailChart(snapshot) {
  const rows = Array.isArray(snapshot.mail_rows) ? snapshot.mail_rows : [];
  renderHorizontalBar(dom.mailChart, {
    rows: rows.map((row) => ({
      label: String(row.label || intentLabel(row.key)),
      value: toInt(row.value)
    })),
    ariaLabel: '邮件意图单系列条形图',
    emptyText: '当前筛选下暂无邮件分类数据。'
  });
  renderTable(dom.mailTable, {
    caption: '表：邮件意图计数',
    columns: ['意图', '数量'],
    rows: rows.map((row) => [String(row.label || intentLabel(row.key)), toInt(row.value)]),
    emptyText: '当前筛选下暂无邮件数据。'
  });
}

/* Render: jobs */

function badge(text, kind, symbol) {
  const node = el('span', {
    className: `badge badge-${kind}`,
    text: symbol ? `${symbol} ${text}` : String(text)
  });
  return node;
}

function riskBadgeNode(risk) {
  const level = risk && typeof risk === 'object' ? String(risk.level || 'low') : 'low';
  const signals = risk && Array.isArray(risk.signals) ? risk.signals : [];
  const detail = signals.map((item) => `${item.label}${item.evidence ? `（${item.evidence}）` : ''}`).join('；');
  let node;
  if (level === 'high') node = badge('高风险', 'bad', '×');
  else if (level === 'verify') node = badge('需核实', 'warn', '!');
  else node = badge('正常', 'good', '✓');
  if (detail) node.setAttribute('title', detail);
  return node;
}

// 后端返回的硬筛原因/警告是 {code, message, ...} 对象，旧数据可能是字符串。
// 统一取出可读文本，避免把对象直接 join 成「[object Object]」。
function reasonText(items) {
  return (Array.isArray(items) ? items : [])
    .map((item) => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object') {
        return String(item.message || item.reason || item.code || '').trim();
      }
      return String(item || '').trim();
    })
    .filter(Boolean)
    .join('；');
}

function hardFilterNode(job) {
  const raw = job.hard_filter;
  const status = raw && typeof raw === 'object' ? String(raw.status || 'unknown') : String(raw || 'unknown');
  let node;
  if (status === 'pass') node = badge('通过', 'good', '✓');
  else if (status === 'reject') node = badge('拒绝', 'bad', '×');
  else node = badge('未知', 'neutral', '?');
  const reasons = raw && typeof raw === 'object' && Array.isArray(raw.reasons) ? raw.reasons : [];
  const text = reasonText(reasons);
  if (text) node.setAttribute('title', `原因：${text}`);
  return node;
}

function approvalNode(value) {
  if (value === 'approved') return badge('已确认可人工投递', 'good', '✓');
  if (value === 'pending') return badge('待确认', 'warn', '!');
  if (value) return badge(String(value), 'neutral', '·');
  return el('span', { className: 'muted', text: '未加入队列' });
}

/* jobs-dossier:start（tools/tests/test_jobs_dossier.py 会截取本段用 node 执行） */
const JOB_STANDARD_FIELDS = [
  ['title', '岗位名称'],
  ['location', '工作地点'],
  ['responsibilities', '工作内容'],
  ['must_have', '必备条件'],
  ['nice_to_have', '加分条件'],
  ['salary_and_start', '薪资与到岗'],
  ['hiring_status', '招聘状态'],
  ['source_platform', '来源平台'],
  ['source_updated_at', '来源更新时间']
];

function dossierText(value) {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text ? text : null;
}

function dossierList(value) {
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (item && typeof item === 'object') {
          return dossierText(item.text || item.label || item.value || item.item);
        }
        return dossierText(item);
      })
      .filter(Boolean);
  }
  const text = dossierText(value);
  if (!text) return [];
  return text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
}

/* 后端给的是枚举原值或对象；这里只翻译成人话，缺值仍返回 null（显示为「未知」），不猜测。 */
const DOSSIER_HIRING_STATUS = { closed: '已停止招聘', not_closed: '仍在招聘', unknown: null };
const DOSSIER_SOURCE_PLATFORM = { boss: 'BOSS直聘', liepin: '猎聘', zhilian: '智联招聘', job51: '前程无忧' };
const DOSSIER_RISK_LEVEL = { low: '低', medium: '中', high: '高' };

function dossierSalaryAndStart(raw) {
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    const parts = [];
    const salary = dossierText(raw.salary);
    const start = dossierText(raw.start);
    if (salary) parts.push(`薪资 ${salary}`);
    if (start) parts.push(`到岗 ${start}`);
    return parts.length ? parts.join('；') : null;
  }
  return dossierText(raw);
}

function dossierEnum(map, raw) {
  const text = dossierText(raw);
  if (text === null) return null;
  return Object.prototype.hasOwnProperty.call(map, text) ? map[text] : text;
}

function dossierFormatValue(key, raw) {
  if (Array.isArray(raw)) return dossierList(raw).join('\n') || null;
  if (key === 'salary_and_start') return dossierSalaryAndStart(raw);
  if (key === 'hiring_status') return dossierEnum(DOSSIER_HIRING_STATUS, raw);
  if (key === 'source_platform') return dossierEnum(DOSSIER_SOURCE_PLATFORM, raw);
  return dossierText(raw);
}

function dossierStandard(job) {
  const standard = job && typeof job.standard === 'object' && job.standard ? job.standard : {};
  return JOB_STANDARD_FIELDS.map(([key, label]) => ({
    key,
    label,
    value: dossierFormatValue(key, standard[key])
  }));
}

function dossierConfidence(raw) {
  // 0–1 的小数显示成百分比；已经是文字（如「中」）的原样保留。
  if (typeof raw === 'number' && raw >= 0 && raw <= 1) return `${Math.round(raw * 100)}%`;
  return dossierText(raw);
}

function dossierMatch(job) {
  const match = job && typeof job.match === 'object' && job.match ? job.match : {};
  return [
    { key: 'fit_score', label: '适配分', value: dossierText(match.fit_score) },
    { key: 'fit_confidence', label: '判断依据', value: dossierConfidence(match.fit_confidence) },
    { key: 'risk_level', label: '岗位风险等级', value: dossierEnum(DOSSIER_RISK_LEVEL, match.risk_level) }
  ];
}

function dossierTraceability(job) {
  const rows = job && Array.isArray(job.traceability) ? job.traceability : [];
  return rows
    .map((row) => ({
      requirement: dossierText(row && row.requirement),
      evidence: dossierText(row && row.project_evidence),
      source: dossierText(row && row.source)
    }))
    .filter((row) => row.requirement || row.evidence || row.source);
}

function dossierParts(job) {
  const dossier = job && typeof job.dossier === 'object' && job.dossier ? job.dossier : {};
  const existingGreeting = job && job.greeting && typeof job.greeting === 'object' ? job.greeting.greeting : job && job.greeting;
  return {
    analysis: dossierText(dossier.analysis_card),
    resume: dossierText(dossier.resume_variant),
    greeting: dossierText(dossier.greeting) || dossierText(existingGreeting),
    checklist: dossierList(dossier.checklist),
    action: dossierText(dossier.recommended_action)
  };
}

function dossierFindJob(snapshot, id) {
  const jobs = snapshot && Array.isArray(snapshot.jobs) ? snapshot.jobs : [];
  return jobs.find((job) => String((job && job.id) || '') === String(id)) || null;
}

function queueReviewJob(snapshot, id) {
  if (id === null || id === undefined) return null;
  const queue = snapshot && Array.isArray(snapshot.queue) ? snapshot.queue : [];
  const row = queue.find((item) => String((item && item.id) || '') === String(id));
  if (!row) return null;
  return Object.assign({}, dossierFindJob(snapshot, id) || {}, row);
}

/* 定制材料（materials）：字段名由后端固定，materials 为 null 表示尚未生成。
   这里只做纯数据归一与联系方式过滤；渲染层在 jobs-dossier 区块之外。 */
const MATERIALS_GREETING_VARIANTS = [
  { key: 'concise', label: '简洁版' },
  { key: 'project', label: '项目成果版' },
  { key: 'safe', label: '稳妥版' }
];

// 电话、邮箱、微信与链接一律不进入界面；外部文本仍按数据处理。
const MATERIALS_REDACTIONS = [
  [/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, '［邮箱已隐藏］'],
  [/\bhttps?:\/\/[^\s，。；、）)]+/gi, '［链接已隐藏］'],
  [/\bwww\.[^\s，。；、）)]+/gi, '［链接已隐藏］'],
  [/(?:微信|微 信|wechat|weixin|\bwx\b|\bvx\b)\s*[:：]?\s*[A-Za-z0-9_-]{4,}/gi, '［微信已隐藏］'],
  [/(?:\+?86[-\s]?)?1[3-9]\d{9}/g, '［电话已隐藏］'],
  [/\b0\d{2,3}[-\s]\d{7,8}\b/g, '［电话已隐藏］']
];

function materialsSafeText(value) {
  const text = dossierText(value);
  if (!text) return null;
  return MATERIALS_REDACTIONS.reduce(
    (result, [pattern, replacement]) => result.replace(pattern, replacement),
    text
  );
}

function materialsTextList(value) {
  return dossierList(value).map((item) => materialsSafeText(item)).filter(Boolean);
}

function materialsObjectList(value) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : [];
}

function materialsStatusTone(status) {
  if (status === '已满足') return 'met';
  if (status === '明确不满足') return 'unmet';
  if (status === '待确认') return 'pending';
  return 'unknown';
}

// 与队列卡片共用 greeting.selection 的来源标注：能对上就选中对应版本。
function materialsGreetingSelection(job, greetings) {
  const greeting = job && job.greeting && typeof job.greeting === 'object' ? job.greeting : {};
  const label = dossierText(greeting.selection);
  const withText = MATERIALS_GREETING_VARIANTS.filter((variant) => greetings[variant.key]);
  const matched = label
    ? withText.find((variant) => label === variant.key
      || label === variant.label
      || label.indexOf(variant.label) !== -1)
    : null;
  if (matched) return matched.key;
  return withText.length ? withText[0].key : '';
}

function materialsOf(job) {
  const raw = job && typeof job.materials === 'object' && job.materials ? job.materials : null;
  if (!raw) return null;
  const mapping = materialsObjectList(raw.mapping)
    .map((row) => ({
      requirement: materialsSafeText(row.requirement),
      evidence: materialsSafeText(row.evidence),
      source: materialsSafeText(row.source)
    }))
    .filter((row) => row.requirement || row.evidence || row.source);
  const conditions = materialsObjectList(raw.conditions)
    .map((row) => ({
      condition: materialsSafeText(row.condition),
      status: materialsSafeText(row.status),
      evidence: materialsSafeText(row.evidence)
    }))
    .filter((row) => row.condition || row.status || row.evidence);
  const resumeSuggestions = materialsObjectList(raw.resume_suggestions)
    .map((row) => ({
      original: materialsSafeText(row.original),
      suggested: materialsSafeText(row.suggested),
      evidence: materialsSafeText(row.evidence),
      reason: materialsSafeText(row.reason)
    }))
    .filter((row) => row.original || row.suggested || row.evidence || row.reason);
  const rawGreetings = raw.greetings && typeof raw.greetings === 'object' ? raw.greetings : {};
  const greetings = {};
  MATERIALS_GREETING_VARIANTS.forEach((variant) => {
    greetings[variant.key] = materialsSafeText(rawGreetings[variant.key]);
  });
  return {
    mapping,
    conditions,
    unknownFields: materialsTextList(raw.unknown_fields),
    resumeSuggestions,
    greetings,
    confirmItems: materialsTextList(raw.confirm_items),
    selected: materialsGreetingSelection(job, greetings)
  };
}
/* jobs-dossier:end */

// 岗位评分的两个尺度：旧的手动 0–5 分不参与自动入队，只有岗位文档的
// 0–100 匹配分（且信息覆盖率 > 0）才算文档评分。后端 enqueue 的判定是
// 「没有文档评分，或必备条件明确不满足，或岗位已关闭」都需要手动加入。
const DOC_SCORE_SCALE = '0-100（文档匹配分）';

function jobHasDocumentScore(job) {
  if (!job || typeof job.score !== 'number' || !Number.isFinite(job.score)) return false;
  // 快照里 score_scale 为 "100"（文档评分）或 "5"（旧手动分）；岗位原始记录里是完整标签。
  if (job.score_scale === DOC_SCORE_SCALE || job.score_scale === '100') {
    return typeof job.score_coverage === 'number' && job.score_coverage > 0;
  }
  // 兼容旧快照：没有 score_scale 时，只有带正覆盖率才按文档评分处理。
  return job.score_scale == null
    && typeof job.score_coverage === 'number'
    && job.score_coverage > 0;
}

function jobNeedsManualEnqueue(job) {
  if (!job) return true;
  if (job.mandatory_status === 'unsatisfied' || job.hiring_status === 'closed') return true;
  // 文档评分为 0 不自动通过（与后端 enqueue 的 zero_score_held 一致）。
  if (jobHasDocumentScore(job) && Number(job.score) <= 0) return true;
  return !jobHasDocumentScore(job);
}

function formatJobScore(job) {
  if (!job || job.score === null || job.score === undefined || job.score === '') return '未评分';
  const number = Number(job.score);
  if (!Number.isFinite(number)) return '未评分';
  if (jobHasDocumentScore(job) || number > 5) {
    return `${Math.round(number)}/100`;
  }
  return `${number}/5`;
}

function renderJobs(snapshot) {
  const jobs = Array.isArray(snapshot.jobs) ? snapshot.jobs : [];
  const transitions = snapshot.transitions || {};
  dom.jobsCount.textContent = `显示 ${jobs.length} 条`;
  // 空表有两种原因：岗位池确实为空，或当前筛选没有命中。分开提示，
  // 否则用户会被引导去重新采集，而其实池子里已经有岗位。
  const allJobs = snapshot.scope && Number.isFinite(Number(snapshot.scope.all_jobs))
    ? Number(snapshot.scope.all_jobs)
    : null;
  const filteredEmpty = jobs.length === 0 && allJobs !== null && allJobs > 0;
  if (dom.jobsEmptyHint) dom.jobsEmptyHint.hidden = jobs.length > 0 || filteredEmpty;
  if (dom.jobsFilterEmptyHint) dom.jobsFilterEmptyHint.hidden = !filteredEmpty;

  // 选择按岗位 id 保留：切换筛选只隐藏行，不清掉已选中的岗位。

  const rows = jobs.map((job) => {
    const jobId = String(job.id);
    const checkbox = el('input', {
      attrs: {
        type: 'checkbox',
        'aria-label': `选择 ${String(job.company || '')} ${String(job.title || '')}`.trim()
      }
    });
    checkbox.checked = state.jobsSelection.has(jobId);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) state.jobsSelection.add(jobId);
      else state.jobsSelection.delete(jobId);
      syncJobsSelection(jobs);
    });
    const warnings = Array.isArray(job.warnings) ? job.warnings : [];
    const warningCell = warnings.length
      ? badge(String(warnings.length), 'warn', '!')
      : el('span', { className: 'muted', text: '0' });
    if (warnings.length) warningCell.setAttribute('title', reasonText(warnings));
    const riskNode = riskBadgeNode(job.risk);

    const actions = el('div', { className: 'row-actions jobs-actions' });
    const queued = job.approval !== null && job.approval !== undefined;
    const needsManual = jobNeedsManualEnqueue(job);
    const enqueueButton = el('button', {
      className: 'button button-small button-quiet',
      text: queued ? '已在审批队列' : needsManual ? '手动加入审批队列' : '加入审批队列',
      attrs: { type: 'button' }
    });
    enqueueButton.disabled = queued;
    if (queued) {
      enqueueButton.title = '该岗位已在审批队列中';
      enqueueButton.setAttribute('aria-label', '已在审批队列（不可重复加入）');
    } else if (needsManual) {
      enqueueButton.title = '该岗位不会自动通过（没有文档评分、必备条件不满足或已关闭）；点击后手动加入待确认队列';
      enqueueButton.setAttribute('aria-label', '手动加入审批队列（该岗位需要你自行判断，并选择手动加入原因）');
    } else {
      enqueueButton.title = '只加入待确认队列，不投递';
      enqueueButton.setAttribute('aria-label', '加入审批队列（只加入待确认队列，不投递）');
    }
    enqueueButton.addEventListener('click', () => {
      enqueueJob(job, enqueueButton, needsManual);
    });
    actions.append(enqueueButton);

    const prepareButton = el('button', {
      className: 'button button-small button-quiet',
      text: '生成投递准备清单',
      attrs: {
        type: 'button',
        'aria-label': '生成投递准备清单（只生成清单，不提交申请）'
      }
    });
    prepareButton.title = '只生成人工准备清单，不提交申请';
    prepareButton.addEventListener('click', () => prepareJob(job, prepareButton));
    actions.append(prepareButton);

    const allowed = Array.isArray(transitions[job.state]) ? transitions[job.state] : [];
    if (allowed.length) {
      const select = el('select', {
        attrs: { 'aria-label': `更新 ${job.company || ''} ${job.title || ''} 的状态` }
      });
      select.append(new Option('更新状态…', ''));
      allowed.forEach((target) => select.append(new Option(String(target), String(target))));
      select.addEventListener('change', () => {
        const target = select.value;
        if (!target) return;
        // 终态先确认；取消时把下拉还原到「更新状态…」。
        if (IRREVERSIBLE_JOB_STATES.has(target)
          && !window.confirm(`确定改为「${target}」吗？此状态不可恢复。`)) {
          select.value = '';
          return;
        }
        transitionJob(job, target, select);
      });
      actions.append(select);
    } else {
      actions.append(el('span', { className: 'terminal-note', text: '已是最终状态' }));
    }

    const dossierButton = el('button', {
      className: 'button button-small button-quiet',
      text: '查看详情',
      attrs: {
        type: 'button',
        'aria-label': `查看 ${String(job.company || '')} ${String(job.title || '')} 的标准字段与匹配结果`.trim()
      }
    });
    dossierButton.addEventListener('click', () => {
      // 关闭抽屉时把焦点还给打开它的按钮；程序触发的 click 不会自动聚焦。
      dossierButton.focus({ preventScroll: true });
      openJobDossier(job);
    });
    actions.append(dossierButton);

    // 入队失败（未评分、必备条件不满足、已关闭、城市不符等）的岗位保留勾选，
    // 并在行内写明原因，避免用户只看到一条汇总文案。
    const enqueueNote = state.jobsEnqueueNotes[jobId];
    if (enqueueNote) {
      actions.append(el('span', {
        className: 'terminal-note jobs-enqueue-note',
        text: enqueueNote,
        attrs: { title: enqueueNote }
      }));
    }

    const companyText = String(job.company || '未填写公司');
    const titleText = String(job.title || '未填写岗位');
    const platformText = channelLabel(job.source_channel);
    const scoreText = formatJobScore(job);
    const scoreNode = el('span', {
      className: scoreText === '未评分' ? 'jobs-score jobs-score-empty' : 'jobs-score',
      text: scoreText
    });
    return [
      checkbox,
      el('span', { className: 'jobs-company', text: companyText, attrs: { title: companyText } }),
      el('span', { className: 'jobs-title', text: titleText, attrs: { title: titleText } }),
      el('span', { className: 'jobs-city', text: String(job.city || '—') }),
      el('span', { className: 'jobs-salary', text: String(job.salary_label || '未填写') }),
      el('span', { className: 'jobs-platform', text: platformText, attrs: { title: `来源平台：${platformText}` } }),
      scoreNode,
      el('span', { className: 'jobs-hard-filter' }, [hardFilterNode(job)]),
      el('span', { className: 'jobs-risk' }, [riskNode]),
      el('span', { className: 'jobs-state', text: String(job.state || '未知') }),
      el('span', { className: 'jobs-approval' }, [approvalNode(job.approval)]),
      warningCell,
      actions
    ];
  });

  renderTable(dom.jobsTable, {
    caption: '表：岗位清单与允许的下一步',
    columns: ['选择', '公司', '岗位', '城市', '薪资', '来源平台', '评分', '硬条件', '风险', '状态', '审批状态', '警告数', '动作'],
    rows,
    emptyText: '当前筛选下没有岗位。可以调整筛选，或在下方粘贴 JD / 导入静态 JSON。',
    className: 'jobs-table'
  });

  const dossierJob = jobs.find((job) => String(job.id) === String(state.jobsDossierId)) || null;
  if (dossierJob && dom.jobsDossier && dom.jobsDossierBody) {
    dom.jobsDossier.hidden = false;
    renderDossier(dom.jobsDossierBody, dossierJob);
  } else if (dom.jobsDossier) {
    state.jobsDossierId = null;
    dom.jobsDossier.hidden = true;
    clear(dom.jobsDossierBody);
  }
  syncJobsSelection(jobs);
}

function dossierSection(title, children) {
  return el('section', { className: 'jobs-dossier-section' }, [
    el('h4', { className: 'jobs-dossier-heading', text: title }),
    ...children
  ]);
}

function dossierSectionText(title, value, className) {
  return dossierSection(title, [
    el('p', {
      className: value ? className || 'jobs-dossier-text' : 'jobs-dossier-empty',
      text: value || '未知'
    })
  ]);
}

function dossierSectionList(title, values) {
  if (!values.length) return dossierSection(title, [el('p', { className: 'jobs-dossier-empty', text: '未知' })]);
  return dossierSection(title, [
    el('ul', { className: 'jobs-dossier-list' }, values.map((value) => el('li', { text: value })))
  ]);
}

function dossierStandardSection(job) {
  const list = el('dl', { className: 'jobs-dossier-fields' });
  dossierStandard(job).forEach(({ key, label, value }) => {
    const item = el('div', { className: 'jobs-dossier-field' });
    item.dataset.field = key;
    item.append(el('dt', { text: label }));
    item.append(el('dd', {
      className: value ? '' : 'jobs-dossier-unknown',
      text: value || '未知'
    }));
    list.append(item);
  });
  return dossierSection('标准字段', [list]);
}

function dossierMatchSection(job) {
  const row = el('div', { className: 'jobs-dossier-match' });
  dossierMatch(job).forEach(({ key, label, value }) => {
    const item = el('div', { className: 'jobs-dossier-match-item' });
    item.dataset.match = key;
    item.append(el('span', { className: 'jobs-dossier-match-label', text: label }));
    item.append(el('span', {
      className: value ? 'jobs-dossier-match-value' : 'jobs-dossier-match-value jobs-dossier-unknown',
      text: value || '未知'
    }));
    row.append(item);
  });
  return dossierSection('匹配结果', [row]);
}

function dossierTraceSection(job) {
  const rows = dossierTraceability(job);
  if (!rows.length) {
    return dossierSection('逐条核对', [el('p', { className: 'jobs-dossier-empty', text: '未知' })]);
  }
  const list = el('ul', { className: 'jobs-dossier-trace' });
  rows.forEach((row) => {
    const item = el('li', { className: 'jobs-dossier-trace-row' });
    item.append(el('p', { className: 'jobs-dossier-trace-requirement', text: row.requirement || '未知' }));
    item.append(el('p', {
      className: 'jobs-dossier-trace-evidence',
      text: row.evidence ? `项目证据：${row.evidence}` : '项目证据：未知'
    }));
    item.append(el('p', {
      className: 'jobs-dossier-trace-source',
      text: row.source ? `来源：${row.source}` : '来源：未知'
    }));
    list.append(item);
  });
  return dossierSection('逐条核对', [list]);
}

function dossierGreetingEvidenceSection(job) {
  const parts = dossierParts(job);
  const children = [
    el('p', {
      className: parts.analysis ? 'jobs-dossier-text' : 'jobs-dossier-empty',
      text: parts.analysis || '未知'
    })
  ];
  const sources = Array.from(new Set(dossierTraceability(job).map((row) => row.source).filter(Boolean)));
  if (sources.length) {
    children.push(el('p', { className: 'jobs-dossier-sources', text: `依据来源：${sources.join('；')}` }));
  }
  return dossierSection('招呼语依据', children);
}

/* 定制材料：只增区块，不改上面已有的详情段。 */
function materialsTextCell(value) {
  if (!value) return el('span', { className: 'jobs-dossier-empty', text: '未知' });
  return el('span', { className: 'jobs-materials-text', text: value });
}

function materialsBlock(title, children, className) {
  return el('div', { className: className ? `jobs-materials-block ${className}` : 'jobs-materials-block' }, [
    el('h5', { className: 'jobs-materials-subheading', text: title }),
    ...children
  ]);
}

function materialsEmptyBlock(title) {
  return materialsBlock(title, [el('p', { className: 'jobs-dossier-empty', text: '未知' })]);
}

// 表格样式与窄屏堆叠由 data-label 承担：宽屏并排，窄屏逐格列出。
function materialsTable(tableClassName, headers, rows) {
  const table = el('table', { className: `jobs-materials-table ${tableClassName}` });
  const headRow = el('tr');
  headers.forEach((label) => {
    headRow.append(el('th', { attrs: { scope: 'col' }, text: label }));
  });
  const thead = el('thead');
  thead.append(headRow);
  table.append(thead);
  const tbody = el('tbody');
  rows.forEach((cells) => {
    const tr = el('tr');
    cells.forEach((cell) => {
      const td = el('td', { attrs: { 'data-label': cell.label } });
      td.append(cell.node);
      tr.append(td);
    });
    tbody.append(tr);
  });
  table.append(tbody);
  return el('div', { className: 'jobs-materials-scroll' }, [table]);
}

function materialsNote(parts) {
  const lines = parts.filter(Boolean);
  if (!lines.length) return null;
  return el('p', { className: 'jobs-materials-note', text: lines.join('；') });
}

function materialsMappingBlock(materials) {
  if (!materials.mapping.length) return materialsEmptyBlock('岗位要求与证据');
  const rows = materials.mapping.map((row) => [
    { label: '岗位要求', node: materialsTextCell(row.requirement) },
    { label: '项目证据', node: materialsTextCell(row.evidence) },
    { label: '来源', node: materialsTextCell(row.source) }
  ]);
  return materialsBlock('岗位要求与证据', [
    materialsTable('jobs-materials-table--mapping', ['岗位要求', '项目证据', '来源'], rows)
  ]);
}

function materialsConditionsBlock(materials) {
  if (!materials.conditions.length) return materialsEmptyBlock('硬条件');
  const rows = materials.conditions.map((row) => {
    const tone = materialsStatusTone(row.status);
    return [
      { label: '条件', node: materialsTextCell(row.condition) },
      {
        label: '状态',
        node: el('span', {
          className: `jobs-materials-status jobs-materials-status--${tone}`,
          text: row.status || '未知'
        })
      },
      { label: '证据', node: materialsTextCell(row.evidence) }
    ];
  });
  return materialsBlock('硬条件与待确认', [
    materialsTable('jobs-materials-table--conditions', ['条件', '状态', '证据'], rows)
  ]);
}

function materialsUnknownBlock(materials) {
  if (!materials.unknownFields.length) return materialsEmptyBlock('未知字段');
  return materialsBlock('未知字段', [
    el('ul', { className: 'jobs-materials-unknown' }, materials.unknownFields.map((field) => (
      el('li', { text: field })
    )))
  ]);
}

function materialsResumeBlock(materials) {
  if (!materials.resumeSuggestions.length) return materialsEmptyBlock('简历建议');
  const rows = materials.resumeSuggestions.map((row) => [
    { label: '原文', node: materialsTextCell(row.original) },
    {
      label: '建议',
      node: el('div', { className: 'jobs-materials-suggestion' }, [
        materialsTextCell(row.suggested),
        materialsNote([row.evidence ? `依据：${row.evidence}` : null, row.reason ? `理由：${row.reason}` : null])
      ].filter(Boolean))
    }
  ]);
  return materialsBlock('简历建议', [
    materialsTable('jobs-materials-table--resume', ['简历原文', '建议改法'], rows)
  ]);
}

function materialsGreetingsBlock(job, materials) {
  const options = MATERIALS_GREETING_VARIANTS.filter((variant) => materials.greetings[variant.key]);
  if (!options.length) return materialsEmptyBlock('招呼语');
  const fieldName = `jobs-materials-greeting-${String((job && job.id) || 'job')}`;
  const radios = el('div', {
    className: 'jobs-materials-greeting-options',
    attrs: { role: 'radiogroup', 'aria-label': '招呼语版本' }
  });
  const preview = el('p', { className: 'jobs-materials-greeting-text' });
  const meta = el('p', { className: 'jobs-materials-greeting-meta' });
  const labels = [];
  const select = (key) => {
    const variant = options.find((item) => item.key === key) || options[0];
    preview.textContent = materials.greetings[variant.key] || '未知';
    preview.dataset.variant = variant.key;
    // 与队列卡片的「来源：…」共用同一套标注，不发送、不写入。
    meta.textContent = `来源：${variant.label}`;
    labels.forEach(({ input, label }) => {
      const active = input.value === variant.key;
      label.classList.toggle('is-active', active);
      input.checked = active;
    });
  };
  options.forEach((variant) => {
    const id = `${fieldName}-${variant.key}`;
    const input = el('input', { attrs: { type: 'radio', name: fieldName, id, value: variant.key } });
    const label = el('label', { className: 'jobs-materials-greeting-option', attrs: { for: id } });
    label.append(input);
    label.append(el('span', { text: variant.label }));
    input.addEventListener('change', () => {
      if (input.checked) select(variant.key);
    });
    labels.push({ input, label });
    radios.append(label);
  });
  select(materials.selected || options[0].key);
  return materialsBlock('招呼语（三版择一）', [radios, preview, meta]);
}

function materialsConfirmBlock(materials) {
  if (!materials.confirmItems.length) return materialsEmptyBlock('确认事项');
  return materialsBlock('确认事项', [
    el('ul', { className: 'jobs-materials-confirm' }, materials.confirmItems.map((item) => (
      el('li', { text: item })
    )))
  ]);
}

function dossierMaterialsSection(job) {
  const materials = materialsOf(job);
  if (!materials) {
    return dossierSection('定制材料', [
      el('p', {
        className: 'jobs-materials-empty',
        text: '尚未生成定制材料。在审批队列勾选已确认岗位后点「生成招呼语」。'
      })
    ]);
  }
  return dossierSection('定制材料', [
    el('div', { className: 'jobs-materials' }, [
      materialsMappingBlock(materials),
      materialsConditionsBlock(materials),
      materialsUnknownBlock(materials),
      materialsResumeBlock(materials),
      materialsGreetingsBlock(job, materials),
      materialsConfirmBlock(materials)
    ])
  ]);
}

function dossierSections(job) {
  const parts = dossierParts(job);
  return [
    dossierStandardSection(job),
    dossierMatchSection(job),
    dossierTraceSection(job),
    dossierMaterialsSection(job),
    dossierSectionText('简历改动', parts.resume),
    dossierSectionText('招呼语（确认前原文）', parts.greeting, 'jobs-dossier-greeting'),
    dossierGreetingEvidenceSection(job),
    dossierSectionList('剩余不确定项', parts.checklist),
    dossierSectionText('建议动作', parts.action)
  ];
}

function renderDossier(container, job) {
  if (!container) return;
  clear(container);
  if (!job) {
    container.append(el('p', { className: 'jobs-dossier-empty', text: '未知' }));
    return;
  }
  container.append(el('div', { className: 'jobs-dossier-meta' }, [
    el('strong', { className: 'jobs-dossier-job', text: String(job.company || '未知公司') }),
    el('span', { className: 'jobs-dossier-role', text: String(job.title || '未知岗位') })
  ]));
  dossierSections(job).forEach((section) => container.append(section));
}

// 详情与核对改为右侧抽屉（CSS fixed）：不移动 DOM，不滚动整页；
// 打开时把焦点放进抽屉，关闭时还给触发的按钮。
function openJobDossier(job, trigger) {
  state.jobsDossierId = String(job.id);
  if (!dom.jobsDossier || !dom.jobsDossierBody) return;
  state.jobsDossierTrigger = trigger || document.activeElement;
  dom.jobsDossier.hidden = false;
  renderDossier(dom.jobsDossierBody, job);
  dom.jobsDossier.setAttribute('tabindex', '-1');
  dom.jobsDossier.focus({ preventScroll: true });
}

function closeJobDossier() {
  const trigger = state.jobsDossierTrigger;
  state.jobsDossierTrigger = null;
  state.jobsDossierId = null;
  if (dom.jobsDossier) dom.jobsDossier.hidden = true;
  clear(dom.jobsDossierBody);
  if (trigger && typeof trigger.focus === 'function' && document.contains(trigger)) {
    trigger.focus();
  }
}

function openQueueReview(snapshot, row, trigger) {
  state.queueReviewId = String(row.id);
  const job = queueReviewJob(snapshot, row.id) || row;
  if (!dom.queueReview || !dom.queueReviewBody) return;
  state.queueReviewTrigger = trigger || document.activeElement;
  dom.queueReview.hidden = false;
  renderDossier(dom.queueReviewBody, job);
  dom.queueReview.setAttribute('tabindex', '-1');
  dom.queueReview.focus({ preventScroll: true });
}

function closeQueueReview() {
  const trigger = state.queueReviewTrigger;
  state.queueReviewTrigger = null;
  state.queueReviewId = null;
  if (dom.queueReview) dom.queueReview.hidden = true;
  clear(dom.queueReviewBody);
  if (trigger && typeof trigger.focus === 'function' && document.contains(trigger)) {
    trigger.focus();
  }
}

function syncJobsSelection(jobs) {
  const total = jobs.length;
  const selected = jobs.filter((job) => state.jobsSelection.has(String(job.id))).length;
  // 切换筛选后，已选但当前不可见的岗位仍保留在选择里；把数量显式告诉用户。
  const visibleIds = new Set(jobs.map((job) => String(job.id)));
  const hidden = Array.from(state.jobsSelection).filter((id) => !visibleIds.has(id)).length;
  if (dom.jobsSelectionCount) {
    dom.jobsSelectionCount.textContent = hidden
      ? `已选 ${selected} 条（另有 ${hidden} 条已选未显示）`
      : `已选 ${selected} 条`;
  }
  if (dom.jobsSelectAll) {
    dom.jobsSelectAll.checked = total > 0 && selected === total;
    dom.jobsSelectAll.indeterminate = selected > 0 && selected < total;
    dom.jobsSelectAll.disabled = total === 0;
  }
  if (dom.jobsBulkEnqueue) {
    dom.jobsBulkEnqueue.disabled = selected === 0;
    dom.jobsBulkEnqueue.textContent = selected > 1 ? `加入审批队列（${selected}）` : '加入审批队列';
  }
  if (dom.jobsBulkDelete) {
    dom.jobsBulkDelete.disabled = selected === 0;
    dom.jobsBulkDelete.textContent = selected > 1 ? `删除所选（${selected}）` : '删除所选';
  }
}

/* Structured personal profile */

const PROFILE_LIST_CONFIG = {
  education: {
    title: '教育经历',
    fields: [
      { key: 'school', label: '学校', placeholder: '学校名称' },
      { key: 'major', label: '专业', placeholder: '专业名称' },
      { key: 'degree', label: '学历', type: 'select', options: ['', '大专', '本科', '硕士', '博士', '其他'] },
      { key: 'start', label: '开始', placeholder: '2018-09' },
      { key: 'end', label: '结束', placeholder: '2022-06' },
      { key: 'summary', label: '补充说明', type: 'textarea', full: true }
    ]
  },
  experiences: {
    title: '工作经历',
    fields: [
      { key: 'company', label: '公司', placeholder: '公司名称' },
      { key: 'title', label: '职位', placeholder: '岗位名称' },
      { key: 'start', label: '开始', placeholder: '2021-07' },
      { key: 'end', label: '结束', placeholder: '2022-05' },
      { key: 'summary', label: '做了什么（只写可核实事实）', type: 'textarea', full: true }
    ]
  },
  projects: {
    title: '项目经历',
    fields: [
      { key: 'name', label: '项目名', placeholder: '项目名称' },
      { key: 'role', label: '角色', placeholder: '你的角色' },
      { key: 'start', label: '开始', placeholder: '2021-09' },
      { key: 'end', label: '结束', placeholder: '2022-03' },
      { key: 'summary', label: '项目说明（只写可核实事实）', type: 'textarea', full: true }
    ]
  }
};

function profileListContainer(kind) {
  if (kind === 'education') return dom.profileEducation;
  if (kind === 'experiences') return dom.profileExperiences;
  if (kind === 'projects') return dom.profileProjects;
  return null;
}

function splitList(value) {
  return String(value || '')
    .split(/[,，、;；\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function profileFieldNode(field, value) {
  const wrap = el('div', { className: `form-field${field.full ? ' full' : ''}` });
  wrap.append(el('label', { text: field.label }));
  let input;
  if (field.type === 'select') {
    input = el('select');
    field.options.forEach((option) => {
      input.append(el('option', { text: option || '未选择', attrs: { value: option } }));
    });
    input.value = String(value || '');
  } else if (field.type === 'textarea') {
    input = el('textarea', { attrs: { rows: '2', placeholder: field.placeholder || '' } });
    input.value = String(value || '');
  } else {
    input = el('input', { attrs: { type: 'text', placeholder: field.placeholder || '', autocomplete: 'off' } });
    input.value = String(value || '');
  }
  input.dataset.field = field.key;
  wrap.append(input);
  return wrap;
}

function renumberProfileRows(kind) {
  const container = profileListContainer(kind);
  if (!container) return;
  const config = PROFILE_LIST_CONFIG[kind];
  Array.from(container.querySelectorAll('.profile-item')).forEach((item, index) => {
    const title = item.querySelector('.profile-item-title');
    if (title) title.textContent = `${config.title} ${index + 1}`;
  });
}

function addProfileRow(kind, row = {}, markDirty = true) {
  const container = profileListContainer(kind);
  const config = PROFILE_LIST_CONFIG[kind];
  if (!container || !config) return;
  const empty = container.querySelector('[data-profile-empty]');
  if (empty) empty.remove();
  const item = el('div', { className: 'profile-item' });
  const remove = el('button', {
    className: 'button button-quiet button-small',
    text: '删除',
    attrs: { type: 'button' }
  });
  remove.addEventListener('click', () => {
    item.remove();
    renumberProfileRows(kind);
    if (!container.querySelector('.profile-item')) renderProfileList(kind, []);
    state.profileDirty = true;
    renderProfile(state.snapshot && state.snapshot.profile);
  });
  const head = el('div', { className: 'profile-item-head' }, [
    el('strong', { className: 'profile-item-title', text: config.title }),
    remove
  ]);
  item.append(head);
  const grid = el('div', { className: 'form-grid profile-item-grid' });
  config.fields.forEach((field) => grid.append(profileFieldNode(field, row[field.key])));
  item.append(grid);
  container.append(item);
  renumberProfileRows(kind);
  if (markDirty) {
    state.profileDirty = true;
    renderProfile(state.snapshot && state.snapshot.profile);
  }
}

function renderProfileList(kind, rows) {
  const container = profileListContainer(kind);
  if (!container) return;
  clear(container);
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    container.append(el('p', {
      className: 'hint',
      text: `暂无${PROFILE_LIST_CONFIG[kind].title}；点击下方按钮添加。`,
      attrs: { 'data-profile-empty': '1' }
    }));
    return;
  }
  list.forEach((row) => addProfileRow(kind, row, false));
}

/* 左侧分节导航：每节只显示必填是否完成，规则来自后端 completeness.required。 */
const SG_PROFILE_NAV_SECTIONS = [
  { id: 'sg-profile-sec-basic', label: '基本信息', keys: ['basic_name', 'basic_city'] },
  { id: 'sg-profile-sec-intent', label: '求职偏好', keys: ['job_intent_titles', 'job_intent_cities'] },
  { id: 'sg-profile-sec-education', label: '教育', keys: ['education'] },
  { id: 'sg-profile-sec-experiences', label: '经历', keys: ['experience_or_project'] },
  { id: 'sg-profile-sec-projects', label: '项目', keys: ['experience_or_project'] },
  { id: 'sg-profile-sec-skills', label: '技能', keys: ['skills'] },
  { id: 'sg-profile-sec-summary', label: '简介', keys: ['summary'] },
  { id: 'sg-profile-sec-truth', label: '确认', keys: ['truth_confirmed'] }
];

function renderProfileNav(completeness) {
  const list = document.getElementById('sg-profile-nav-list');
  if (!list) return;
  const data = completeness && typeof completeness === 'object' ? completeness : {};
  const required = Array.isArray(data.required) ? data.required : [];
  const doneByKey = {};
  required.forEach((item) => {
    if (item && item.key) doneByKey[item.key] = item.done === true;
  });
  clear(list);
  SG_PROFILE_NAV_SECTIONS.forEach((section) => {
    const done = section.keys.every((key) => doneByKey[key] === true);
    const stateLabel = done ? '✓' : '缺';
    const button = el('button', {
      className: `sg-profile-nav-item${done ? ' is-done' : ''}`,
      attrs: {
        type: 'button',
        'data-sg-profile-target': section.id,
        'aria-label': `${section.label}，必填${done ? '已完成' : '未完成'}；跳到这一节`
      }
    }, [
      el('span', { className: 'sg-profile-nav-label', text: section.label }),
      el('span', { className: 'sg-profile-nav-state', text: stateLabel })
    ]);
    button.addEventListener('click', () => {
      const target = document.getElementById(section.id);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    list.append(button);
  });
}

function renderProfileMeter(completeness) {
  if (!dom.profileMeter) return;
  const data = completeness && typeof completeness === 'object' ? completeness : {};
  renderProfileNav(data);
  if (!Number.isFinite(Number(data.percent)) && state.profileDirty) {
    clear(dom.profileMeter);
    dom.profileMeter.append(el('p', {
      className: 'profile-meter-text',
      text: '已填入建议字段；核对并保存后会重新计算完整度。'
    }));
    return;
  }
  const percent = Number.isFinite(Number(data.percent)) ? Number(data.percent) : 0;
  const sections = Array.isArray(data.sections) ? data.sections : [];
  clear(dom.profileMeter);
  const progress = el('div', { className: 'sg-profile-progress' });
  const value = el('p', { className: 'sg-profile-progress-value' });
  value.append(document.createTextNode(String(percent)), el('small', { text: '%' }));
  const body = el('div', { className: 'sg-profile-progress-body' });
  const bar = el('div', { className: 'profile-meter-bar', attrs: { role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(percent), 'aria-label': '资料完整度' } });
  const fill = el('span');
  fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  bar.append(fill);
  body.append(bar);
  const missing = Array.isArray(data.missing) ? data.missing : [];
  body.append(el('p', {
    className: 'profile-meter-text',
    text: state.profileDirty
      ? `当前显示已保存资料的完整度 ${percent}%；页面有未保存修改，保存后更新。`
      : missing.length
        ? `完整度 ${percent}%，还缺：${missing.join('、')}`
        : `完整度 ${percent}%，资料齐全，可以生成草稿。`
  }));
  progress.append(value, body);
  dom.profileMeter.append(progress);
  if (sections.length) {
    const chips = el('div', { className: 'chip-row' });
    sections.forEach((section) => {
      // 走查第 5 条：chip 旁直接渲染后端给的 sections[].hint，不用悬停才能看到。
      const item = el('span', { className: 'sg-profile-chip-item' });
      item.append(el('span', {
        className: `chip profile-chip${section.done ? ' is-done' : ''}`,
        text: `${section.done ? '✓' : '缺'} ${section.label}`
      }));
      if (section.hint) item.append(el('span', { className: 'sg-profile-chip-hint', text: section.hint }));
      chips.append(item);
    });
    dom.profileMeter.append(chips);
  }
  const requiredMissing = Array.isArray(data.required_missing) ? data.required_missing : [];
  if (!state.profileDirty && requiredMissing.length) {
    dom.profileMeter.append(el('p', {
      className: 'profile-meter-text profile-meter-required',
      text: `还缺少必填项，暂时无法启动「采集」/「完整流程」：${requiredMissing.join('、')}`
    }));
  }
}

/* 首次导入：user 模式下尚未保存过资料、但本机有可读简历时，自动预填一次草稿（只预填，不保存）。 */
function profileCountPrefilled(profile) {
  const basic = profile.basic || {};
  const skills = profile.skills || {};
  const basicCount = ['name', 'email', 'phone', 'city'].filter((key) => basic[key]).length;
  const rowCount = (profile.education || []).length + (profile.experiences || []).length + (profile.projects || []).length;
  const skillCount = (skills.tools || []).length ? 1 : 0;
  const summaryCount = profile.summary ? 1 : 0;
  return basicCount + rowCount + skillCount + summaryCount;
}

function renderProfileDraftBanner() {
  const banner = dom.profileDraftBanner;
  if (!banner) return;
  const showing = state.profileDirty && state.profilePrefillCount > 0;
  banner.hidden = !showing;
  if (!showing) {
    clear(banner);
    return;
  }
  clear(banner);
  banner.append(el('strong', {
    text: `已按你的简历预填了 ${state.profilePrefillCount} 项，请核对后点「保存」；现在还是草稿，离开页面就会丢失。`
  }));
}

function profileShouldAutoPrefill(profile) {
  return profile.saved === false
    && profile.cv_available === true
    && !state.profileAutoPrefillTried;
}

/* 进入个人资料页时调用：只在快照确认「未保存过 + 可读简历」时预填一次。 */
function maybeAutoPrefillProfile() {
  const profile = state.snapshot && state.snapshot.profile;
  if (!profile || state.profileDirty || !profileShouldAutoPrefill(profile)) return;
  autoPrefillProfileFromCv();
}

async function autoPrefillProfileFromCv() {
  state.profileAutoPrefillTried = true;
  if (!dom.profileImport) return;
  const data = await postAction('import-profile-cv').catch((error) => ({ ok: false, message: friendlyError(error) }));
  if (!data || data.ok === false) {
    // A missing or unreadable resume is not an error for the user here; the form simply stays empty.
    if (data && data.message) setStatus(data.message, 'warn');
    return;
  }
  // The form is empty before this point (saved=false), so overwriting needs no confirmation.
  populateProfileForm(data.profile);
  state.profileDirty = true;
  state.profilePrefillCount = profileCountPrefilled(data.profile);
  renderProfile(data.profile);
  showInline(dom.profileResult, `已按你的简历预填了 ${state.profilePrefillCount} 项，请核对后保存。`, 'ok');
}

function renderProfile(profile) {
  if (!dom.profileForm || !profile || typeof profile !== 'object') return;
  if (!state.profileDirty) populateProfileForm(profile);
  const completeness = profile.completeness || {};
  renderProfileMeter(completeness);
  renderProfileDraftBanner();
  if (dom.profileSave) dom.profileSave.classList.toggle('button-draft', state.profileDirty);
  // The snapshot can arrive after the user already opened this page; retry the one-time prefill then.
  const profilePanel = document.querySelector('[data-view-panel="profile"]');
  if (profilePanel && !profilePanel.hidden) maybeAutoPrefillProfile();
  if (dom.profileBadge) {
    const level = completeness.level || 'empty';
    dom.profileBadge.textContent = state.profileDirty
      ? '有未保存修改'
      : level === 'ready'
        ? '可用于草稿'
        : level === 'empty'
          ? '未填写'
          : `完整度 ${completeness.percent || 0}%`;
    dom.profileBadge.className = `badge ${level === 'ready' && !state.profileDirty ? 'badge-good' : 'badge-neutral'}`;
  }
  if (dom.profileImport) {
    dom.profileImport.title = '读取本机 workspace/resume.md 并填入可识别字段';
  }
}

function populateProfileForm(profile) {
  const basic = profile.basic || {};
  const intent = profile.job_intent || {};
  const skills = profile.skills || {};
  dom.profileName.value = basic.name || '';
  dom.profileCity.value = basic.city || '';
  dom.profileEmail.value = basic.email || '';
  dom.profilePhone.value = basic.phone || '';
  dom.profileWechat.value = basic.wechat || '';
  dom.profileLinks.value = basic.links || '';
  dom.profileTitles.value = (intent.titles || []).join(', ');
  dom.profileTargetCities.value = (intent.cities || []).join(', ');
  dom.profileSalaryMin.value = intent.salary_min === null || intent.salary_min === undefined ? '' : String(intent.salary_min);
  dom.profileSalaryMax.value = intent.salary_max === null || intent.salary_max === undefined ? '' : String(intent.salary_max);
  dom.profileJobType.value = intent.job_type || '全职';
  dom.profileAvailability.value = intent.availability || '';
  dom.profileTools.value = (skills.tools || []).join(', ');
  dom.profileStrengths.value = (skills.strengths || []).join(', ');
  dom.profileSummary.value = profile.summary || '';
  dom.profileExcluded.value = (profile.excluded_terms || []).join(', ');
  dom.profileTruth.checked = profile.truth_confirmed === true;
  renderProfileList('education', profile.education);
  renderProfileList('experiences', profile.experiences);
  renderProfileList('projects', profile.projects);
  state.profileDirty = false;
}

function collectProfileList(kind) {
  const container = profileListContainer(kind);
  if (!container) return [];
  return Array.from(container.querySelectorAll('.profile-item')).map((item) => {
    const row = {};
    item.querySelectorAll('[data-field]').forEach((input) => {
      row[input.dataset.field] = String(input.value || '').trim();
    });
    return row;
  }).filter((row) => Object.values(row).some(Boolean));
}

function collectProfileForm() {
  return {
    basic: {
      name: dom.profileName.value.trim(),
      city: dom.profileCity.value.trim(),
      email: dom.profileEmail.value.trim(),
      phone: dom.profilePhone.value.trim(),
      wechat: dom.profileWechat.value.trim(),
      links: dom.profileLinks.value.trim()
    },
    job_intent: {
      titles: splitList(dom.profileTitles.value),
      cities: splitList(dom.profileTargetCities.value),
      salary_min: dom.profileSalaryMin.value === '' ? null : Number(dom.profileSalaryMin.value),
      salary_max: dom.profileSalaryMax.value === '' ? null : Number(dom.profileSalaryMax.value),
      job_type: dom.profileJobType.value,
      availability: dom.profileAvailability.value.trim()
    },
    skills: {
      tools: splitList(dom.profileTools.value),
      strengths: splitList(dom.profileStrengths.value)
    },
    education: collectProfileList('education'),
    experiences: collectProfileList('experiences'),
    projects: collectProfileList('projects'),
    summary: dom.profileSummary.value.trim(),
    excluded_terms: splitList(dom.profileExcluded.value),
    truth_confirmed: dom.profileTruth.checked
  };
}

async function saveProfileForm(event) {
  event.preventDefault();
  const profile = collectProfileForm();
  const data = await runAction(dom.profileSave, () => postAction('save-profile', { profile }));
  if (!data) return;
  if (data.ok === false) {
    setStatus(data.message || '个人资料未保存。', 'error');
    showInline(dom.profileResult, data.message || '个人资料未保存。', 'error');
    return;
  }
  state.profileDirty = false;
  state.profilePrefillCount = 0;
  populateProfileForm(data.profile);
  renderProfileMeter(data.profile.completeness);
  showInline(dom.profileResult, data.message || '个人资料已保存到本机。', 'ok');
  setStatus(data.message || '个人资料已保存到本机。', 'ok');
  await loadState();
}

function chooseProfileCv() {
  if (state.profileImportBusy || !dom.profileImportFile) return;
  dom.profileImportFile.value = '';
  dom.profileImportFile.click();
}

async function importProfileFromCv(file) {
  if (!file || !file.name || state.profileImportBusy) return;
  if (!/\.(pdf|docx|md|txt)$/i.test(file.name) || file.size > 5 * 1024 * 1024 || file.size === 0) {
    showInline(dom.profileResult, '请选择非空的 PDF、DOCX、MD 或 TXT 文件，最大 5 MB。', 'error');
    return;
  }
  if (state.profileDirty && !window.confirm('导入会用识别结果更新资料、教育和经历；没识别到的部分保持不变。继续吗？')) return;
  state.profileImportBusy = true;
  dom.profileImport.disabled = true;
  dom.profileImport.setAttribute('aria-busy', 'true');
  dom.profileDrop.setAttribute('aria-disabled', 'true');
  dom.profileSave.disabled = true;
  dom.profileImportPreview.hidden = true;
  dom.profileImportText.textContent = '';
  try {
    showInline(dom.profileResult, '正在读取简历文件…', 'info');
    const contentBase64 = await readFileAsBase64(file);
    showInline(dom.profileResult, '正在解析整份简历，包括教育、工作和项目经历，请稍候…', 'info');
    const data = await postAction('import-profile-cv', { filename: file.name, content_base64: contentBase64 });
    if (data.ok === false) throw new Error(data.message || '简历导入失败，请重新选择。');
    const profile = collectProfileForm();
    const suggested = data.profile || {};
    Object.entries(suggested.basic || {}).forEach(([key, value]) => {
      if (value) profile.basic[key] = value;
    });
    profile.skills.tools = [...new Set([...profile.skills.tools, ...(suggested.skills?.tools || [])])];
    profile.skills.strengths = [...new Set([...profile.skills.strengths, ...(suggested.skills?.strengths || [])])];
    ['education', 'experiences', 'projects'].forEach((key) => {
      if (suggested[key]?.length) profile[key] = suggested[key];
    });
    ['titles', 'cities', 'availability'].forEach((key) => {
      if (suggested.job_intent?.[key]?.length) profile.job_intent[key] = suggested.job_intent[key];
    });
    if (suggested.summary) profile.summary = suggested.summary;
    profile.truth_confirmed = false;
    populateProfileForm(profile);
    state.profileDirty = true;
    state.profilePrefillCount = profileCountPrefilled(profile);
    renderProfile(profile);
    dom.profileImportText.textContent = data.source_text || '';
    dom.profileImportPreview.hidden = !data.source_text;
    const counts = `教育 ${suggested.education?.length || 0} 条，工作/实习 ${suggested.experiences?.length || 0} 条，项目 ${suggested.projects?.length || 0} 条。`;
    showInline(dom.profileResult, [data.message, counts, ...(data.warnings || [])].join('\n'), data.warnings?.length ? 'warn' : 'ok');
    setStatus('简历已解析，请核对并确认真实性后保存。', 'ok');
  } catch (error) {
    showInline(dom.profileResult, friendlyError(error), 'error');
    setStatus(friendlyError(error), 'error');
  } finally {
    state.profileImportBusy = false;
    dom.profileImport.disabled = false;
    dom.profileImport.removeAttribute('aria-busy');
    dom.profileDrop.setAttribute('aria-disabled', 'false');
    dom.profileSave.disabled = false;
  }
}

/* Drag-and-drop for resume inputs: profile import, collect scoring resume, ATS PDF check. */
function bindResumeDrops() {
  const zones = [
    ['profile-resume-drop', dom.profileImportFile, () => state.profileImportBusy],
    ['collect-resume-drop', dom.collectResumeFile, () => Boolean(dom.collectResumeUpload && dom.collectResumeUpload.disabled)],
    ['ats-resume-drop', dom.atsFile, () => Boolean(dom.atsSubmit && dom.atsSubmit.disabled)]
  ];
  const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes('Files');
  zones.forEach(([id, input, disabled]) => {
    const zone = document.getElementById(id);
    if (!zone || !input) return;
    const status = zone.querySelector('.resume-drop-status');
    const say = (text) => { if (status) status.textContent = text; };
    input.addEventListener('change', () => {
      if (input.files[0]) say(`已选择：${input.files[0].name}`);
    });
    zone.addEventListener('dragover', (event) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = disabled() ? 'none' : 'copy';
      zone.classList.toggle('is-dragging', !disabled());
    });
    zone.addEventListener('dragleave', (event) => {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove('is-dragging');
    });
    zone.addEventListener('drop', (event) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      zone.classList.remove('is-dragging');
      if (disabled()) {
        say('正在处理文件，请稍候再拖入。');
        return;
      }
      const files = event.dataTransfer.files;
      if (files.length !== 1) {
        say('请一次拖入一份简历文件。');
        return;
      }
      const file = files[0];
      const suffixes = input.accept.split(',').filter((value) => value.startsWith('.'));
      if (!suffixes.some((suffix) => file.name.toLowerCase().endsWith(suffix)) || !file.size || file.size > 5 * 1024 * 1024) {
        say(`请选择非空的 ${suffixes.join(' / ')} 文件，最大 5 MB。`);
        return;
      }
      const selected = new DataTransfer();
      selected.items.add(file);
      input.files = selected.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
  ['dragover', 'drop'].forEach((type) => document.addEventListener(type, (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    if (type === 'drop' && !event.target.closest('.resume-dropzone')) setStatus('请将简历拖入对应的简历导入区域。', 'warn');
  }));
  if (dom.profileDrop) {
    dom.profileDrop.addEventListener('click', chooseProfileCv);
    dom.profileDrop.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        chooseProfileCv();
      }
    });
  }
  if (dom.profileImportFile) {
    dom.profileImportFile.addEventListener('change', () => importProfileFromCv(dom.profileImportFile.files[0]));
  }
}

/* OfferPilot bridge: status, controlled start/stop, read-only job snapshot */

function compactValue(value) {
  if (value === undefined || value === null || value === '') return '—';
  if (Array.isArray(value)) return value.map(compactValue).join('、');
  if (typeof value === 'object') {
    return Object.keys(value).slice(0, 8).map((key) => `${key} ${compactValue(value[key])}`).join(' / ');
  }
  return String(value);
}

function offerpilotMetaRow(label, value) {
  const dd = el('dd');
  if (value instanceof Node) dd.append(value);
  else dd.textContent = value === undefined || value === null || value === '' ? '—' : String(value);
  return el('div', {}, [el('dt', { text: label }), dd]);
}

function offerpilotTaskStatusNode(status) {
  const text = OFFERPILOT_TASK_STATUS_LABELS[status] || status || '未知';
  const kind = ['running', 'queued', 'pending'].includes(status)
    ? 'badge-good'
    : ['failed', 'stopped'].includes(status)
      ? 'badge-bad'
      : 'badge-neutral';
  return el('span', { className: `badge ${kind}`, text });
}

function renderOfferPilotTask(task, lastTask) {
  const container = dom.offerpilotTask;
  if (!container) return;
  clear(container);
  const current = task && typeof task === 'object' ? task : null;
  const previous = lastTask && typeof lastTask === 'object' ? lastTask : null;
  const row = current || previous;
  if (!row) {
    container.append(el('p', { className: 'hint', text: '还没有任务记录。采集组件就绪后，可以在这里启动。' }));
    return;
  }
  if (!current && previous) {
    container.append(el('p', { className: 'hint', text: '现在没有运行中的任务；下面是最近一次的结果。' }));
  }
  const line = el('div', { className: 'offerpilot-task-line' });
  line.append(el('strong', { text: OFFERPILOT_MODE_LABELS[row.mode] || row.mode || '任务' }));
  line.append(offerpilotTaskStatusNode(String(row.status || '')));
  if (row.id) line.append(el('span', { className: 'cell-mono', text: String(row.id) }));
  container.append(line);
  const meta = el('dl', { className: 'integration-meta' });
  meta.append(offerpilotMetaRow('创建时间', formatDateTime(row.created_at)));
  meta.append(offerpilotMetaRow('更新时间', formatDateTime(row.updated_at)));
  if (row.deadline_at) meta.append(offerpilotMetaRow('截止时间', formatDateTime(row.deadline_at)));
  meta.append(offerpilotMetaRow('已请求停止', row.stop_requested ? '是' : '否'));
  container.append(meta);
  if (current && row.id && ['running', 'stopping', 'queued', 'pending'].includes(String(row.status || ''))) {
    const stop = el('button', {
      className: 'button button-quiet button-small',
      text: row.stop_requested ? '正在停止…' : '停止任务',
      attrs: { type: 'button' }
    });
    stop.disabled = Boolean(row.stop_requested) || String(row.status) === 'stopping';
    stop.addEventListener('click', () => stopOfferPilotTask(String(row.id), stop));
    container.append(el('p', { className: 'form-actions' }, [stop]));
  }
}

function splitTextList(value) {
  return String(value || '')
    .replace(/，/g, ',')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function collectMode() {
  return dom.offerpilotMode ? dom.offerpilotMode.value : 'collect';
}

function collectNeedsSearch(mode) {
  return mode === 'collect' || mode === 'full';
}

// 采集平台：四个平台都能单独采集；「完整流程」会进入投递，目前只有 Boss 直聘开放投递，所以锁定 Boss。
const COLLECT_PLATFORMS = ['boss', 'zhilian', '51job', 'liepin'];

function collectPlatform() {
  if (collectMode() === 'full') return 'boss';
  const value = dom.collectPlatform ? dom.collectPlatform.value : 'boss';
  return COLLECT_PLATFORMS.includes(value) ? value : 'boss';
}

function collectPlatformLabel(platform) {
  return CHANNEL_LABELS[platform] || platform;
}

/* 采集页「本次初筛条件」：只读展示个人资料里的求职意向，并给空输入框提供默认值。 */

function collectProfileIntent() {
  const profile = state.snapshot && state.snapshot.profile;
  const intent = profile && typeof profile.job_intent === 'object' && profile.job_intent ? profile.job_intent : {};
  const list = (value) => (Array.isArray(value) ? value.map((item) => String(item).trim()).filter(Boolean) : []);
  const amount = (value) => {
    const number = Number(value);
    return value === null || value === undefined || value === '' || !Number.isFinite(number) || number <= 0 ? null : number;
  };
  return {
    titles: list(intent.titles),
    cities: list(intent.cities),
    salaryMin: amount(intent.salary_min),
    salaryMax: amount(intent.salary_max),
    jobType: String(intent.job_type || '').trim()
  };
}

function collectSalaryText(intent) {
  if (intent.salaryMin !== null && intent.salaryMax !== null) return `${intent.salaryMin}–${intent.salaryMax} 元/月`;
  if (intent.salaryMin !== null) return `不低于 ${intent.salaryMin} 元/月`;
  if (intent.salaryMax !== null) return `不高于 ${intent.salaryMax} 元/月`;
  return '未设置';
}

function renderCollectCriteria() {
  const intent = collectProfileIntent();
  if (dom.collectKeywords) {
    dom.collectKeywords.placeholder = intent.titles.length ? intent.titles.slice(0, 10).join(', ') : '产品经理, AI产品经理';
  }
  if (dom.collectCities) {
    dom.collectCities.placeholder = intent.cities.length ? intent.cities.slice(0, 5).join(', ') : '北京';
  }
  if (dom.collectCriteria) {
    clear(dom.collectCriteria);
    dom.collectCriteria.append(offerpilotMetaRow('求职类型', intent.jobType || '未设置'));
    dom.collectCriteria.append(offerpilotMetaRow('期望月薪', collectSalaryText(intent)));
    dom.collectCriteria.append(offerpilotMetaRow('目标城市', intent.cities.length ? intent.cities.join('、') : '未设置'));
    dom.collectCriteria.append(offerpilotMetaRow('目标岗位', intent.titles.length ? intent.titles.join('、') : '未设置'));
  }
  if (dom.collectCriteriaHint) {
    const incomplete = !intent.jobType || (intent.salaryMin === null && intent.salaryMax === null);
    dom.collectCriteriaHint.hidden = !incomplete;
    dom.collectCriteriaHint.textContent = incomplete ? '去个人资料补全求职类型和期望月薪后，初筛会更准；不补全也可以直接开始采集。' : '';
  }
}

/* 输入框为空时回退到个人资料的目标岗位/城市；用户已输入的内容永远优先。 */
function collectEffectiveList(input, fallback, limit) {
  const typed = splitTextList(input && input.value);
  return typed.length ? typed : fallback.slice(0, limit);
}

function collectFormKey() {
  const mode = collectMode();
  if (!collectNeedsSearch(mode)) return mode;
  const intent = collectProfileIntent();
  return [
    mode,
    collectPlatform(),
    collectEffectiveList(dom.collectKeywords, intent.titles, 10).join(','),
    collectEffectiveList(dom.collectCities, intent.cities, 5).join(','),
    dom.collectPages ? dom.collectPages.value.trim() : '',
    dom.collectPace ? dom.collectPace.value : 'cautious',
    dom.collectAutoScore && dom.collectAutoScore.checked ? '1' : '0'
  ].join('|');
}

function buildOfferPilotOptions(silent = false) {
  const intent = collectProfileIntent();
  const keywords = collectEffectiveList(dom.collectKeywords, intent.titles, 10);
  const cities = collectEffectiveList(dom.collectCities, intent.cities, 5);
  const pages = Number(dom.collectPages && dom.collectPages.value);
  if (!keywords.length) {
    if (!silent) setStatus('请至少填写一个搜索关键词。', 'error');
    return null;
  }
  if (!cities.length) {
    if (!silent) setStatus('请至少填写一个城市。', 'error');
    return null;
  }
  if (!Number.isInteger(pages) || pages < 1 || pages > 10) {
    if (!silent) setStatus('每个关键词的页数必须是 1–10 的整数。', 'error');
    return null;
  }
  return {
    platform: collectPlatform(),
    keywords,
    cities,
    max_pages: pages,
    auto_score: Boolean(dom.collectAutoScore && dom.collectAutoScore.checked),
    pace: dom.collectPace && OFFERPILOT_PACE[dom.collectPace.value] ? dom.collectPace.value : 'cautious'
  };
}

function renderCollectSummary() {
  if (!dom.collectSummary) return;
  const mode = collectMode();
  const options = collectNeedsSearch(mode) ? buildOfferPilotOptions(true) : null;
  let text = OFFERPILOT_MODE_HINTS[mode] || '';
  if (collectNeedsSearch(mode)) {
    if (!options) {
      text += ' 填写关键词和城市后，这里会显示本次采集范围。';
    } else {
      const pace = OFFERPILOT_PACE[options.pace] || OFFERPILOT_PACE.cautious;
      const low = (2 * pace.multiplier).toFixed(1);
      const high = (5 * pace.multiplier).toFixed(1);
      text += ` 将在 ${collectPlatformLabel(options.platform)} 搜索「${options.keywords.join('、')}」，城市「${options.cities.join('、')}」，每个关键词最多 ${options.max_pages} 页。`;
      text += ` 节奏「${pace.label}」：每次翻页/读详情前随机等待 ${low}–${high} 秒。`;
      text += ' 采集后会按你的简历自动评分。';
    }
  }
  dom.collectSummary.textContent = text;
}

function renderCollectChecks(preflight) {
  if (!dom.collectChecks) return;
  clear(dom.collectChecks);
  if (!preflight) {
    dom.collectChecks.append(el('p', {
      className: 'hint',
      text: '修改条件后需要重新检查。'
    }));
    return;
  }
  const checks = Array.isArray(preflight.checks) ? preflight.checks : [];
  const mode = collectMode();
  const summary = el('p', {
    className: `notice ${preflight.ok ? '' : 'notice-accent'}`.trim(),
    text: preflight.ok ? '检查通过，可以启动。' : '检查未通过；请先处理下面的问题。'
  });
  dom.collectChecks.append(summary);
  if (!checks.length) {
    dom.collectChecks.append(el('p', { className: 'hint', text: '没有可显示的检查项。' }));
  }
  checks.forEach((check) => {
    const display = mode === 'monitor' && check.id === 'ai_connection'
      ? { ...check, message: '监控任务不调用 AI', detail: '只读取已有会话中的 HR 回复，不进行评分。' }
      : check;
    const status = String(display.status || '');
    const kind = status === 'pass' ? 'badge-good' : status === 'warning' ? 'badge-warn' : 'badge-bad';
    const label = status === 'pass' ? '通过' : status === 'warning' ? '注意' : '阻塞';
    const symbol = status === 'pass' ? '✓' : status === 'warning' ? '!' : '×';
    const row = el('div', { className: 'collect-check' });
    row.append(el('span', { className: `badge ${kind}`, text: `${symbol} ${label}` }));
    const body = el('div', { className: 'collect-check-body' });
    body.append(el('strong', { text: String(display.title || display.id || '检查项') }));
    body.append(el('p', { text: String(display.message || '') }));
    if (display.detail) body.append(el('p', { className: 'hint', text: String(display.detail) }));
    row.append(body);
    dom.collectChecks.append(row);
  });
  const messages = Array.isArray(preflight.messages) ? preflight.messages.filter(Boolean) : [];
  if (messages.length) {
    dom.collectChecks.append(el('p', { className: 'notice notice-accent', text: messages.join('；') }));
  }
}

function syncCollectModeUI() {
  renderCollectCriteria();
  const mode = collectMode();
  const needsSearch = collectNeedsSearch(mode);
  document.querySelectorAll('[data-collect-search]').forEach((node) => {
    node.hidden = !needsSearch;
  });
  if (dom.offerpilotStart) {
    dom.offerpilotStart.textContent = mode === 'monitor' ? '开始监控' : mode === 'full' ? '开始完整流程' : '开始采集';
  }
  if (dom.collectPlatform) {
    const locked = mode === 'full';
    if (locked) dom.collectPlatform.value = 'boss';
    dom.collectPlatform.disabled = locked;
    if (dom.collectPlatformHint) {
      dom.collectPlatformHint.textContent = locked
        ? '完整流程会进入投递，目前只有 Boss直聘 开放投递；其他平台请选「仅采集」。'
        : collectPlatform() === 'boss'
          ? ''
          : `${collectPlatformLabel(collectPlatform())} 目前只能采集、评分和生成招呼语，投递与回复监控暂未开放。`;
    }
  }
  renderCollectSummary();
  const key = collectFormKey();
  if (state.offerpilotPreflight && state.offerpilotPreflightKey !== key) {
    state.offerpilotPreflight = null;
    renderCollectChecks(null);
  }
  syncOfferPilotStartState();
}

function syncCollectResumeUI() {
  const resume = state.offerpilotResume || { available: false };
  const available = Boolean(resume.available);
  if (dom.collectResumeStatus) {
    dom.collectResumeStatus.textContent = available
      ? `已上传：${resume.filename || '简历'}${resume.size_label ? `（${resume.size_label}）` : ''}。本次采集会默认评分。`
      : '必须先上传简历才能开始采集（用于给岗位评分、生成招呼语）。支持 .md / .docx / .pdf。';
    dom.collectResumeStatus.classList.toggle('resume-missing', !available);
  }
  if (dom.collectAutoScore) {
    // Scoring is no longer optional: a resume is required to start collect/full.
    dom.collectAutoScore.checked = available;
    const scoreLabel = dom.collectAutoScore.closest('label');
    if (scoreLabel) scoreLabel.hidden = true;
  }
}

function applyOfferPilotPrefs(data) {
  if (!data.preferences || typeof data.preferences !== 'object') return;
  if (state.offerpilotPrefsMode === state.mode) return;
  state.offerpilotPrefsMode = state.mode;
  const prefs = data.preferences;
  if (dom.collectKeywords && !dom.collectKeywords.value && Array.isArray(prefs.keywords)) {
    dom.collectKeywords.value = prefs.keywords.slice(0, 10).join(', ');
  }
  if (dom.collectCities && !dom.collectCities.value && Array.isArray(prefs.cities)) {
    dom.collectCities.value = prefs.cities.slice(0, 5).join(', ');
  }
  if (dom.collectPages && !dom.collectPages.value && prefs.max_pages && prefs.max_pages.boss) {
    dom.collectPages.value = String(prefs.max_pages.boss);
  }
  syncCollectModeUI();
}

function renderOfferPilot(boss) {
  const data = boss && typeof boss === 'object' ? boss : {};
  // /api/offerpilot/state uses `ok`; pipeline.offerpilot uses `connected`.
  const connected = data.connected === true || data.ok === true;
  state.offerpilotConnected = connected;
  state.offerpilotCanStart = connected
    && !(data.capabilities && data.capabilities.collect_without_ai === false);
  if (state.offerpilotJobsMode !== state.mode) {
    // Never carry a job snapshot across data modes: demo must not show user jobs.
    state.offerpilotJobsMode = state.mode;
    state.offerpilotJobsLoaded = false;
    state.offerpilotPrefsMode = null;
    state.offerpilotJobs = [];
    state.offerpilotSelection.clear();
    state.offerpilotPreflight = null;
    state.offerpilotPreflightKey = '';
    renderCollectChecks(null);
    if (dom.offerpilotJobsCount) dom.offerpilotJobsCount.textContent = '尚未读取';
    if (dom.offerpilotJobsTable) {
      clear(dom.offerpilotJobsTable);
      dom.offerpilotJobsTable.append(el('p', { className: 'hint', text: '正在读取采集结果…' }));
    }
  }
  if (dom.offerpilotConnection) {
    dom.offerpilotConnection.textContent = state.offerpilotCanStart ? '已就绪' : '未就绪';
    dom.offerpilotConnection.className = `badge ${state.offerpilotCanStart ? 'badge-good' : 'badge-warn'}`;
  }
  if (dom.offerpilotState) {
    clear(dom.offerpilotState);
    dom.offerpilotState.append(offerpilotMetaRow('运行方式', el('span', { className: 'cell-mono', text: String(data.base_url || '—').startsWith('embedded://') ? '内嵌运行（本机）' : String(data.base_url || '—') })));
    dom.offerpilotState.append(offerpilotMetaRow('状态', state.offerpilotCanStart ? '采集组件可用' : '组件或数据没准备好'));
    if (connected && data.ai) {
      dom.offerpilotState.append(offerpilotMetaRow('AI 配置', data.ai.configured ? '已配置（不会显示密钥）' : '未配置（仍可无 AI 采集/监控）'));
    }
    const capabilities = connected && data.capabilities ? data.capabilities : {};
    const keys = Object.keys(OFFERPILOT_CAPABILITY_LABELS).filter((key) => capabilities[key] === true);
    if (keys.length) {
      const chips = el('div', { className: 'chip-row' });
      keys.forEach((key) => chips.append(el('span', { className: 'chip', text: OFFERPILOT_CAPABILITY_LABELS[key] })));
      dom.offerpilotState.append(offerpilotMetaRow('能力', chips));
    }
    const preferences = connected && data.preferences && typeof data.preferences === 'object' ? data.preferences : null;
    if (preferences) {
      const parts = [];
      if (Array.isArray(preferences.keywords) && preferences.keywords.length) parts.push(`关键词：${preferences.keywords.slice(0, 6).map(compactValue).join('、')}`);
      if (Array.isArray(preferences.cities) && preferences.cities.length) parts.push(`城市：${preferences.cities.slice(0, 6).map(compactValue).join('、')}`);
      if (preferences.salary !== undefined && preferences.salary !== null && preferences.salary !== '') parts.push(`薪资：${compactValue(preferences.salary)}`);
      if (preferences.score_threshold !== undefined && preferences.score_threshold !== null) parts.push(`最低分：${compactValue(preferences.score_threshold)}/100`);
      dom.offerpilotState.append(offerpilotMetaRow('上次使用的偏好', parts.length ? parts.join('；') : '已连接，暂无偏好字段'));
    }
  }
  if (dom.offerpilotError) {
    const error = connected ? '' : String(data.error || '采集组件或数据还没准备好；工作台其他功能不受影响。');
    dom.offerpilotError.hidden = !error;
    dom.offerpilotError.textContent = error;
    dom.offerpilotError.className = `notice ${connected ? '' : 'notice-accent'}`.trim();
  }
  if (dom.collectAutoScore) {
    const aiReady = Boolean(connected && data.ai && data.ai.configured);
    state.offerpilotResume = connected && data.resume && typeof data.resume === 'object'
      ? data.resume
      : { available: false };
    syncCollectResumeUI();
    dom.collectAutoScore.checked = Boolean(state.offerpilotResume.available);
    state.offerpilotAiReady = aiReady;
  }
  applyOfferPilotPrefs(data);
  state.offerpilotTaskActive = Boolean(data.task);
  state.offerpilotPipeline = data.pipeline && typeof data.pipeline === 'object' ? data.pipeline : null;
  renderPipelineStatus();
  syncCollectModeUI();
  renderOfferPilotTask(data.task, data.last_task);
  syncOfferPilotStartState();
  if (!data.task) maybeAutoImportCollected(data.last_task);
  if (!connected) {
    state.offerpilotJobsLoaded = false;
    if (dom.offerpilotJobsCount) dom.offerpilotJobsCount.textContent = '未连接';
    if (dom.offerpilotJobsTable) {
      clear(dom.offerpilotJobsTable);
      dom.offerpilotJobsTable.append(el('p', { className: 'hint', text: '采集组件就绪后，这里会显示采集结果。' }));
    }
  } else if (!state.offerpilotJobsLoaded) {
    loadOfferPilotJobs();
  }
  syncOfferPilotPoll(state.offerpilotTaskActive);
  const collectView = document.getElementById('view-collect');
  if (state.offerpilotCanStart && collectView && !collectView.hidden) {
    maybeRunOfferPilotPreflight();
  }
}

function syncOfferPilotPoll(active) {
  if (active && !state.offerpilotPollTimer) {
    state.offerpilotPollTimer = window.setInterval(() => refreshOfferPilot(), 5000);
  } else if (!active && state.offerpilotPollTimer) {
    window.clearInterval(state.offerpilotPollTimer);
    state.offerpilotPollTimer = null;
  }
}

function collectResumeMissing() {
  const mode = collectMode();
  const needsResume = mode === 'collect' || mode === 'full';
  return needsResume && !(state.offerpilotResume && state.offerpilotResume.available);
}

// 采集/完整流程依赖个人资料里的必填项（姓名、所在城市、目标岗位、目标城市、教育经历、
// 至少一段工作或项目经历、技能、个人简介、真实性确认）；监控任务不读取资料，不受影响。
function collectProfileRequiredMissing() {
  const mode = collectMode();
  if (mode !== 'collect' && mode !== 'full') return [];
  const profile = state.snapshot && state.snapshot.profile;
  const completeness = profile && profile.completeness;
  if (!completeness || !Array.isArray(completeness.required_missing)) return [];
  return completeness.required_missing;
}

function syncOfferPilotStartState() {
  if (!dom.offerpilotStart) return;
  const preflightReady = Boolean(state.offerpilotPreflight && state.offerpilotPreflight.ok === true);
  const resumeMissing = collectResumeMissing();
  const profileMissing = collectProfileRequiredMissing();
  dom.offerpilotStart.disabled = resumeMissing
    || profileMissing.length > 0
    || !state.offerpilotCanStart
    || state.offerpilotTaskActive
    || !dom.offerpilotRisk.checked
    || !dom.offerpilotConfirm.checked
    || !preflightReady;
  // 禁用原因直接写在按钮旁，不再只放在悬停提示里；按「最先要做的一步」给出。
  let reason = '';
  if (state.offerpilotTaskActive) reason = '已有任务正在运行；请先停止或等待结束。';
  else if (!state.offerpilotCanStart) reason = '采集组件还没准备好；请点「重新检测」。';
  else if (profileMissing.length) reason = `个人资料缺少必填项：${profileMissing.join('、')}；请先在「个人资料」页补全并保存。`;
  else if (resumeMissing) reason = '请先上传评分简历。';
  else if (!preflightReady) reason = '请先点「检查环境」，并处理提示的问题。';
  else if (!dom.offerpilotRisk.checked) reason = '请先勾选「我知道自动化操作可能导致账号被平台限制」。';
  else if (!dom.offerpilotConfirm.checked) reason = '勾选「确认启动」后才能开始。';
  dom.offerpilotStart.title = reason;
  const reasonNode = document.getElementById('offerpilot-start-reason');
  if (reasonNode) {
    reasonNode.textContent = reason;
    reasonNode.hidden = !reason;
  }
}

// 采集库里的岗位要经过「导入」才进岗位池：用岗位池里记录的 offerpilot_id 对出哪些已入库，
// 让「采集 126 条、岗位池 31 条」这种差距有解释。
function offerpilotPoolIds() {
  const rows = state.snapshot && Array.isArray(state.snapshot.jobs) ? state.snapshot.jobs : [];
  return new Set(rows.map((row) => String((row && row.offerpilot_id) || '')).filter(Boolean));
}

function offerpilotJobsCountText(jobs, total, pool) {
  const head = total > jobs.length ? `显示前 ${jobs.length} 条 / 共 ${total} 条` : `共 ${total} 条`;
  const imported = jobs.filter((job) => pool.has(String(job.id || ''))).length;
  return jobs.length ? `${head}；其中 ${imported} 条已在岗位池，其余需勾选后导入` : head;
}

function renderOfferPilotJobs() {
  if (!dom.offerpilotJobsTable) return;
  const jobs = state.offerpilotJobs;
  const pool = offerpilotPoolIds();
  if (dom.offerpilotJobsCount && state.offerpilotJobsLoaded) {
    dom.offerpilotJobsCount.textContent = offerpilotJobsCountText(jobs, state.offerpilotJobsTotal, pool);
  }
  renderTable(dom.offerpilotJobsTable, {
    caption: '表：本机采集结果（只读快照）',
    columns: ['岗位', '公司', '城市', '薪资', '评分', '状态'],
    rows: jobs.map((job) => [
      String(job.title || '—'),
      String(job.company || '—'),
      String(job.city || '—'),
      String(job.salary || '—'),
      // 采集结果的评分都是 0–100 的文档匹配分；0 分也是有效评分，不能显示成「—」或「待评分」。
      el('span', {
        className: 'sg-num',
        text: job.score === undefined || job.score === null || job.score === '' || !Number.isFinite(Number(job.score))
          ? '—'
          : `${Math.round(Number(job.score))}/100`
      }),
      (OFFERPILOT_JOB_STATUS_LABELS[String(job.status || '')] || '未知状态')
        + (pool.has(String(job.id || '')) ? '；已在岗位池' : '')
    ]),
    emptyText: state.offerpilotConnected ? '当前没有采集结果。启动一次采集后，这里会显示岗位。' : '采集组件还没准备好。'
  });
  syncOfferPilotSelection();
}

function syncOfferPilotSelection() {
  if (dom.offerpilotImport) {
    dom.offerpilotImport.disabled = state.offerpilotJobs.length === 0 || !state.offerpilotCanStart;
  }
}

async function loadOfferPilotJobs(options = {}) {
  if (!state.offerpilotConnected || state.offerpilotJobsLoading) return;
  const requestedMode = state.mode;
  state.offerpilotJobsLoading = true;
  if (options.announce) setStatus('正在读取采集结果…', 'info');
  try {
    const response = await fetch(`/api/offerpilot/jobs?mode=${encodeURIComponent(requestedMode)}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });
    const data = await parseResponse(response);
    if (state.mode !== requestedMode) return;
    const jobs = Array.isArray(data.jobs) ? data.jobs : [];
    const reportedTotal = Number(data.total);
    const total = Number.isFinite(reportedTotal) && reportedTotal >= jobs.length
      ? reportedTotal
      : jobs.length;
    state.offerpilotJobs = jobs;
    state.offerpilotJobsTotal = total;
    state.offerpilotJobsLoaded = true;
    const validIds = new Set(jobs.map((job) => String(job.id || '')).filter(Boolean));
    state.offerpilotSelection.forEach((id) => {
      if (!validIds.has(id)) state.offerpilotSelection.delete(id);
    });
    renderOfferPilotJobs();
    if (options.announce) {
      const scope = total > jobs.length ? `显示前 ${jobs.length} 条（共 ${total} 条）` : `读到 ${jobs.length} 条`;
      setStatus(`${scope}采集结果；导入前不会写入岗位池。`, 'ok');
    }
  } catch (error) {
    state.offerpilotJobsLoaded = false;
    state.offerpilotJobs = [];
    state.offerpilotJobsTotal = 0;
    state.offerpilotSelection.clear();
    if (dom.offerpilotJobsCount) dom.offerpilotJobsCount.textContent = '读取失败';
    if (dom.offerpilotJobsTable) {
      clear(dom.offerpilotJobsTable);
      dom.offerpilotJobsTable.append(el('p', { className: 'notice', text: friendlyError(error) }));
    }
    syncOfferPilotSelection();
    if (options.announce) setStatus(`读取采集结果失败：${friendlyError(error)}`, 'error');
  } finally {
    state.offerpilotJobsLoading = false;
  }
}

async function runOfferPilotPreflight(button) {
  if (!state.offerpilotCanStart) {
    setStatus('采集组件还没准备好；请点「重新检测」。', 'error');
    return;
  }
  const mode = collectMode();
  const needsSearch = collectNeedsSearch(mode);
  const options = needsSearch ? buildOfferPilotOptions() : null;
  if (needsSearch && !options) return;
  const key = collectFormKey();
  if (button) {
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
  }
  if (dom.collectChecks) {
    clear(dom.collectChecks);
    dom.collectChecks.append(el('p', { className: 'hint', text: '正在检查浏览器、配置与 AI…' }));
  }
  try {
    const payload = { mode, data_mode: state.mode };
    if (options) payload.options = options;
    const data = await postJson('/api/offerpilot/preflight', payload);
    state.offerpilotPreflight = data;
    state.offerpilotPreflightKey = key;
    renderCollectChecks(data);
    if (data.ok) {
      if (collectResumeMissing()) setStatus('检查通过，但还需要先上传评分简历才能启动。', 'warn');
      else setStatus('检查通过，可以启动。', 'ok');
    }
    else setStatus(`检查未通过：${(data.messages && data.messages[0]) || '请查看检查项'}`, 'warn');
  } catch (error) {
    const failure = { ok: false, checks: [], messages: [friendlyError(error)] };
    state.offerpilotPreflight = failure;
    state.offerpilotPreflightKey = key;
    renderCollectChecks(failure);
    setStatus(`检查没有完成：${friendlyError(error)}`, 'error');
  } finally {
    if (button) {
      button.removeAttribute('aria-busy');
      button.disabled = false;
    }
    syncOfferPilotStartState();
  }
}

function maybeRunOfferPilotPreflight() {
  if (!state.offerpilotCanStart) return;
  // 任务运行时会独占浏览器；此时自动检查只会得到误导性的「连接失败」。
  if (state.offerpilotTaskActive) return;
  const key = collectFormKey();
  if (state.offerpilotPreflight && state.offerpilotPreflightKey === key) return;
  if (collectNeedsSearch(collectMode()) && !buildOfferPilotOptions(true)) {
    renderCollectChecks(null);
    return;
  }
  runOfferPilotPreflight();
}

async function refreshOfferPilot(options = {}) {
  if (dom.offerpilotRefresh) dom.offerpilotRefresh.disabled = true;
  try {
    const response = await fetch(`/api/offerpilot/state?mode=${encodeURIComponent(state.mode)}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });
    const data = await parseResponse(response);
    renderOfferPilot(data.state);
    if (options.announce) {
      setStatus(
        data.state && data.state.ok
          ? (state.offerpilotCanStart ? '采集组件已就绪。' : '采集组件还没准备好；请点「重新检测」。')
          : `采集组件不可用：${(data.state && data.state.error) || '组件或数据没准备好'}`,
        data.state && data.state.ok ? 'ok' : 'warn'
      );
    }
    if (state.offerpilotConnected) await loadOfferPilotJobs(options);
    if (state.snapshot) await loadState();
    maybeRunOfferPilotPreflight();
  } catch (error) {
    renderOfferPilot({ connected: false, error: friendlyError(error) });
    if (options.announce) setStatus(`检测采集组件失败：${friendlyError(error)}`, 'error');
  } finally {
    if (dom.offerpilotRefresh) dom.offerpilotRefresh.disabled = false;
  }
}

async function startOfferPilotTask(button) {
  const mode = collectMode();
  if (!['collect', 'monitor', 'full'].includes(mode)) {
    setStatus('任务类型不正确；请重新选择后再启动。', 'error');
    return;
  }
  if (!state.offerpilotCanStart) {
    setStatus('采集组件还没准备好；请点「重新检测」。', 'error');
    return;
  }
  const needsSearch = collectNeedsSearch(mode);
  const options = needsSearch ? buildOfferPilotOptions() : null;
  if (needsSearch && !options) return;
  if (!state.offerpilotPreflight || state.offerpilotPreflight.ok !== true || state.offerpilotPreflightKey !== collectFormKey()) {
    setStatus('请先点击「检查环境」，通过后再启动。', 'error');
    return;
  }
  if (!dom.offerpilotRisk.checked || !dom.offerpilotConfirm.checked) {
    setStatus('启动前请同时勾选风险提示和「确认启动」。', 'error');
    return;
  }
  const payload = {
    mode,
    data_mode: state.mode,
    confirm: true,
    risk_acknowledged: true
  };
  if (options) payload.options = options;
  const data = await runAction(button, () => postJson('/api/offerpilot/tasks', payload));
  if (!data) return;
  setStatus(data.message || '任务已提交，正在后台运行。', 'ok');
  showInline(dom.offerpilotResult, data.message || '任务已提交，正在后台运行。', 'ok');
  dom.offerpilotRisk.checked = true;
  dom.offerpilotConfirm.checked = false;
  state.offerpilotPreflight = null;
  state.offerpilotPreflightKey = '';
  syncOfferPilotStartState();
  await refreshOfferPilot();
}

function importedTaskIds() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(OFFERPILOT_IMPORTED_TASKS_KEY) || '[]');
    return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
  } catch {
    return new Set();
  }
}

function markTaskImported(taskId, imported) {
  const ids = importedTaskIds();
  if (imported) ids.add(String(taskId));
  else ids.delete(String(taskId));
  try {
    window.localStorage.setItem(OFFERPILOT_IMPORTED_TASKS_KEY, JSON.stringify(Array.from(ids).slice(-50)));
  } catch {
    // Storage may be unavailable; dedupe on the server still protects the pool.
  }
}

const IMPORT_CHUNK_SIZE = 100;

function chunkList(values, size = IMPORT_CHUNK_SIZE) {
  const chunks = [];
  for (let index = 0; index < values.length; index += size) {
    chunks.push(values.slice(index, index + size));
  }
  return chunks;
}

async function maybeAutoImportCollected(task) {
  if (!task || !state.offerpilotCanStart) return;
  if (state.offerpilotTaskActive || state.offerpilotAutoImporting) return;
  if (!['completed', 'stopped'].includes(String(task.status || ''))) return;
  const ids = task.progress && Array.isArray(task.progress.collected_job_ids)
    ? task.progress.collected_job_ids.map(String).filter(Boolean)
    : [];
  if (!ids.length || importedTaskIds().has(String(task.id))) return;
  const full = String(task.mode || '') === 'full';
  state.offerpilotAutoImporting = true;
  markTaskImported(task.id, true);
  const summary = { added: 0, duplicates: 0, failed: 0, processed: 0 };
  let lastData = null;
  let firstError = '';
  try {
    // 后端单次最多接收 100 条；超过时按 100 条分块顺序处理，
    // 一块失败不影响其他块，也不把整个任务标回未导入。
    for (const chunk of chunkList(ids)) {
      try {
        const payload = full
          ? { ids: chunk, data_mode: state.mode, task_id: String(task.id || '') }
          : { ids: chunk, data_mode: state.mode };
        const data = await postAction(full ? 'offerpilot-automate' : 'offerpilot-import', payload);
        if (!data || data.ok === false) {
          summary.failed += chunk.length;
          firstError = firstError || String((data && data.message) || '');
          continue;
        }
        lastData = data;
        summary.processed += chunk.length;
        summary.added += Array.isArray(data.added) ? data.added.length : 0;
        summary.duplicates += Number(data.duplicates) || 0;
      } catch (error) {
        summary.failed += chunk.length;
        firstError = firstError || friendlyError(error);
      }
    }
    if (!summary.processed) {
      // 所有分块都失败：保留可重试状态，下次刷新会再试。
      markTaskImported(task.id, false);
      const reason = firstError || '服务没有返回结果';
      showInline(dom.offerpilotResult, `自动导入没有成功：${reason}。稍后刷新会重试，也可点「导入全部到岗位池」。`, 'error');
      return;
    }
    let message = full
      ? String((lastData && lastData.message) || '流程已停在发送确认前')
      : `采集完成，已自动导入 ${summary.added} 条岗位`;
    if (summary.duplicates) message += `；跳过 ${summary.duplicates} 条重复记录`;
    if (summary.failed) message += `；另有 ${summary.failed} 条分块导入失败，可在采集结果里重新导入`;
    if (full && lastData) state.offerpilotPipeline = lastData;
    renderPipelineStatus();
    const collectView = document.getElementById('view-collect');
    const onCollect = collectView && !collectView.hidden;
    showInline(dom.offerpilotResult, message, summary.failed ? 'warn' : 'ok');
    await loadState();
    renderOfferPilotJobs();
    if (full) {
      // 采集 → 评分 → 入队 → 招呼语 都是自动的，完成后直接落到审批队列。
      showView('queue');
      setStatus(`${message} 请在「已通过，可以联系」里核对后发送。`, summary.failed ? 'warn' : 'ok');
    } else if (onCollect) {
      // 采集 → 自动导入 → 挑选岗位 是同一条主线，完成后直接落到岗位表。
      showView('jobs');
      setStatus(`${message} 已跳到岗位池，挑好后加入审批队列。`, summary.failed ? 'warn' : 'ok');
    } else {
      setStatus(message, summary.failed ? 'warn' : 'ok');
    }
  } finally {
    state.offerpilotAutoImporting = false;
  }
}

async function uploadOfferPilotResume(file) {
  if (!file) return;
  const name = String(file.name || '');
  if (!/\.(md|docx|pdf)$/i.test(name)) {
    setStatus('简历只支持 Markdown、DOCX 或 PDF 格式。', 'error');
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    setStatus('简历文件超过 5 MB 上限。', 'error');
    return;
  }
  const dataUrl = await new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => resolve('');
    reader.readAsDataURL(file);
  });
  if (!dataUrl) {
    setStatus('没能读取这份简历文件；请换一份再试。', 'error');
    return;
  }
  const base64 = dataUrl.includes(',') ? dataUrl.slice(dataUrl.indexOf(',') + 1) : dataUrl;
  const data = await runAction(dom.collectResumeUpload, () => postAction('offerpilot-resume', {
    filename: name,
    content_base64: base64
  }));
  if (!data) return;
  state.offerpilotAutoScoreTouched = false;
  setStatus(data.message || '简历已保存。', 'ok');
  await refreshOfferPilot();
  syncCollectResumeUI();
  syncCollectModeUI();
}

async function importOfferPilotJobs(button) {
  const ids = state.offerpilotJobs.map((job) => String(job.id || '')).filter(Boolean);
  if (!ids.length) {
    setStatus('当前没有可导入的采集结果。', 'error');
    return;
  }
  const data = await runAction(button, () => postAction('offerpilot-import', {
    ids,
    data_mode: state.mode
  }));
  if (!data) return;
  setStatus(data.message || '已导入岗位池。', 'ok');
  showInline(dom.offerpilotResult, data.message || '已导入岗位池。', 'ok');
  await loadState();
  renderOfferPilotJobs();
  syncOfferPilotSelection();
}

async function stopOfferPilotTask(taskId, button) {
  const data = await runAction(button, () => postJson(
    `/api/offerpilot/tasks/${encodeURIComponent(taskId)}/stop`,
    { data_mode: state.mode }
  ));
  if (!data) return;
  setStatus('已请求停止。', 'ok');
  showInline(dom.offerpilotResult, '已请求停止；当前这一步结束后就会停下，以任务状态为准。', 'ok');
  await refreshOfferPilot();
}

// 入队结果里有多个「没进去」的列表；按岗位 id 收集一条可读原因，
// 渲染在对应行里。行内提示比只给一条汇总文案更容易核对。
function enqueueNotesFromResult(data) {
  const notes = {};
  const put = (id, text) => {
    const key = String(id || '');
    if (key && !notes[key]) notes[key] = text;
  };
  const each = (rows, fallback) => {
    (Array.isArray(rows) ? rows : []).forEach((item) => {
      if (typeof item === 'string') put(item, fallback);
      else if (item && typeof item === 'object') {
        put(item.id, String(item.reason || item.message || fallback));
      }
    });
  };
  each(data.risk_blocked, '疑似高风险岗位，未入队');
  each(data.city_blocked, '城市不在目标城市，未入队');
  each(data.mandatory_blocked, '必备条件明确不满足，未自动入队');
  each(data.closed_blocked, '岗位已关闭或失效，未自动入队');
  each(data.unscored, '未评分，未自动入队');
  each(data.dropped, '不是岗位文档评分，未自动入队');
  each(data.recent_duplicates, '30 天内已加入或联系过，已跳过');
  return notes;
}

async function enqueueJob(job, button, manual = false) {
  return enqueueJobs([job], button, manual);
}

async function enqueueJobs(jobs, button, manual = false) {
  const ids = jobs.map((job) => String(job.id)).filter(Boolean);
  if (!ids.length) return;
  const payload = { ids };
  if (manual) {
    payload.allow_low_score = true;
    payload.override_reason = dom.jobsOverrideReason ? dom.jobsOverrideReason.value : '';
  }
  const data = await runAction(button, () => postAction('enqueue', payload));
  if (!data) return;
  // 只清掉真正入队（含已在队列）的岗位；被丢弃的岗位保留勾选，方便修改后重试。
  const cleared = new Set();
  ['accepted', 'manual', 'duplicate'].forEach((key) => {
    (Array.isArray(data[key]) ? data[key] : []).forEach((item) => {
      const id = typeof item === 'string' ? item : item && item.id;
      if (id) cleared.add(String(id));
    });
  });
  ids.forEach((id) => { if (cleared.has(id)) state.jobsSelection.delete(id); });
  state.jobsEnqueueNotes = enqueueNotesFromResult(data);
  let message = data.message || '已加入待确认队列。';
  if (Array.isArray(data.dropped) && data.dropped.length) {
    message += ` 有 ${data.dropped.length} 条没有加入（没有按岗位文档评分，或不符合加入条件）。`;
  }
  if (Array.isArray(data.duplicate) && data.duplicate.length) {
    message += ` 其中 ${data.duplicate.length} 条已经在队列里。`;
  }
  if (Array.isArray(data.recent_duplicates) && data.recent_duplicates.length) {
    message += ` ${data.recent_duplicates.length} 条在 30 天内加入过或联系过，已跳过。`;
  }
  const accepted = (Array.isArray(data.accepted) && data.accepted.length > 0)
    || (Array.isArray(data.manual) && data.manual.length > 0);
  setStatus(message, accepted ? 'ok' : 'warn');
  showInline(dom.jobsActionResult, message, accepted ? 'ok' : 'warn');
  await loadState();
}

async function jobsDeleteSelected(jobs, button) {
  const ids = jobs.map((job) => String(job.id)).filter(Boolean);
  if (!ids.length) return;
  if (!window.confirm(`删除 ${ids.length} 条岗位？已通过或已发送的不会被删除。`)) return;
  const data = await runAction(button, () => postAction('delete-jobs', { ids }));
  if (!data) return;
  const kept = new Set(
    (Array.isArray(data.skipped) ? data.skipped : [])
      .filter((item) => item && item.reason !== 'not_found')
      .map((item) => String(item.id))
  );
  ids.forEach((id) => {
    if (kept.has(id)) return;
    state.jobsSelection.delete(id);
    delete state.jobsEnqueueNotes[id];
  });
  const message = data.message || `已删除 ${data.deleted || 0} 条。`;
  showInline(dom.jobsActionResult, message, data.deleted ? 'ok' : 'warn');
  await loadState();
}

async function prepareJob(job, button) {
  const data = await runAction(button, () => postAction('prepare', { id: String(job.id) }));
  if (!data) return;
  const ok = announceActionResult(data, '已生成人工准备清单；没有提交申请。');
  if (ok) {
    showInline(
      dom.jobsActionResult,
      data.message || '已生成人工准备清单；没有提交申请。',
      'ok',
      data.download ? [data.download] : []
    );
    await loadState();
  }
}

// 岗位池里不可回到上一状态的目标：淘汰、已过滤、Offer（Offer 之后没有后继状态）。
const IRREVERSIBLE_JOB_STATES = new Set(['淘汰', '已过滤', 'Offer']);

async function transitionJob(job, target, select) {
  const data = await runAction(select, () => postAction('transition', {
    id: String(job.id),
    from: String(job.state || ''),
    to: String(target)
  }));
  if (!data) {
    select.value = '';
    return;
  }
  const ok = announceActionResult(data, `状态已记录为「${target}」。`);
  if (ok) {
    showInline(dom.jobsActionResult, data.message || `状态已记录为「${target}」。`, 'ok');
    await loadState();
  } else {
    select.value = '';
  }
}

/* Render: queue */

function pendingQueueRows() {
  const queue = state.snapshot && Array.isArray(state.snapshot.queue) ? state.snapshot.queue : [];
  return queue.filter((row) => row.status === 'pending');
}

function syncQueueCheckboxes() {
  dom.queuePendingTable.querySelectorAll('input.queue-check').forEach((box) => {
    box.checked = state.queueSelection.has(String(box.dataset.queueId));
  });
}

function updateQueueSelectionUI() {
  const pending = pendingQueueRows();
  const pendingIds = new Set(pending.map((row) => String(row.id)));
  Array.from(state.queueSelection).forEach((id) => {
    if (!pendingIds.has(id)) state.queueSelection.delete(id);
  });
  let selected = 0;
  state.queueSelection.forEach((id) => {
    if (pendingIds.has(id)) selected += 1;
  });
  dom.queueSelectionCount.textContent = `已选 ${selected} 条`;
  const allSelected = pending.length > 0 && selected === pending.length;
  dom.queueSelectAll.checked = allSelected;
  dom.queueSelectAll.indeterminate = selected > 0 && !allSelected;
  dom.queueConfirmButton.disabled = selected === 0;
}

function renderPipelineStatus() {
  if (!dom.queuePipelineStatus) return;
  const pipeline = state.offerpilotPipeline && typeof state.offerpilotPipeline === 'object'
    ? state.offerpilotPipeline
    : null;
  const awaiting = Boolean(pipeline && pipeline.awaiting_confirmation);
  const approved = Number(pipeline && pipeline.approved_count) || 0;
  const message = pipeline && pipeline.message ? String(pipeline.message) : '';
  if (!message && !awaiting) {
    dom.queuePipelineStatus.hidden = true;
    dom.queuePipelineStatus.textContent = '';
    return;
  }
  const parts = [];
  if (message) parts.push(message);
  if (awaiting) {
    parts.push(`当前有 ${approved} 条已通过岗位等待你最终确认；未点「确认发送本批」前不会发出任何消息。`);
  }
  dom.queuePipelineStatus.textContent = parts.join(' ');
  dom.queuePipelineStatus.className = awaiting ? 'notice notice-accent' : 'notice';
  dom.queuePipelineStatus.hidden = false;
}

function queueEmptyNode(text, actionLabel = '去岗位池挑选') {
  const empty = el('div', { className: 'sg-empty' });
  empty.append(el('p', { className: 'sg-empty-text', text }));
  const action = el('button', {
    className: 'button button-quiet button-small',
    text: actionLabel,
    attrs: { type: 'button' }
  });
  action.addEventListener('click', () => showView('jobs'));
  empty.append(action);
  return empty;
}

// 公司 / 岗位在审批表里单行省略，完整内容放在 title（规格 3.4）。
function queueTextCell(value) {
  const text = String(value || '—');
  return el('span', { className: 'sg-ellipsis', text, attrs: { title: text } });
}

function renderQueue(snapshot) {
  const queue = Array.isArray(snapshot.queue) ? snapshot.queue : [];
  const pending = queue.filter((row) => row.status === 'pending');
  const approved = queue.filter((row) => row.status === 'approved');
  const pendingIds = new Set(pending.map((row) => String(row.id)));
  Array.from(state.queueSelection).forEach((id) => {
    if (!pendingIds.has(id)) state.queueSelection.delete(id);
  });

  dom.queuePendingCount.textContent = `${pending.length} 条待确认`;
  dom.queueApprovedCount.textContent = `${approved.length} 条已确认`;

  const pendingRows = pending.map((row) => {
    const id = String(row.id);
    const checkbox = el('input', {
      className: 'queue-check',
      props: { type: 'checkbox', checked: state.queueSelection.has(id) }
    });
    checkbox.dataset.queueId = id;
    checkbox.setAttribute('aria-label', `选择 ${row.company || ''} ${row.title || ''}`);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) state.queueSelection.add(id);
      else state.queueSelection.delete(id);
      updateQueueSelectionUI();
    });
    const reviewButton = el('button', {
      className: 'button button-small button-quiet queue-review-open',
      text: '核对',
      attrs: { type: 'button', 'aria-label': `核对 ${row.company || ''} ${row.title || ''} 的要求与证据` }
    });
    reviewButton.addEventListener('click', () => {
      // 关闭抽屉时把焦点还给「核对」按钮。
      reviewButton.focus({ preventScroll: true });
      openQueueReview(snapshot, row);
    });
    return [
      checkbox,
      queueTextCell(row.company),
      queueTextCell(row.title),
      el('span', { className: 'sg-num', text: formatJobScoreValue(row.score) }),
      channelLabel(row.Source_Channel),
      formatDateTime(row.created_at),
      confidenceCell(row),
      reviewButton
    ];
  });
  renderTable(dom.queuePendingTable, {
    caption: '表：待确认队列',
    columns: ['选择', '公司', '岗位', '评分', '渠道', '创建时间', '判断依据', '核对'],
    rows: pendingRows,
    emptyText: '待确认队列为空。到「岗位池」把想联系的岗位加入队列。',
    emptyNode: queueEmptyNode('待确认队列为空。到「岗位池」把想联系的岗位加入队列。'),
    className: 'data-table-wide'
  });

  const approvedRows = approved.map((row) => {
    const id = String(row.id);
    const checkbox = el('input', {
      className: 'queue-check',
      props: { type: 'checkbox', checked: state.queueApprovedSelection.has(id) }
    });
    checkbox.dataset.queueId = id;
    checkbox.setAttribute('aria-label', `选择已确认 ${row.company || ''} ${row.title || ''}`);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) state.queueApprovedSelection.add(id);
      else state.queueApprovedSelection.delete(id);
      updateQueueApprovedSelectionUI();
    });
    const reviewButton = el('button', {
      className: 'button button-small button-quiet queue-review-open',
      text: '核对',
      attrs: { type: 'button', 'aria-label': `核对已确认岗位 ${row.company || ''} ${row.title || ''} 的要求与证据` }
    });
    reviewButton.addEventListener('click', () => {
      // 关闭抽屉时把焦点还给「核对」按钮。
      reviewButton.focus({ preventScroll: true });
      openQueueReview(snapshot, row);
    });
    return [
      checkbox,
      queueTextCell(row.company),
      queueTextCell(row.title),
      el('span', { className: 'sg-num', text: formatJobScoreValue(row.score) }),
      channelLabel(row.Source_Channel),
      greetingStatusBadge(row.greeting),
      deliveryStatusBadge(row.delivery),
      planBadge(row.plan),
      badge('已通过，可以联系', 'good', '✓'),
      reviewButton
    ];
  });
  renderTable(dom.queueApprovedTable, {
    caption: '表：已确认可人工投递',
    columns: ['选择', '公司', '岗位', '评分', '渠道', '招呼语', '投递', '今日安排', '状态', '核对'],
    rows: approvedRows,
    emptyText: '还没有已确认的岗位。「已通过」只表示你同意联系，不代表已经投递。',
    emptyNode: queueEmptyNode('还没有已确认的岗位。「已通过」只表示你同意联系，不代表已经投递。'),
    className: 'data-table-wide'
  });
  renderQueueGreetings(approved);
  renderDeliveryResults(snapshot);
  if (state.queueDeliveryOpen) {
    renderDeliveryProgress(snapshot);
    updateDeliveryStartState();
  }
  renderPipelineStatus();

  const reviewJob = queueReviewJob(snapshot, state.queueReviewId);
  if (reviewJob && dom.queueReview && dom.queueReviewBody) {
    dom.queueReview.hidden = false;
    renderDossier(dom.queueReviewBody, reviewJob);
  } else if (dom.queueReview) {
    state.queueReviewId = null;
    dom.queueReview.hidden = true;
    clear(dom.queueReviewBody);
  }

  updateQueueSelectionUI();
  updateQueueApprovedSelectionUI();
}

function planBadge(plan) {
  if (!plan || typeof plan !== 'object') return el('span', { className: 'muted', text: '—' });
  const node = plan.today ? badge(`今日第 ${plan.rank} 位`, 'good', '✓') : badge('顺延', 'neutral', '·');
  if (plan.reason) node.setAttribute('title', String(plan.reason));
  return node;
}

function approvedQueueRows() {
  const queue = state.snapshot && Array.isArray(state.snapshot.queue) ? state.snapshot.queue : [];
  return queue.filter((row) => row.status === 'approved');
}

function greetingStatusBadge(greeting) {
  if (!greeting || !String(greeting.greeting || '').trim()) return badge('未生成', 'neutral', '·');
  if (greeting.ready) return badge('已生成', 'good', '✓');
  return badge('待复核', 'warn', '!');
}

// 「判断置信度」是独立结果：必备条件证据的充分度，缺失时取资料覆盖率。
// 旧队列行的 high_confidence 只是阈值标记、未参与任何判定，不再显示在这一列。
function confidenceCell(row) {
  const value = row && typeof row.fit_confidence === 'number' ? row.fit_confidence : null;
  if (value === null) {
    const node = el('span', { className: 'muted', text: '—' });
    node.setAttribute('title', '该岗位没有可用的判断证据（必备条件证据或资料覆盖率）');
    return node;
  }
  const percent = Math.round(value * 100);
  const node = percent >= 70
    ? badge(formatPercent(value), 'good', '')
    : percent >= 40
      ? badge(formatPercent(value), 'warn', '')
      : el('span', { className: 'muted', text: formatPercent(value) });
  node.setAttribute('title', '判断依据：必备条件有多少证据；没有必备条件时看资料覆盖率');
  return node;
}

function renderQueueGreetings(approved) {
  const container = dom.queueGreetings;
  if (!container) return;
  clear(container);
  const rows = approved.filter((row) => row.greeting && String(row.greeting.greeting || '').trim());
  if (!rows.length) {
    container.append(el('p', {
      className: 'muted',
      text: '已确认岗位生成招呼语后，会在这里显示只读预览；不会发送。'
    }));
    return;
  }
  rows.forEach((row) => {
    const greeting = row.greeting || {};
    const card = el('article', { className: 'queue-greeting-card' });
    const head = el('div', { className: 'queue-greeting-head' });
    head.append(el('strong', { text: `${row.company || '—'}｜${row.title || '—'}` }));
    head.append(greeting.ready ? badge('已生成', 'good', '✓') : badge('待复核', 'warn', '!'));
    card.append(head);
    card.append(el('p', {
      className: 'queue-greeting-text',
      text: String(greeting.greeting || '')
    }));
    const meta = [];
    if (greeting.selection) meta.push(`来源：${greetingSourceLabel(greeting.selection)}`);
    if (Array.isArray(greeting.style_issues) && greeting.style_issues.length) {
      meta.push(`表达提醒：${greeting.style_issues.join('；')}`);
    }
    if (meta.length) card.append(el('p', { className: 'queue-greeting-meta', text: meta.join('；') }));
    const evidence = greeting.evidence_check;
    if (evidence && Array.isArray(evidence.unsupported_claims) && evidence.unsupported_claims.length) {
      const list = el('ul', { className: 'queue-greeting-evidence' });
      evidence.unsupported_claims.forEach((claim) => {
        list.append(el('li', { text: `「${claim.context}」中的数字 ${claim.value} 在个人资料中找不到依据，请核对后再发送` }));
      });
      card.append(el('p', { className: 'queue-greeting-meta', text: '资料里找不到依据的数字（只提醒，不会自动改）：' }));
      card.append(list);
    }
    container.append(card);
  });
}

function updateQueueApprovedSelectionUI() {
  const approved = approvedQueueRows();
  const approvedIds = new Set(approved.map((row) => String(row.id)));
  Array.from(state.queueApprovedSelection).forEach((id) => {
    if (!approvedIds.has(id)) state.queueApprovedSelection.delete(id);
  });
  const selected = state.queueApprovedSelection.size;
  if (dom.queueApprovedSelectionCount) {
    dom.queueApprovedSelectionCount.textContent = `已选 ${selected} 条`;
  }
  if (dom.queueApprovedSelectAll) {
    const allSelected = approved.length > 0 && selected === approved.length;
    dom.queueApprovedSelectAll.checked = allSelected;
    dom.queueApprovedSelectAll.indeterminate = selected > 0 && !allSelected;
  }
  if (dom.queueGenerateGreetings) {
    dom.queueGenerateGreetings.disabled = selected === 0
      || selected > 10
      || Boolean(state.offerpilotTaskActive);
    dom.queueGenerateGreetings.title = state.offerpilotTaskActive
      ? '已有采集任务在运行；请先停止或等它结束'
      : selected > 10
        ? '一次最多 10 条'
        : '只生成招呼语；完成后自动弹出核对窗口';
  }
  if (dom.queueSendGreetings) {
    const selectedRows = approved.filter((row) => state.queueApprovedSelection.has(String(row.id)));
    const greetingReady = selectedRows.length > 0
      && selectedRows.every((row) => row.greeting && row.greeting.ready);
    dom.queueSendGreetings.disabled = !greetingReady
      || selected > 10
      || Boolean(state.offerpilotTaskActive)
      || state.queueDeliveryOpen;
    // 禁用原因按真实原因给：未勾选 → 超过单批上限 → 无招呼语 → 发送中/任务运行。
    dom.queueSendGreetings.title = selectedRows.length === 0
      ? '请先勾选已确认岗位'
      : selected > 10
        ? `一次最多发送 10 条，当前已选 ${selected} 条`
        : !greetingReady
          ? '所选岗位还没有可发送的招呼语'
          : state.offerpilotTaskActive || state.queueDeliveryOpen
            ? '正在发送或已有任务在运行；请等它结束'
            : '查看并发送所选岗位的招呼语';
  }
}

async function generateQueueGreetings(button) {
  const ids = Array.from(state.queueApprovedSelection);
  if (!ids.length) {
    setStatus('请先勾选已确认岗位。', 'warn');
    return;
  }
  const data = await runAction(button, () => postAction('offerpilot-greet', { ids }));
  if (!data) return;
  if (data.ok === false) {
    setStatus(data.message || '招呼语生成未开始。', 'warn');
    return;
  }
  setStatus(data.message || '正在生成招呼语；完成后会自动弹出核对窗口。', 'ok');
  watchQueueGreetings(ids, button);
}

/* 生成招呼语是后台任务：轮询到所选岗位都 ready 后自动打开发送弹窗。 */
function stopQueueGreetingWatch() {
  const watch = state.queueGreetingWatch;
  if (watch && watch.timer) window.clearTimeout(watch.timer);
  state.queueGreetingWatch = null;
}

function watchQueueGreetings(ids, trigger) {
  stopQueueGreetingWatch();
  const watch = { ids: ids.map(String), attempts: 0, timer: null, trigger };
  state.queueGreetingWatch = watch;
  const maxAttempts = 30;
  const tick = async () => {
    if (state.queueGreetingWatch !== watch) return;
    watch.attempts += 1;
    if (!state.offerpilotPollTimer) {
      await refreshOfferPilot();
    }
    if (state.queueGreetingWatch !== watch) return;
    const rows = approvedQueueRows().filter((row) => watch.ids.includes(String(row.id)));
    const ready = rows.length === watch.ids.length
      && rows.every((row) => row.greeting && row.greeting.ready);
    if (ready) {
      stopQueueGreetingWatch();
      openDeliveryModal(rows, trigger);
      return;
    }
    if (watch.attempts >= maxAttempts) {
      stopQueueGreetingWatch();
      setStatus('招呼语还在生成；完成后可勾选岗位点「查看并发送」核对。', 'warn');
      return;
    }
    watch.timer = window.setTimeout(tick, 2500);
  };
  watch.timer = window.setTimeout(tick, 1500);
}

const DELIVERY_STATUS_META = {
  starting: ['准备中', 'warn', '…'],
  sending: ['发送中', 'warn', '…'],
  sent: ['已发送', 'good', '✓'],
  failed: ['失败', 'bad', '!'],
  deferred: ['延后', 'warn', '…'],
  blocked: ['已阻止', 'bad', '!'],
  unknown: ['待核实', 'warn', '?']
};

function deliveryStatusBadge(delivery) {
  if (!delivery || !delivery.status) return el('span', { className: 'muted', text: '—' });
  const meta = DELIVERY_STATUS_META[String(delivery.status)] || [String(delivery.status), 'neutral', '·'];
  return badge(meta[0], meta[1], meta[2]);
}

function selectedApprovedRows() {
  return approvedQueueRows().filter((row) => state.queueApprovedSelection.has(String(row.id)));
}

function deliveryConfirmPhrase(count) {
  return `确认发送本批 ${count} 条`;
}

function openDeliveryPanel(trigger) {
  openDeliveryModal(selectedApprovedRows(), trigger);
}

function openDeliveryModal(rows, trigger) {
  if (!dom.queueDeliveryPanel) return;
  const list = Array.isArray(rows) ? rows.filter(Boolean) : [];
  if (!list.length) {
    setStatus('请先勾选已确认岗位。', 'warn');
    return;
  }
  if (!list.every((row) => row.greeting && row.greeting.ready)) {
    setStatus('所选岗位需要先生成招呼语。', 'warn');
    return;
  }
  if (!state.queueDeliveryOpen) {
    state.queueDeliveryOpen = true;
    state.queueDeliveryReturnFocus = trigger || (document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null);
    document.body.classList.add('queue-modal-open');
    document.addEventListener('keydown', handleDeliveryKeydown);
  }
  state.queueDeliveryBusy = false;
  state.queueDeliverySubmitted = false;
  state.queueDeliveryBatchId = null;
  renderDeliveryModal(list);
  // 视图容器可能带 transform，会让 position:fixed 相对容器定位；弹窗挂到 body 才是全屏遮罩。
  if (dom.queueDeliveryPanel.parentElement !== document.body) {
    document.body.append(dom.queueDeliveryPanel);
  }
  dom.queueDeliveryPanel.hidden = false;
  if (dom.queueDeliveryCancel) dom.queueDeliveryCancel.focus();
  updateQueueApprovedSelectionUI();
}

function renderDeliveryModal(rows) {
  state.queueDeliveryIds = rows.map((row) => String(row.id));
  const count = rows.length;
  if (dom.queueDeliverySummary) {
    dom.queueDeliverySummary.textContent = count > 1
      ? `本批 ${count} 条；预计 ${count - 1} 次间隔，约 ${count - 1}–${(count - 1) * 3} 分钟。请逐条核对招呼语后再发送。`
      : '本批 1 条；确认后立即开始。请核对招呼语后再发送。';
  }
  if (dom.queueDeliveryPlatform) {
    const platforms = Array.from(new Set(rows
      .map((row) => (row.Source_Channel ? channelLabel(row.Source_Channel) : ''))
      .filter(Boolean)));
    dom.queueDeliveryPlatform.textContent = platforms.length
      ? `平台：${platforms.join('、')}`
      : '平台未知';
  }
  clear(dom.queueDeliveryList);
  rows.forEach((row) => {
    const greeting = row.greeting || {};
    const item = el('li', { className: 'queue-delivery-item' });
    item.append(el('strong', { text: `${row.company || '—'}｜${row.title || '—'}` }));
    item.append(el('p', { className: 'queue-delivery-text', text: String(greeting.greeting || '') }));
    item.append(el('p', {
      className: 'queue-delivery-meta',
      text: `来源：${greetingSourceLabel(greeting.selection) || '未标注'}`
    }));
    const evidence = greeting.evidence_check;
    if (evidence && Array.isArray(evidence.unsupported_claims) && evidence.unsupported_claims.length) {
      item.append(el('p', {
        className: 'queue-delivery-meta queue-delivery-warn',
        text: '资料里找不到依据的数字（只提醒，不会自动改）：'
      }));
      const evidenceList = el('ul', { className: 'queue-delivery-evidence' });
      evidence.unsupported_claims.forEach((claim) => {
        evidenceList.append(el('li', {
          text: `「${claim.context}」中的数字 ${claim.value} 在个人资料中找不到依据，请核对后再发送`
        }));
      });
      item.append(evidenceList);
    }
    dom.queueDeliveryList.append(item);
  });
  if (dom.queueDeliveryRisk) dom.queueDeliveryRisk.checked = true;
  if (dom.queueDeliveryProgress) dom.queueDeliveryProgress.textContent = '';
  updateDeliveryStartState();
}

function deliveryProgressText(snapshot) {
  if (state.queueDeliveryBusy) return '正在提交发送请求…';
  if (state.queueDeliverySubmitted) {
    const delivery = snapshot && snapshot.pipeline && snapshot.pipeline.delivery;
    const latest = delivery && delivery.latest_batch;
    const batch = latest && (!state.queueDeliveryBatchId
      || String(latest.batch_id || '') === state.queueDeliveryBatchId)
      ? latest
      : null;
    if (batch) {
      const status = String(batch.status || '');
      if (status === 'starting' || status === 'sending') {
        return `发送中：已成功 ${batch.sent || 0} 条，剩余在队列中；关闭弹窗后可在结果区查看。`;
      }
      const unknownText = batch.unknown ? `，${batch.unknown} 条读不到状态需到平台核实` : '';
      return `已提交：${batch.sent || 0} 成功，${batch.failed || 0} 失败，${batch.deferred || 0} 延后${unknownText}。关闭弹窗后可在结果区查看。`;
    }
    return '已提交发送，正在后台执行；关闭弹窗后可在结果区查看。';
  }
  return '';
}

function renderDeliveryProgress(snapshot) {
  if (!dom.queueDeliveryProgress) return;
  dom.queueDeliveryProgress.textContent = deliveryProgressText(snapshot);
}

function updateDeliveryStartState() {
  if (!dom.queueDeliveryStart) return;
  const count = state.queueDeliveryIds.length;
  const riskChecked = Boolean(dom.queueDeliveryRisk && dom.queueDeliveryRisk.checked);
  const blocked = state.queueDeliveryBusy
    || state.queueDeliverySubmitted
    || Boolean(state.offerpilotTaskActive);
  dom.queueDeliveryStart.disabled = !(count > 0 && riskChecked && !blocked);
  dom.queueDeliveryStart.textContent = `确认发送本批 ${count} 条`;
  if (dom.queueDeliveryCancel) dom.queueDeliveryCancel.disabled = state.queueDeliveryBusy;
}

function deliveryFocusable() {
  if (!dom.queueDeliveryPanel) return [];
  return Array.from(dom.queueDeliveryPanel.querySelectorAll(
    'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
  )).filter((node) => node.offsetParent !== null || node === document.activeElement);
}

function handleDeliveryKeydown(event) {
  if (!state.queueDeliveryOpen) return;
  if (event.key === 'Escape') {
    if (state.queueDeliveryBusy) return;
    event.preventDefault();
    closeDeliveryModal();
    return;
  }
  if (event.key !== 'Tab') return;
  const nodes = deliveryFocusable();
  if (!nodes.length) return;
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function closeDeliveryModal() {
  if (!state.queueDeliveryOpen || !dom.queueDeliveryPanel) return;
  if (state.queueDeliveryBusy) return;
  dom.queueDeliveryPanel.hidden = true;
  state.queueDeliveryOpen = false;
  state.queueDeliveryIds = [];
  state.queueDeliverySubmitted = false;
  state.queueDeliveryBatchId = null;
  document.body.classList.remove('queue-modal-open');
  document.removeEventListener('keydown', handleDeliveryKeydown);
  // 先恢复按钮可用状态，否则弹窗打开期间被禁用的触发按钮无法接收焦点。
  updateQueueApprovedSelectionUI();
  const target = state.queueDeliveryReturnFocus;
  state.queueDeliveryReturnFocus = null;
  if (target && typeof target.focus === 'function' && document.contains(target) && !target.disabled) {
    target.focus();
  } else if (dom.queueSendGreetings && !dom.queueSendGreetings.disabled) {
    dom.queueSendGreetings.focus();
  }
}

async function startQueueDelivery(button) {
  const ids = [...state.queueDeliveryIds];
  if (!ids.length) return;
  if (!dom.queueDeliveryRisk || !dom.queueDeliveryRisk.checked) return;
  const count = ids.length;
  state.queueDeliveryBusy = true;
  state.queueDeliverySubmitted = false;
  updateDeliveryStartState();
  renderDeliveryProgress(state.snapshot);
  setStatus('正在提交发送请求…', 'warn');
  const data = await runAction(button, () => postAction('offerpilot-deliver', {
    ids,
    confirm: deliveryConfirmPhrase(count),
    risk_acknowledged: true
  }));
  state.queueDeliveryBusy = false;
  if (!data || data.ok === false) {
    updateDeliveryStartState();
    renderDeliveryProgress(state.snapshot);
    if (data && data.message) setStatus(data.message, 'warn');
    return;
  }
  state.queueDeliverySubmitted = true;
  state.queueDeliveryBatchId = String((data.batch && data.batch.batch_id) || '') || null;
  state.queueApprovedSelection.clear();
  updateQueueApprovedSelectionUI();
  setStatus(data.message || '已提交发送；受每日上限与随机间隔约束。', 'ok');
  await refreshOfferPilot();
  renderDeliveryProgress(state.snapshot);
  updateDeliveryStartState();
}


async function stopQueueDelivery(button, taskId) {
  if (!taskId) return;
  const data = await runAction(button, () => postAction('offerpilot-stop', { task_id: taskId }));
  if (!data) return;
  setStatus('已请求停止；当前条完成后停止，剩余岗位会标记为延后。', 'ok');
  await refreshOfferPilot();
}

function renderDeliveryResults(snapshot) {
  const container = dom.queueDeliveryResults;
  if (!container) return;
  clear(container);
  const delivery = snapshot && snapshot.pipeline && snapshot.pipeline.delivery;
  const batch = delivery && delivery.latest_batch;
  if (!batch) return;
  const card = el('article', { className: 'queue-delivery-card' });
  const head = el('div', { className: 'queue-delivery-card-head' });
  const status = String(batch.status || '');
  const titles = {
    starting: '准备发送',
    sending: '发送中',
    completed: '发送完成',
    partial: '部分发送（有未发出的岗位，见下）',
    failed: '发送未完成',
    unknown: '状态待核实（读不到平台发送状态，请到平台确认）'
  };
  const sent = Number(batch.sent) || 0;
  const failed = Number(batch.failed) || 0;
  head.append(el('strong', {
    text: `${titles[status] || '发送结果'}：成功 ${sent} 条，失败 ${failed} 条`
  }));
  if (batch.deferred) head.append(badge(`${batch.deferred} 条延后`, 'warn', '…'));
  if (batch.blocked) head.append(badge(`${batch.blocked} 条被阻止`, 'bad', '!'));
  if (batch.unknown) head.append(badge(`${batch.unknown} 条待核实`, 'warn', '?'));
  card.append(head);
  if (status === 'sending' || status === 'starting') {
    const active = snapshot.pipeline.offerpilot && snapshot.pipeline.offerpilot.task;
    if (active && active.mode === 'deliver') {
      const stop = el('button', {
        className: 'button button-quiet button-small',
        text: '停止发送',
        attrs: { type: 'button' }
      });
      stop.addEventListener('click', () => stopQueueDelivery(stop, active.id));
      card.append(stop);
    }
  }
  const list = el('ul', { className: 'queue-delivery-result-list' });
  (batch.items || []).forEach((item) => {
    const row = el('li', { className: 'queue-delivery-result' });
    row.append(el('span', { text: `${item.company || '—'}｜${item.title || '—'}` }));
    const meta = DELIVERY_STATUS_META[String(item.status)] || [String(item.status || '—'), 'neutral', '·'];
    row.append(badge(meta[0], meta[1], meta[2]));
    if (item.error_code) row.append(el('span', { className: 'muted', text: String(item.error_code) }));
    list.append(row);
  });
  card.append(list);
  container.append(card);
}

/* Render: mail */

function renderClassification(container, classification, mail) {
  const info = classification && typeof classification === 'object' ? classification : {};
  const source = mail && typeof mail === 'object' ? mail : {};
  clear(container);
  container.hidden = false;
  container.className = 'action-result action-result-ok';
  container.append(el('p', { className: 'result-title', text: '解析结果' }));
  const list = el('dl', { className: 'detail-list' });
  const pairs = [
    ['intent', `${intentLabel(info.intent)}（${String(info.intent || 'other')}）`],
    ['company', String(info.company || '未识别')],
    ['title', String(info.title || '未识别')],
    ['event_time', info.event_time ? String(info.event_time) : '未识别（不猜测日期）'],
    ['识别把握', formatPercent(info.confidence)],
    ['Message-ID', String(source.message_id || info.message_id || '—')]
  ];
  pairs.forEach(([key, value]) => {
    list.append(el('dt', { text: key }), el('dd', { text: value }));
  });
  container.append(list);

  const links = Array.isArray(info.meeting_links) ? info.meeting_links : [];
  if (links.length) {
    container.append(el('p', { className: 'card-subtitle', text: '会议链接（仅文本，不自动打开）' }));
    const ul = el('ul');
    links.forEach((link) => ul.append(el('li', { className: 'cell-mono', text: String(link) })));
    container.append(ul);
  }

  const anomalies = Array.isArray(info.input_anomalies) ? info.input_anomalies : [];
  if (anomalies.length) {
    container.append(el('p', { className: 'card-subtitle', text: '检测到可疑输入（只当文本显示，不会执行）' }));
    const ul = el('ul');
    anomalies.forEach((item) => {
      const quote = item && typeof item === 'object' ? String(item.quote || '') : String(item);
      const action = item && typeof item === 'object' ? String(item.action || '') : '';
      ul.append(el('li', { text: action ? `${quote} → ${action}` : quote }));
    });
    container.append(ul);
  }

  container.append(el('p', {
    className: 'card-meta',
    text: '离线规则分类；没有读取真实邮箱，也没有发送任何邮件。'
  }));
}

function mailActions(row) {
  const classification = row.classification && typeof row.classification === 'object' ? row.classification : {};
  if (!classification.event_time) {
    return el('span', { className: 'terminal-note', text: '无明确时间' });
  }
  const button = el('button', {
    className: 'button button-small button-quiet',
    text: '生成 .ics',
    attrs: { type: 'button' }
  });
  button.addEventListener('click', async () => {
    const data = await runAction(button, () => postAction('generate-ics', { id: String(row.id) }));
    if (!data) return;
    const ok = announceActionResult(data, '已生成 .ics；请手动导入系统日历。');
    if (ok) {
      showInline(
        dom.mailActionResult,
        data.message || '已生成 .ics；请手动导入系统日历。',
        'ok',
        data.download ? [data.download] : []
      );
      await loadState();
    }
  });
  return button;
}

function renderMails(snapshot) {
  const mails = Array.isArray(snapshot.mails) ? snapshot.mails : [];
  const rows = mails.map((row) => {
    const mail = row.mail && typeof row.mail === 'object' ? row.mail : {};
    const classification = row.classification && typeof row.classification === 'object' ? row.classification : {};
    return [
      el('div', { className: 'cell-text', text: String(mail.subject || '（无主题）') }),
      String(mail.from || '—'),
      formatDateTime(mail.date),
      intentLabel(classification.intent),
      String(classification.company || '未识别'),
      String(classification.title || '未识别'),
      classification.event_time ? String(classification.event_time) : '未识别',
      el('span', { className: 'cell-mono', text: String(mail.message_id || row.id || '—') }),
      mailActions(row)
    ];
  });
  renderTable(dom.mailList, {
    caption: '表：已解析邮件',
    columns: ['主题', '发件人', '日期', '意图', '公司', '岗位', 'event_time', 'Message-ID', '操作'],
    rows,
    emptyText: '还没有解析过邮件。粘贴主题与正文后，会在这里看到分类结果。',
    className: 'data-table-wide'
  });
  renderHrConversations();
  const mailView = document.getElementById('view-mail');
  if (mailView && !mailView.hidden) ensureHrConversationsLoaded();
}

/* Render: HR conversations（页面内单条回复，发送前必须确认） */

const HR_REPLY_CONFIRM_PHRASE = '确认发送这条回复';

function hrConversationById(id) {
  const key = String(id || '');
  if (!key) return null;
  return state.hrConversations.find((row) => String((row && row.id) || '') === key) || null;
}

function hrConversationHasReply(conversation) {
  const id = String((conversation && conversation.id) || '');
  const cached = state.hrThreads[id];
  if (cached && Array.isArray(cached.messages)) {
    return cached.messages.some((message) => message && message.sender === 'hr');
  }
  return Boolean(conversation && (conversation.unread || conversation.last_message));
}

/* hr-inbox:start（tools/tests/test_hr_inbox.py 会截取本段用 node 执行） */
// 各平台把最近消息时间给成不同的展示文本（“11-16 10:20”“昨天”“09:20”），
// 这里只做排序用的粗解析；解析不出来的排在最后，保持原有顺序。
function hrMessageTime(value, now) {
  const text = String(value || '').trim();
  if (!text) return NaN;
  const ref = now instanceof Date && !Number.isNaN(now.getTime()) ? now : new Date();
  const stamp = (year, month, day, hour, minute) =>
    new Date(year, month - 1, day, hour || 0, minute || 0).getTime();
  let match = text.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?/);
  if (match) {
    return stamp(+match[1], +match[2], +match[3], +match[4] || 0, +match[5] || 0);
  }
  match = text.match(/^(\d{1,2})[-/.](\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?/);
  if (match) {
    const month = +match[1];
    const day = +match[2];
    let year = ref.getFullYear();
    if (month > ref.getMonth() + 1 || (month === ref.getMonth() + 1 && day > ref.getDate() + 1)) {
      year -= 1;
    }
    return stamp(year, month, day, +match[3] || 0, +match[4] || 0);
  }
  match = text.match(/^(\d{1,2}):(\d{2})/);
  if (match) {
    return stamp(ref.getFullYear(), ref.getMonth() + 1, ref.getDate(), +match[1], +match[2]);
  }
  if (/(刚刚|刚才)/.test(text)) return ref.getTime();
  match = text.match(/(\d+)\s*分钟前/);
  if (match) return ref.getTime() - (+match[1]) * 60000;
  match = text.match(/(\d+)\s*小时前/);
  if (match) return ref.getTime() - (+match[1]) * 3600000;
  const relative = text.match(/(前天|昨天|今天)[^\d]*(\d{1,2}):(\d{2})/);
  if (relative) {
    const offset = relative[1] === '前天' ? -2 : relative[1] === '昨天' ? -1 : 0;
    const day = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate() + offset);
    return stamp(day.getFullYear(), day.getMonth() + 1, day.getDate(), +relative[2], +relative[3]);
  }
  if (/前天/.test(text)) {
    const day = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate() - 2);
    return stamp(day.getFullYear(), day.getMonth() + 1, day.getDate(), 0, 0);
  }
  if (/昨天/.test(text)) {
    const day = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate() - 1);
    return stamp(day.getFullYear(), day.getMonth() + 1, day.getDate(), 0, 0);
  }
  // 只接受带时区的完整 ISO 串；不对任意文本调用 Date 构造，避免 "3" 之类被解析成无关日期。
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text)) {
    const iso = new Date(text);
    return Number.isNaN(iso.getTime()) ? NaN : iso.getTime();
  }
  return NaN;
}

// 回复页暂不展示前程无忧；接口仍照常返回它的状态，只在展示层隐藏。
function hrPlatformHidden(platform) {
  return String(platform || '').toLowerCase() === '51job';
}

function sortHrConversationsByRecent(rows, now = new Date()) {
  return (Array.isArray(rows) ? rows : [])
    .map((row, index) => ({ row, index, time: hrMessageTime(row && row.last_message_at, now) }))
    .sort((a, b) => {
      const aValid = Number.isFinite(a.time);
      const bValid = Number.isFinite(b.time);
      if (aValid !== bValid) return aValid ? -1 : 1;
      if (aValid && bValid && a.time !== b.time) return b.time - a.time;
      return a.index - b.index;
    })
    .map((entry) => entry.row);
}
/* hr-inbox:end */

/* HR 会话页：摘要 / 同步状态 / 未读角标
   本地存储优先：列表和对话先显示已有内容，平台的增量同步只静默在后台跑。 */

const HR_VISIBLE_PLATFORMS = ['boss', 'zhilian', 'liepin'];
const HR_SUMMARY_URL = '/api/offerpilot/conversations/summary';
const HR_SYNC_URL = '/api/offerpilot/conversations/sync';
const HR_POLL_INTERVAL = 60000;
const HR_SYNC_POLL_INTERVAL = 2500;
const HR_SYNC_TIMEOUT = 45000;
const HR_ENTER_SYNC_THROTTLE = 20000;

function hrPad(value) {
  return String(value).padStart(2, '0');
}

function hrClockLabel(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    const fallback = text.match(/(\d{1,2}):(\d{2})/);
    return fallback ? `${hrPad(fallback[1])}:${fallback[2]}` : '';
  }
  const clock = `${hrPad(date.getHours())}:${hrPad(date.getMinutes())}`;
  const now = new Date();
  return date.toDateString() === now.toDateString()
    ? clock
    : `${date.getMonth() + 1}-${date.getDate()} ${clock}`;
}

function hrConversationTimeLabel(value) {
  const stamp = hrMessageTime(value);
  if (!Number.isFinite(stamp)) return '';
  const date = new Date(stamp);
  const now = new Date();
  const clock = `${hrPad(date.getHours())}:${hrPad(date.getMinutes())}`;
  if (date.toDateString() === now.toDateString()) return clock;
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1}-${date.getDate()} ${clock}`;
  }
  return `${date.getFullYear()}-${hrPad(date.getMonth() + 1)}-${hrPad(date.getDate())}`;
}

function hrMessageStamp(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  const compact = hrConversationTimeLabel(text);
  if (compact) return compact;
  const full = formatDateTime(text);
  return full === '—' ? '' : full;
}

function hrUnreadFromConversations() {
  return (Array.isArray(state.hrConversations) ? state.hrConversations : [])
    .filter((row) => row && row.unread && !hrPlatformHidden(row.platform))
    .length;
}

function hrSetNavUnread(count) {
  const total = Math.max(0, toInt(count));
  state.hrUnreadTotal = total;
  if (!dom.hrNavUnread) return;
  dom.hrNavUnread.hidden = total === 0;
  dom.hrNavUnread.textContent = total > 99 ? '99+' : String(total);
  dom.hrNavUnread.setAttribute('aria-label', total ? `${total} 条未读 HR 消息` : '没有未读 HR 消息');
}

function hrRenderSyncStatus() {
  if (!dom.hrSyncStatus) return;
  const clock = hrClockLabel(state.hrLastSyncedAt);
  let text = '尚未同步';
  let status = 'idle';
  if (state.hrSyncing) {
    text = clock ? `上次同步 ${clock}，正在同步` : '正在同步…';
    status = 'syncing';
  } else if (clock) {
    text = `上次同步 ${clock}，已是最新`;
    status = 'ok';
  }
  dom.hrSyncStatus.dataset.state = status;
  dom.hrSyncStatus.setAttribute('aria-label', text);
  if (dom.hrSyncText) dom.hrSyncText.textContent = text;
  hrUpdateRefreshButton();
}

// 同步结束后必须把刷新按钮恢复可用：只靠 renderHrConversations 会漏掉这一步。
function hrUpdateRefreshButton() {
  if (!dom.hrRefresh) return;
  const busy = Boolean(state.hrConversationsLoading || state.hrSyncing);
  dom.hrRefresh.disabled = busy;
  dom.hrRefresh.setAttribute('aria-busy', busy ? 'true' : 'false');
  dom.hrRefresh.textContent = state.hrSyncing ? '正在同步…' : '刷新会话';
}

function hrSetMobilePane(pane) {
  state.hrMobilePane = pane === 'thread' ? 'thread' : 'list';
  if (dom.hrLayout) dom.hrLayout.dataset.hrPane = state.hrMobilePane;
}

function hrOnMailView() {
  const view = document.getElementById('view-mail');
  return Boolean(view && !view.hidden);
}

function hrPageVisible() {
  return document.visibilityState !== 'hidden';
}

// 新接口可能还没落到本机后端；404/405 时安静退回旧的会话列表接口。
async function hrRequestJson(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 404 || response.status === 405) {
    const error = new Error(`本机后端还没有这个接口（HTTP ${response.status}）。`);
    error.missing = true;
    throw error;
  }
  return parseResponse(response);
}

function hrPlatformStatusRows() {
  const summary = state.hrPlatformSummary && typeof state.hrPlatformSummary === 'object'
    ? state.hrPlatformSummary
    : {};
  const counts = {};
  state.hrConversations.forEach((row) => {
    if (!row || hrPlatformHidden(row.platform)) return;
    const key = String(row.platform || 'boss');
    counts[key] = (counts[key] || 0) + 1;
  });
  return HR_VISIBLE_PLATFORMS.map((platform) => {
    const entry = summary[platform] && typeof summary[platform] === 'object' ? summary[platform] : null;
    return {
      platform,
      count: entry && entry.count !== undefined ? toInt(entry.count) : (counts[platform] || 0),
      unread: entry && entry.unread !== undefined ? toInt(entry.unread) : 0,
      source: String((entry && entry.source) || ''),
      clock: hrClockLabel(entry && entry.last_synced_at),
      error: String((entry && entry.error) || state.hrPlatformErrors[platform] || '')
    };
  });
}

// 每个平台一个紧凑 chip：平时只显示会话数；同步时间、来源和错误原因放进 title 与读屏文案。
// 失败只标这一个平台，不影响其他平台。
// 平台状态条只占一行，用平台惯用的短名；全名保留在 title / aria-label 中。
const HR_PLATFORM_SHORT_LABELS = { boss: 'BOSS', zhilian: '智联', liepin: '猎聘' };

function hrPlatformShortLabel(platform) {
  const key = String(platform || '');
  return HR_PLATFORM_SHORT_LABELS[key] || channelLabel(key);
}

function renderHrPlatformStatus(unavailable) {
  if (!dom.hrPlatformStatus) return;
  clear(dom.hrPlatformStatus);
  dom.hrPlatformStatus.hidden = Boolean(unavailable);
  if (unavailable) return;
  const rows = hrPlatformStatusRows();
  dom.hrPlatformStatus.hidden = !rows.length;
  rows.forEach((row) => {
    // 读取失败但屏幕上仍有缓存时，写明「已显示缓存」；只有完全没有缓存才叫「未读取」。
    const hasCache = Boolean(row.error) && (Number(row.count) || 0) > 0;
    const cacheText = state.hrSyncing ? '已显示缓存，正在同步' : '已显示缓存';
    const node = el('div', { className: `hr-platform-row${row.error ? ' is-error' : ''}` });
    // 缓存还在时这一格不算失败态，避免整条 chip 变红。
    if (hasCache) node.classList.remove('is-error');
    const sourceLabel = row.source === 'api' ? '接口同步' : row.source === 'dom' ? '网页同步' : '';
    const detailText = row.error
      ? (hasCache ? `${cacheText}；${row.error}` : row.error)
      : [
        `${row.count} 个会话`,
        row.unread ? `${row.unread} 未读` : '',
        row.clock ? `已同步 ${row.clock}` : '',
        sourceLabel
      ].filter(Boolean).join('，');
    node.setAttribute('title', detailText);
    node.setAttribute('aria-label', `${channelLabel(row.platform)}：${detailText}`);
    node.append(el('span', { className: 'hr-platform-row-name' }, [
      el('span', { className: 'hr-platform-dot', attrs: { 'aria-hidden': 'true' } }),
      el('span', { className: 'hr-platform-row-label', text: hrPlatformShortLabel(row.platform) })
    ]));
    node.append(el('span', {
      className: 'hr-platform-row-detail',
      text: row.error ? (hasCache ? cacheText : '未读取') : String(row.count)
    }));
    dom.hrPlatformStatus.append(node);
  });
}

async function hrLoadSummary() {
  if (state.hrSummaryLoading) return null;
  state.hrSummaryLoading = true;
  const mode = state.mode;
  try {
    const data = await hrRequestJson(`${HR_SUMMARY_URL}?mode=${encodeURIComponent(mode)}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });
    if (state.mode !== mode) return null;
    state.hrSyncSupported = true;
    state.hrSummary = data && typeof data === 'object' ? data : {};
    state.hrPlatformSummary = state.hrSummary.by_platform && typeof state.hrSummary.by_platform === 'object'
      ? state.hrSummary.by_platform
      : {};
    if (state.hrSummary.last_synced_at) {
      state.hrLastSyncedAt = String(state.hrSummary.last_synced_at);
    }
    hrSetNavUnread(toInt(state.hrSummary.unread_total));
    hrRenderSyncStatus();
    renderHrPlatformStatus(state.hrAvailable === false);
    // 调用方靠返回值判断后台 worker 是否全部结束；读取失败时返回 null。
    return state.hrSummary;
  } catch (error) {
    if (state.mode !== mode) return null;
    if (error && error.missing) {
      state.hrSyncSupported = false;
      state.hrPlatformSummary = {};
      hrSetNavUnread(hrUnreadFromConversations());
      renderHrPlatformStatus(state.hrAvailable === false);
    }
    return null;
  } finally {
    state.hrSummaryLoading = false;
  }
}

function hrSleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

// 平台命中同步冷却时的轻提示：只收起自己这条，不覆盖别的状态。
function hrShowCooldownHint() {
  showHrStatus('刚同步过，已是最新', true);
  window.clearTimeout(state.hrNoticeTimer);
  state.hrNoticeTimer = window.setTimeout(() => {
    state.hrNoticeTimer = 0;
    if (dom.hrStatus && dom.hrStatus.textContent === '刚同步过，已是最新') hideHrStatus();
  }, 4000);
}

// 同步是后台任务：POST 只负责启动。平台命中冷却（started:false + skipped）时
// 立刻结束，不空等到超时；有平台启动后，以摘要里的 syncing 变 false 为完成信号，
// last_synced_at 变化仍作兜底。
async function hrTriggerSync(options = {}) {
  if (state.hrSyncing || state.hrSyncSupported === false) return;
  const manual = Boolean(options.manual);
  state.hrSyncing = true;
  state.hrSyncBaseline = state.hrLastSyncedAt;
  hrRenderSyncStatus();
  const results = await Promise.all(HR_VISIBLE_PLATFORMS.map(async (platform) => {
    try {
      const data = await hrRequestJson(HR_SYNC_URL, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform })
      });
      const body = data && typeof data === 'object' ? data : {};
      const skipped = Array.isArray(body.skipped) ? body.skipped.map(String) : [];
      return {
        platform,
        missing: false,
        started: Boolean(body.started),
        skipped: skipped.includes(platform) || skipped.includes('all')
      };
    } catch (error) {
      return {
        platform,
        missing: Boolean(error && error.missing),
        started: false,
        skipped: false
      };
    }
  }));
  if (results.some((row) => row.missing)) {
    state.hrSyncSupported = false;
    state.hrSyncing = false;
    hrRenderSyncStatus();
    renderHrPlatformStatus(state.hrAvailable === false);
    return;
  }
  const startedAny = results.some((row) => row.started);
  const skippedAll = results.length > 0 && results.every((row) => row.skipped);
  if (!startedAny) {
    // 没有平台启动 worker：摘要里也没有后台任务时，立即结束，不再轮询。
    const summary = await hrLoadSummary();
    if (!(summary && summary.syncing === true)) {
      state.hrSyncing = false;
      hrRenderSyncStatus();
      renderHrPlatformStatus(state.hrAvailable === false);
      if (manual && skippedAll) hrShowCooldownHint();
      return;
    }
  }
  const startedAt = Date.now();
  let finished = false;
  while (Date.now() - startedAt < HR_SYNC_TIMEOUT) {
    await hrSleep(HR_SYNC_POLL_INTERVAL);
    const summary = await hrLoadSummary();
    if (state.hrSyncSupported === false) break;
    if (summary && typeof summary.syncing === 'boolean') {
      // 以 syncing 为准：单个平台先完成时 last_synced_at 会提前变化，不能据此收尾。
      if (summary.syncing === false) {
        finished = true;
        break;
      }
    } else if (state.hrLastSyncedAt && state.hrLastSyncedAt !== state.hrSyncBaseline) {
      // 摘要没有 syncing 字段时才退回时间戳判断。
      finished = true;
      break;
    }
  }
  await loadHrConversations({ quiet: true });
  await hrLoadSummary();
  if (finished && state.hrSelectedId) await loadHrThread(state.hrSelectedId, { quiet: true });
  state.hrSyncing = false;
  hrRenderSyncStatus();
  renderHrPlatformStatus(state.hrAvailable === false);
}

// 「刷新会话」与空状态入口共用：本地列表留在屏幕上，平台同步在后台跑。
function hrRefreshAll(manual = true) {
  hrLoadSummary();
  return Promise.resolve(ensureHrConversationsLoaded(true)).then(() => {
    if (state.hrSyncSupported !== false) hrTriggerSync({ manual });
  });
}

// 进入 HR 页：先显示本地已有会话，再静默触发一次增量同步。
function hrEnterPage() {
  hrSetMobilePane('list');
  // 摘要和本地列表并行读取；两者都回来后再决定是否启动同步。
  const summary = hrLoadSummary();
  Promise.resolve(ensureHrConversationsLoaded()).then(() => summary).then(() => {
    const now = Date.now();
    if (now - state.hrSyncTriggeredAt < HR_ENTER_SYNC_THROTTLE) return;
    state.hrSyncTriggeredAt = now;
    hrTriggerSync();
  });
}

async function hrPollTick() {
  if (!hrPageVisible() || state.hrPollBusy) return;
  state.hrPollBusy = true;
  try {
    await hrLoadSummary();
    if (!hrOnMailView()) return;
    // 每次轮询只读本地摘要与本地缓存；平台同步最多每 5 分钟触发一次。
    await loadHrConversations({ quiet: true, refreshThread: true });
    if (state.hrSyncSupported === false) return;
    const now = Date.now();
    const platformSyncEvery = HR_POLL_INTERVAL * 5;
    if (now - (hrPollTick.lastPlatformSyncAt || 0) < platformSyncEvery) return;
    hrPollTick.lastPlatformSyncAt = now;
    await hrTriggerSync();
  } finally {
    state.hrPollBusy = false;
  }
}

function hrStartPolling() {
  if (state.hrPollTimer) return;
  state.hrPollTimer = window.setInterval(hrPollTick, HR_POLL_INTERVAL);
  document.addEventListener('visibilitychange', () => {
    if (!hrPageVisible()) return;
    hrLoadSummary();
    if (hrOnMailView()) hrPollTick();
  });
  hrLoadSummary();
}

function filteredHrConversations() {
  const query = state.hrSearch.trim().toLowerCase();
  return state.hrConversations.filter((conversation) => {
    if (!conversation) return false;
    if (hrPlatformHidden(conversation.platform)) return false;
    if (state.hrPlatform !== 'all' && String(conversation.platform || 'boss') !== state.hrPlatform) return false;
    if (state.hrFilter === 'unread' && !conversation.unread) return false;
    if (state.hrFilter === 'replied' && !hrConversationHasReply(conversation)) return false;
    if (!query) return true;
    return [conversation.company, conversation.title, conversation.hr_name, conversation.hr_title, conversation.last_message]
      .some((value) => String(value || '').toLowerCase().includes(query));
  });
}

function hrPlatformErrorsFrom(data) {
  const errors = {};
  const source = data && data.errors && typeof data.errors === 'object' ? data.errors : {};
  Object.entries(source).forEach(([platform, message]) => {
    if (message) errors[String(platform)] = String(message);
  });
  if (!Object.keys(errors).length && data && Array.isArray(data.platforms)) {
    data.platforms.forEach((row) => {
      if (row && row.platform && row.error) errors[String(row.platform)] = String(row.error);
    });
  }
  return errors;
}

function showHrStatus(message, accent) {
  if (!dom.hrStatus) return;
  dom.hrStatus.hidden = false;
  dom.hrStatus.className = `notice hr-notice${accent ? ' notice-accent' : ''}`;
  dom.hrStatus.textContent = message;
}

function hideHrStatus() {
  if (!dom.hrStatus) return;
  dom.hrStatus.hidden = true;
  dom.hrStatus.textContent = '';
}

// 读取失败只挂在对应平台上；其他平台的会话不受影响，继续显示。
function renderHrPlatformErrors(unavailable) {
  if (!dom.hrPlatformErrors) return;
  clear(dom.hrPlatformErrors);
  const entries = (unavailable ? [] : Object.entries(state.hrPlatformErrors || {}))
    .filter(([platform]) => !hrPlatformHidden(platform));
  dom.hrPlatformErrors.hidden = !entries.length;
  if (!entries.length) return;
  // 平时只占一行；需要看原因时再展开，避免侧栏被错误文案撑高。
  const details = el('details', { className: 'hr-platform-errors-details' });
  details.append(el('summary', {
    className: 'hr-platform-errors-summary',
    text: `${entries.length} 个平台未读取，其他平台照常显示`
  }));
  const list = el('div', { className: 'hr-platform-errors-list' });
  entries.forEach(([platform, reason]) => {
    list.append(el('p', {
      className: 'hr-platform-error',
      text: `${channelLabel(platform)}未读取：${reason}`
    }));
  });
  details.append(list);
  dom.hrPlatformErrors.append(details);
}

function renderHrConversations() {
  if (!dom.hrConversationList) return;
  const unavailable = state.hrAvailable === false;
  if (hrPlatformHidden(state.hrPlatform)) state.hrPlatform = 'all';
  if (unavailable) {
    showHrStatus(
      `${state.hrReason || 'HR 会话暂不可用。'} 请先在本机 Chrome 登录各招聘平台（BOSS / 智联 / 猎聘）、打开调试端口，再点「刷新会话」。`,
      false
    );
  } else if (state.hrConversationsLoading && !state.hrConversations.length) {
    showHrStatus('正在读取本机会话…', true);
  } else {
    hideHrStatus();
  }
  renderHrPlatformErrors(unavailable);
  renderHrPlatformStatus(unavailable);
  hrRenderSyncStatus();
  if (state.hrSyncSupported === false) {
    hrSetNavUnread(unavailable ? 0 : hrUnreadFromConversations());
  }
  hrUpdateRefreshButton();
  if (dom.hrPlatformSelect && dom.hrPlatformSelect.value !== state.hrPlatform) {
    dom.hrPlatformSelect.value = state.hrPlatform;
  }
  dom.hrFilterButtons.forEach((button) => {
    const active = button.dataset.hrFilter === state.hrFilter;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  if (dom.hrSearch && dom.hrSearch.value !== state.hrSearch && document.activeElement !== dom.hrSearch) {
    dom.hrSearch.value = state.hrSearch;
  }

  // 所有平台的会话合并在一个收件箱里，最近有消息的排在前面。
  const conversations = unavailable ? [] : sortHrConversationsByRecent(filteredHrConversations());
  if (dom.hrConversationCount) {
    dom.hrConversationCount.textContent = unavailable ? '0 个会话' : `${conversations.length} 个会话`;
  }
  // 列表签名只包含会影响行内容与选中的字段；签名不变时保留已渲染的行，
  // 后台同步不再整段清空重建，滚动位置和键盘焦点也不会丢。
  const signature = JSON.stringify({
    selected: state.hrSelectedId,
    filter: state.hrFilter,
    platform: state.hrPlatform,
    search: state.hrSearch,
    unavailable,
    rows: conversations.map((conversation) => [
      String(conversation.id || ''),
      conversation.hr_name, conversation.hr_title, conversation.company, conversation.title,
      conversation.platform, Boolean(conversation.unread),
      conversation.last_message, conversation.last_message_at
    ])
  });
  if (!conversations.length) {
    state.hrConversationListSignature = '';
    state.hrConversationListCount = -1;
    clear(dom.hrConversationList);
    let emptyText = '还没有 HR 会话。';
    if (unavailable) emptyText = '读不到 HR 会话。';
    else if (state.hrConversations.length) emptyText = '没有符合条件的会话。';
    else if (state.hrConversationsLoading) emptyText = '正在读取本机会话…';
    const empty = el('div', { className: 'hr-empty-block sg-empty' });
    empty.append(el('p', { className: 'hr-empty sg-empty-text', text: emptyText }));
    if (unavailable) {
      empty.append(el('p', { className: 'hr-empty-hint', text: '请先在本机 Chrome 登录各招聘平台，再重新读取。' }));
      empty.append(hrEmptyAction('重新读取会话'));
    } else if (state.hrConversationsLoading && !state.hrConversations.length) {
      empty.append(el('p', { className: 'hr-empty-hint', text: '读完后会自动显示，不用留在这个页面等。' }));
    } else if (!state.hrConversations.length) {
      empty.append(el('p', {
        className: 'hr-empty-hint',
        text: '进入这一页会自动在后台同步一次；也可以现在刷新。'
      }));
      empty.append(hrEmptyAction('刷新会话'));
    } else {
      empty.append(el('p', { className: 'hr-empty-hint', text: '换一个平台或筛选条件试试。' }));
    }
    dom.hrConversationList.append(empty);
  } else if (
    signature === state.hrConversationListSignature
    && state.hrConversationListCount === conversations.length
    && dom.hrConversationList.querySelector('.hr-conversation')
  ) {
    // 列表没有变化：保持原样，只更新上方状态条与计数。
  } else {
    state.hrConversationListSignature = signature;
    state.hrConversationListCount = conversations.length;
    clear(dom.hrConversationList);
    conversations.forEach((conversation) => {
      const id = String(conversation.id || '');
      const active = id === state.hrSelectedId;
      const unread = Boolean(conversation.unread);
      const top = el('span', { className: 'hr-conversation-top' });
      if (unread) top.append(el('span', { className: 'hr-unread-dot', attrs: { 'aria-hidden': 'true' } }));
      top.append(el('strong', { className: 'hr-conversation-hr', text: String(conversation.hr_name || 'HR') }));
      const platformLabel = channelLabel(conversation.platform);
      const tags = el('span', { className: 'hr-conversation-tags' });
      if (conversation.platform) {
        tags.append(el('span', {
          className: `hr-platform-badge sg-platform-tag sg-platform-${String(conversation.platform)}`,
          attrs: { title: platformLabel }
        }, [
          el('span', { className: 'sg-platform-mark', text: platformLabel.slice(0, 1) }),
          el('span', { className: 'sg-platform-name', text: platformLabel })
        ]));
      }
      if (tags.childNodes.length) top.append(tags);
      const timeLabel = hrConversationTimeLabel(conversation.last_message_at);
      if (timeLabel) top.append(el('span', { className: 'hr-conversation-time', text: timeLabel }));
      const item = el('button', {
        className: `hr-conversation${active ? ' is-active' : ''}${unread ? ' is-unread' : ''}`,
        attrs: {
          type: 'button',
          'aria-current': active ? 'true' : 'false',
          'aria-label': `${conversation.hr_name || 'HR'}，${conversation.company || '未填写公司'}，${conversation.title || '未填写岗位'}，${platformLabel}${unread ? '，未读' : ''}`
        }
      }, [
        top,
        el('span', {
          className: 'hr-conversation-sub',
          text: [conversation.company, conversation.title].filter(Boolean).join('，')
            || conversation.hr_title
            || '—'
        }),
        el('span', { className: 'hr-conversation-bottom' }, [
          el('span', {
            className: 'hr-conversation-last',
            text: String(conversation.last_message || '暂无消息')
          })
        ])
      ]);
      item.addEventListener('click', () => selectHrConversation(id));
      dom.hrConversationList.append(item);
    });
  }
  renderHrThread();
}

// 空状态里的刷新入口和顶部按钮走同一条路径：先显示本地缓存，再后台同步。
function hrEmptyAction(label) {
  const button = el('button', {
    className: 'button button-quiet button-small hr-empty-action',
    attrs: { type: 'button' },
    text: label
  });
  button.addEventListener('click', () => hrRefreshAll());
  return button;
}

function hrConversationScore(conversation) {
  const direct = conversation && (conversation.score !== undefined
    ? conversation.score
    : conversation.job_score !== undefined
      ? conversation.job_score
      : conversation.match_score);
  if (direct !== undefined && direct !== null && direct !== '' && Number.isFinite(Number(direct))) {
    return Number(direct);
  }
  const jobId = String((conversation && conversation.job_id) || '');
  if (!jobId) return null;
  const jobs = state.snapshot && Array.isArray(state.snapshot.jobs) ? state.snapshot.jobs : [];
  const job = jobs.find((row) => String((row && row.id) || '') === jobId);
  const score = job ? job.score : undefined;
  if (score === undefined || score === null || score === '') return null;
  return Number.isFinite(Number(score)) ? Number(score) : null;
}

function renderHrJobCard(conversation) {
  if (!dom.hrDetailJob) return;
  clear(dom.hrDetailJob);
  if (!conversation || !conversation.job_id) {
    dom.hrDetailJob.append(el('span', { className: 'hr-job-empty', text: '未关联岗位' }));
    return;
  }
  const score = hrConversationScore(conversation);
  const body = el('div', { className: 'hr-job-card-body' });
  body.append(el('span', { className: 'hr-job-card-label', text: '关联岗位' }));
  body.append(el('strong', {
    className: 'hr-job-card-title',
    text: [conversation.company, conversation.title].filter(Boolean).join('，') || '已关联岗位'
  }));
  body.append(el('span', {
    className: 'hr-job-card-score',
    text: score === null ? '未评分' : `匹配 ${formatScore(score)}`
  }));
  const jobButton = el('button', {
    className: 'button button-quiet button-small',
    attrs: { type: 'button' },
    text: '查看岗位'
  });
  jobButton.addEventListener('click', () => jumpToHrJob(conversation));
  dom.hrDetailJob.append(el('div', { className: 'hr-job-card' }, [body, jobButton]));
}

// 平台会把同一段系统提示重复塞进消息流；按消息 id 去重，没有 id 的按「文字 + 时间」。
function dedupeHrMessages(messages) {
  const seen = new Set();
  return messages.filter((message) => {
    if (!message) return false;
    const id = message.mid || message.id || message.message_id || '';
    const key = id
      ? `id:${String(id)}`
      : `text:${String(message.text || '')}\u0000${String(message.time || '')}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// 一条消息一个气泡；后台刷新时只追加新消息，已在屏幕上的气泡不动。
function hrMessageNode(message, conversation, startOfGroup) {
  const sender = String((message && message.sender) || 'system');
  const kind = sender === 'hr' ? 'hr' : sender === 'me' ? 'me' : 'system';
  const bubble = el('article', {
    className: `hr-message hr-message-${kind}${startOfGroup ? ' hr-message-start' : ''}`,
    attrs: { 'data-sender': kind }
  });
  const who = kind === 'hr' ? (conversation.hr_name || 'HR') : kind === 'me' ? '我' : '系统';
  const stamp = hrMessageStamp(message && message.time);
  // HR 的气泡需要标出是谁；自己的消息只留时间，省掉“我，”这种多余前缀。
  bubble.append(el('p', {
    className: 'hr-message-meta',
    text: kind === 'hr' ? (stamp ? `${who}，${stamp}` : who) : (stamp || who)
  }));
  const fullText = String((message && message.text) || '');
  // 系统提示常是一大段平台原话；列表里只留摘要，完整内容放在 title。
  const shortText = kind === 'system' ? truncate(fullText, 120) : fullText;
  const textNode = el('p', { className: 'hr-message-text', text: shortText });
  if (shortText !== fullText) textNode.title = fullText;
  bubble.append(textNode);
  return bubble;
}

function appendHrMessages(rows, allMessages, offset, conversation) {
  rows.forEach((message, index) => {
    const absolute = offset + index;
    const previous = absolute > 0 && allMessages ? allMessages[absolute - 1] : null;
    const sender = String((message && message.sender) || 'system');
    const previousSender = String((previous && previous.sender) || 'system');
    dom.hrMessages.append(hrMessageNode(message, conversation, absolute > 0 && sender !== previousSender));
  });
}

function renderHrThread() {
  if (!dom.hrMessages) return;
  const conversation = state.hrThread && state.hrThread.conversation
    ? state.hrThread.conversation
    : hrConversationById(state.hrSelectedId);
  // 后台刷新只追加内容：用户正往上翻时不跳回底部。
  const viewport = dom.hrMessages;
  const atBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= 32;
  const previousTop = viewport.scrollTop;
  clear(dom.hrDetailJob);
  if (!conversation) {
    clear(dom.hrMessages);
    state.hrThreadRenderedKey = '';
    state.hrThreadRenderedMessages = null;
    dom.hrDetailTitle.textContent = '选择一个 HR 会话';
    dom.hrDetailMeta.textContent = '';
    if (dom.hrReplyInput) dom.hrReplyInput.value = '';
    if (dom.hrReplyInput) dom.hrReplyInput.disabled = true;
    if (dom.hrReplySend) dom.hrReplySend.disabled = true;
    if (dom.hrDraftCount) dom.hrDraftCount.textContent = '0 字';
    if (dom.hrReplyBlockReason) {
      dom.hrReplyBlockReason.hidden = true;
      dom.hrReplyBlockReason.textContent = '';
    }
    dom.hrDetailJob.append(el('span', { className: 'hr-job-empty', text: '未关联岗位' }));
    dom.hrMessages.append(el('div', { className: 'hr-empty-block sg-empty' }, [
      el('p', { className: 'hr-empty sg-empty-text', text: '从左侧选择一位 HR，查看完整对话。' }),
      hrEmptyAction('刷新会话')
    ]));
    return;
  }
  const key = String(conversation.id || '');
  dom.hrDetailTitle.textContent = String(conversation.hr_name || 'HR');
  dom.hrDetailMeta.textContent = [
    conversation.platform ? channelLabel(conversation.platform) : '',
    conversation.hr_title
  ].filter(Boolean).join('，');
  renderHrJobCard(conversation);

  const thread = state.hrThread && state.hrThread.conversation
    && String(state.hrThread.conversation.id) === key
    ? state.hrThread
    : null;
  const messages = thread && Array.isArray(thread.messages)
    ? dedupeHrMessages(thread.messages)
    : [];
  const signatures = messages.map((message) => JSON.stringify([
    String((message && message.sender) || 'system'),
    String((message && message.time) || ''),
    String((message && message.text) || '')
  ]));
  const previousMessages = state.hrThreadRenderedKey === key
    && Array.isArray(state.hrThreadRenderedMessages)
    ? state.hrThreadRenderedMessages
    : [];
  const renderedNodes = dom.hrMessages.querySelectorAll('.hr-message').length;
  const canAppend = Boolean(messages.length)
    && previousMessages.length > 0
    && previousMessages.length <= messages.length
    && renderedNodes === previousMessages.length
    && previousMessages.every((signature, index) => signature === signatures[index]);
  if (!messages.length) {
    clear(dom.hrMessages);
    state.hrThreadRenderedMessages = [];
    const empty = el('div', { className: 'hr-empty-block sg-empty' });
    empty.append(el('p', {
      className: 'hr-empty sg-empty-text',
      text: state.hrThreadLoading ? '正在读取对话…' : '这个会话还没有消息。'
    }));
    if (!state.hrThreadLoading) {
      empty.append(el('p', {
        className: 'hr-empty-hint',
        text: '如果你刚在平台上回复过，可以让工作台重新读一次。'
      }));
      const refresh = el('button', {
        className: 'button button-quiet button-small',
        text: '刷新这个会话',
        attrs: { type: 'button' }
      });
      refresh.addEventListener('click', () => loadHrThread(String(conversation.id)));
      empty.append(refresh);
    }
    dom.hrMessages.append(empty);
  } else if (canAppend) {
    // 已有气泡保留，只追加这次新到的消息。
    appendHrMessages(messages.slice(previousMessages.length), messages, previousMessages.length, conversation);
    state.hrThreadRenderedMessages = signatures;
  } else {
    clear(dom.hrMessages);
    appendHrMessages(messages, messages, 0, conversation);
    state.hrThreadRenderedMessages = signatures;
  }
  if (viewport) {
    const switching = state.hrThreadRenderedKey !== key;
    state.hrThreadRenderedKey = key;
    if (switching || atBottom) viewport.scrollTop = viewport.scrollHeight;
    else viewport.scrollTop = previousTop;
  }

  const allowed = Boolean(thread && thread.reply_allowed);
  const blockReason = thread && thread.reply_block_reason ? String(thread.reply_block_reason) : '';
  if (dom.hrReplyBlockReason) {
    dom.hrReplyBlockReason.hidden = allowed;
    dom.hrReplyBlockReason.textContent = allowed
      ? ''
      : (blockReason || (state.hrThreadLoading ? '正在读取对话…' : '当前会话暂时不能回复。'));
  }
  const replyInput = dom.hrReplyInput;
  if (replyInput) {
    replyInput.disabled = !allowed;
    replyInput.placeholder = allowed
      ? '回复 HR；发送前会再确认一次。'
      : state.hrThreadLoading
        ? '正在读取对话…'
        : thread
          ? '这个会话暂时不能回复。'
          : '先选择一个 HR 会话。';
  }
  const draft = state.hrDrafts[key] || '';
  if (dom.hrReplyInput && document.activeElement !== dom.hrReplyInput) {
    dom.hrReplyInput.value = draft;
  }
  updateHrComposerState();
}

function updateHrComposerState() {
  const id = String(state.hrSelectedId || '');
  const draft = String(state.hrDrafts[id] || '');
  const thread = state.hrThread;
  const allowed = Boolean(
    id
    && thread
    && thread.conversation
    && String(thread.conversation.id) === id
    && thread.reply_allowed
  );
  if (dom.hrDraftCount) dom.hrDraftCount.textContent = `${draft.length} 字`;
  if (dom.hrReplyInput) dom.hrReplyInput.disabled = !allowed;
  if (dom.hrReplySend) dom.hrReplySend.disabled = !allowed || !draft.trim();
}

async function ensureHrConversationsLoaded(force = false) {
  if (state.hrMode !== null && state.hrMode !== state.mode) {
    state.hrConversations = [];
    state.hrSelectedId = '';
    state.hrThread = null;
    state.hrThreads = {};
    state.hrConversationsLoaded = false;
    state.hrAvailable = null;
    state.hrReason = '';
    state.hrPlatformErrors = {};
    state.hrSummary = null;
    state.hrPlatformSummary = {};
    state.hrUnreadTotal = 0;
    state.hrLastSyncedAt = '';
    state.hrSyncSupported = null;
    state.hrSyncing = false;
    state.hrThreadRenderedKey = '';
    state.hrThreadRenderedMessages = null;
    state.hrConversationListSignature = '';
    state.hrConversationListCount = -1;
  }
  if (!force && state.hrConversationsLoaded && state.hrMode === state.mode) return;
  if (state.hrConversationsLoading) return;
  // 已经有会话在屏幕上时，刷新只静默重读本地缓存，不进入加载态、不清空列表。
  await loadHrConversations({ quiet: force && Boolean(state.hrConversations.length) });
}

async function loadHrConversations(options = {}) {
  const mode = state.mode;
  const seq = ++state.hrSeq;
  const quiet = Boolean(options.quiet);
  state.hrConversationsLoading = !quiet;
  if (!quiet) renderHrConversations();
  let data = null;
  try {
    data = await hrRequestJson(
      `/api/offerpilot/conversations?platform=all&mode=${encodeURIComponent(mode)}`,
      {
        method: 'GET',
        headers: { Accept: 'application/json' },
        cache: 'no-store'
      }
    );
    if (seq !== state.hrSeq) return null;
    state.hrMode = mode;
    state.hrConversationsLoaded = true;
    state.hrAvailable = Boolean(data && data.available !== false);
    state.hrReason = String((data && (data.reason || data.error)) || '');
    state.hrPlatformErrors = hrPlatformErrorsFrom(data);
    state.hrConversations = state.hrAvailable && Array.isArray(data.conversations)
      ? data.conversations
      : [];
    if (data && data.last_synced_at) state.hrLastSyncedAt = String(data.last_synced_at);
    if (!state.hrAvailable) {
      state.hrSelectedId = '';
      state.hrThread = null;
      state.hrThreads = {};
    } else if (!hrConversationById(state.hrSelectedId)) {
      const first = sortHrConversationsByRecent(state.hrConversations)[0];
      state.hrSelectedId = first ? String(first.id || '') : '';
      state.hrThread = null;
      if (state.hrSelectedId) loadHrThread(state.hrSelectedId, { quiet: true });
    } else if (options.refreshThread) {
      loadHrThread(state.hrSelectedId, { quiet: true });
    }
    if (state.hrSyncSupported === false) hrSetNavUnread(hrUnreadFromConversations());
  } catch (error) {
    if (seq !== state.hrSeq) return null;
    // 后台刷新失败时保留已显示的本地会话；首次读取失败才整体标为不可用。
    if (!quiet || !state.hrConversations.length) {
      state.hrMode = mode;
      state.hrConversationsLoaded = true;
      state.hrAvailable = false;
      state.hrReason = `读取会话失败：${friendlyError(error)}`;
      state.hrConversations = [];
      state.hrSelectedId = '';
      state.hrThread = null;
      state.hrThreads = {};
      state.hrPlatformErrors = {};
    }
    if (error && error.missing) state.hrSyncSupported = false;
  } finally {
    if (seq === state.hrSeq) {
      state.hrConversationsLoading = false;
      renderHrConversations();
    }
  }
  return data;
}

async function loadHrThread(id, options = {}) {
  const mode = state.mode;
  const key = String(id || '');
  if (!key) return;
  const selected = hrConversationById(key);
  const platform = String(
    (selected && selected.platform)
    || (state.hrThread && state.hrThread.conversation && state.hrThread.conversation.platform)
    || 'all'
  );
  state.hrThreadLoading = true;
  if (!options.quiet) renderHrThread();
  try {
    const data = await hrRequestJson(
      `/api/offerpilot/conversation?platform=${encodeURIComponent(platform)}&mode=${encodeURIComponent(mode)}&id=${encodeURIComponent(key)}`,
      { method: 'GET', headers: { Accept: 'application/json' }, cache: 'no-store' }
    );
    if (state.mode !== mode || String(state.hrSelectedId) !== key) return;
    const base = hrConversationById(key) || {};
    const nested = data && data.conversation && typeof data.conversation === 'object'
      ? data.conversation
      : null;
    const flatId = data && data.conversation_id ? String(data.conversation_id) : '';
    const conversation = nested
      ? { ...base, ...nested, id: String(nested.id || flatId || key) }
      : flatId
        ? {
          ...base,
          id: flatId,
          company: String(data.company || base.company || ''),
          title: String(data.title || base.title || '')
        }
        : null;
    state.hrThread = conversation
      ? {
        conversation,
        messages: Array.isArray(data.messages) ? data.messages : [],
        reply_allowed: Boolean(data.reply_allowed),
        reply_block_reason: String(data.reply_block_reason || '')
      }
      : null;
    if (conversation) {
      state.hrThreads[key] = state.hrThread;
      const index = state.hrConversations.findIndex((row) => String((row && row.id) || '') === key);
      if (index >= 0) {
        state.hrConversations[index] = { ...state.hrConversations[index], ...conversation };
      }
    }
  } catch (error) {
    if (state.mode === mode && String(state.hrSelectedId) === key && !options.quiet) {
      state.hrThread = null;
      setStatus(`读取对话失败：${friendlyError(error)}`, 'error');
    }
  } finally {
    if (state.mode === mode && String(state.hrSelectedId) === key) {
      state.hrThreadLoading = false;
      renderHrConversations();
    }
  }
}

function selectHrConversation(id) {
  const key = String(id || '');
  if (!key) return;
  state.hrSelectedId = key;
  // 已读过的会话先显示本机缓存，再在后台增量读取。
  state.hrThread = state.hrThreads[key] || null;
  state.hrThreadLoading = !state.hrThread;
  hrSetMobilePane('thread');
  renderHrConversations();
  loadHrThread(key, { quiet: Boolean(state.hrThread) });
}

function jumpToHrJob(conversation) {
  const jobId = String((conversation && conversation.job_id) || '');
  if (!jobId) return;
  showView('jobs');
  const rows = Array.from(dom.jobsTable.querySelectorAll('tbody tr'));
  const company = String((conversation && conversation.company) || '');
  const title = String((conversation && conversation.title) || '');
  const row = rows.find((candidate) => {
    const cells = candidate.querySelectorAll('td');
    return cells.length > 2
      && cells[1].textContent.includes(company)
      && cells[2].textContent.includes(title);
  });
  if (!row) {
    setStatus('已打开岗位池；当前列表里没有找到对应岗位，可能被筛选或已删除。', 'warn');
    return;
  }
  row.classList.add('hr-target-row');
  row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  window.setTimeout(() => row.classList.remove('hr-target-row'), 2600);
}

function openHrReplyModal(trigger) {
  if (!dom.hrReplyConfirmPanel) return;
  const conversation = state.hrThread && state.hrThread.conversation;
  const id = String(state.hrSelectedId || '');
  const text = String(state.hrDrafts[id] || '');
  if (!conversation || !state.hrThread.reply_allowed || !text.trim()) return;
  // 身份行：姓名 · 职位 · 公司。hr_title 在部分平台就是「hr / 招聘方」，
  // 不再拼进括号重复；职位取会话对应的岗位名。
  const identity = [
    String(conversation.hr_name || 'HR').trim(),
    String(conversation.title || '').trim(),
    String(conversation.company || '').trim()
  ].filter(Boolean).join(' · ');
  dom.hrReplyWho.textContent = identity;
  dom.hrReplyWho.title = identity;
  if (dom.hrReplyPlatform) {
    const platform = String(conversation.platform || '').trim();
    dom.hrReplyPlatform.textContent = platform ? `平台：${channelLabel(platform)}` : '平台未知';
  }
  dom.hrReplyModalText.textContent = text;
  dom.hrReplyModalRisk.checked = true;
  dom.hrReplyModalProgress.textContent = '';
  state.hrReplyBusy = false;
  if (!state.hrReplyModalOpen) {
    state.hrReplyModalOpen = true;
    state.hrReplyReturnFocus = trigger || (document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null);
    document.body.classList.add('hr-modal-open');
    document.addEventListener('keydown', handleHrReplyKeydown);
  }
  if (dom.hrReplyConfirmPanel.parentElement !== document.body) {
    document.body.append(dom.hrReplyConfirmPanel);
  }
  dom.hrReplyConfirmPanel.hidden = false;
  updateHrReplyConfirmState();
  dom.hrReplyModalCancel.focus();
}

function updateHrReplyConfirmState() {
  if (!dom.hrReplyConfirm) return;
  const riskChecked = Boolean(dom.hrReplyModalRisk && dom.hrReplyModalRisk.checked);
  dom.hrReplyConfirm.disabled = !riskChecked || state.hrReplyBusy;
  if (dom.hrReplyModalCancel) dom.hrReplyModalCancel.disabled = state.hrReplyBusy;
  if (dom.hrReplyModalRisk) dom.hrReplyModalRisk.disabled = state.hrReplyBusy;
}

function hrReplyFocusable() {
  if (!dom.hrReplyConfirmPanel) return [];
  return Array.from(dom.hrReplyConfirmPanel.querySelectorAll(
    'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
  )).filter((node) => node.offsetParent !== null || node === document.activeElement);
}

function handleHrReplyKeydown(event) {
  if (!state.hrReplyModalOpen) return;
  if (event.key === 'Escape') {
    if (state.hrReplyBusy) return;
    event.preventDefault();
    closeHrReplyModal();
    return;
  }
  if (event.key !== 'Tab') return;
  const nodes = hrReplyFocusable();
  if (!nodes.length) return;
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function closeHrReplyModal() {
  if (!state.hrReplyModalOpen || !dom.hrReplyConfirmPanel) return;
  if (state.hrReplyBusy) return;
  dom.hrReplyConfirmPanel.hidden = true;
  state.hrReplyModalOpen = false;
  document.body.classList.remove('hr-modal-open');
  document.removeEventListener('keydown', handleHrReplyKeydown);
  const target = state.hrReplyReturnFocus;
  state.hrReplyReturnFocus = null;
  if (target && typeof target.focus === 'function' && document.contains(target) && !target.disabled) {
    target.focus();
  } else if (dom.hrReplySend && !dom.hrReplySend.disabled) {
    dom.hrReplySend.focus();
  }
}

async function submitHrReply() {
  const conversation = state.hrThread && state.hrThread.conversation;
  const id = String(state.hrSelectedId || '');
  const text = String(state.hrDrafts[id] || '');
  if (!conversation || !id || !text.trim()) return;
  if (!dom.hrReplyModalRisk || !dom.hrReplyModalRisk.checked) return;
  state.hrReplyBusy = true;
  updateHrReplyConfirmState();
  dom.hrReplyConfirm.disabled = true;
  dom.hrReplyConfirm.setAttribute('aria-busy', 'true');
  dom.hrReplyModalProgress.textContent = '正在发送这条回复…';
  let data = null;
  let failure = '';
  try {
    data = await postAction('offerpilot-reply', {
      conversation_id: id,
      text,
      confirm: HR_REPLY_CONFIRM_PHRASE,
      risk_acknowledged: true
    });
  } catch (error) {
    failure = friendlyError(error);
  } finally {
    dom.hrReplyConfirm.removeAttribute('aria-busy');
    state.hrReplyBusy = false;
  }
  const status = String((data && data.status) || '');
  const sent = Boolean(data) && data.ok !== false && (status === 'sent' || !status);
  if (sent) {
    state.hrDrafts[id] = '';
    dom.hrReplyModalProgress.textContent = '已发送。';
    closeHrReplyModal();
    setStatus((data && data.message) || '回复已发送。', 'ok');
    await loadHrConversations();
    if (state.hrSelectedId) await loadHrThread(state.hrSelectedId, { quiet: true });
    return;
  }
  const message = data && data.message
    ? String(data.message)
    : failure
      ? failure
      : status === 'blocked'
        ? '平台阻止了这次发送。'
        : '发送失败，请稍后重试。';
  dom.hrReplyModalProgress.textContent = message;
  setStatus(message, status === 'blocked' ? 'warn' : 'error');
  updateHrReplyConfirmState();
}

/* Interview chat (frontend Mock; field shapes match start/stream/reply/library) */

const CHAT_ROUND_LABELS = {
  hr: 'HR',
  business: '业务专业',
  tech: '技术口述',
  manager: '主管'
};
const CHAT_INCOMPLETE_NOTE = '这一问没有说完';
const CHAT_NO_RESUME = '请先在个人资料里填写实习或项目，再开始面试。';
const CHAT_EMPTY_ANSWER = '请填写回答';
const CHAT_EMPTY_MATERIAL = '请粘贴面经或岗位知识正文';
const CHAT_LIBRARY_SAVED = '已保存到本机知识库，之后可以修改或删除。开始面试时不必再勾选。';
const CHAT_WEB_UNAVAILABLE = '这次没有联网补充。面试继续。不会改用套话，也不会编造公司业务或简历里没有的经历。';
const CHAT_WEB_WRITTEN = '已根据公司或岗位从网上补充，并写入知识库（标明来自联网），之后可以改。面经和联网结果不是公司官方标准，也不是你做过的事。';
const CHAT_LIBRARY_KEY_PREFIX = 'offerpilot.interviewLibrary.';
const CHAT_PEER_LABEL = '来自其他公司的同类岗位';
const CHAT_WEB_LABEL = '来自联网';
const CHAT_ROLE_AFFIXES = [
  '实习', '校招', '社招', '应届', '校招生', '暑期', '春招', '秋招',
  '初级', '中级', '高级', '资深', '专家', '助理',
  'intern', 'junior', 'senior', 'staff'
];
const CHAT_GENERIC_ROLE_TOKENS = [
  '工程师', '开发', '专员', '经理', '岗位', '岗', 'engineer', 'developer'
];
const CHAT_ROLE_DIRECTIONS = [
  '产品', '运营', '设计', '前端', '后端', '全栈', '客户端', '移动',
  'ios', 'android', '测试', '数据', '算法', '机器学习', '策略', '研发',
  '销售', '市场', '人力', 'hr', '财务', '法务', '增长', '投放', '内容',
  '游戏', '安全', '运维', '分析', '研究', '咨询',
  'backend', 'frontend', 'fullstack', 'product', 'algorithm'
];
const CHAT_NOT_AN_OFFER = '准备度只表示练习准备程度，不表示录用。';
const CHAT_RESUME_DISCLAIMER = '这些修改点不会自动写入定制简历';
const CHAT_MISSING_EVIDENCE = '证据不足';
const CHAT_READINESS_LABELS = {
  ready: '已准备好练习这一轮',
  almost_ready: '接近准备好，还差一两处补齐',
  needs_practice: '还需要针对缺口再练',
  insufficient_evidence: '这场回答里可核对的证据不足'
};
const CHAT_SCORE_LABELS = {
  hr: ['沟通表达', '协作推进', '职业动机'],
  business: ['需求取舍', '业务理解', '结果表达'],
  tech: ['方案落地', '范围控制', '结果表达'],
  manager: ['优先级判断', '带团队交付', '结果表达']
};

function chatRoundValue() {
  const picked = document.querySelector('input[name="chat-round"]:checked');
  const value = picked ? picked.value : 'business';
  return CHAT_ROUND_LABELS[value] ? value : 'business';
}

function chatDurationValue() {
  const picked = document.querySelector('input[name="chat-duration"]:checked');
  const minutes = Number(picked && picked.value);
  return minutes === 20 ? 20 : 30;
}

function chatHasResumeEvidence(profile) {
  const source = profile && typeof profile === 'object' ? profile : {};
  const experiences = Array.isArray(source.experiences) ? source.experiences : [];
  const projects = Array.isArray(source.projects) ? source.projects : [];
  const hasExperience = experiences.some((row) => row && (row.company || row.title || row.summary));
  const hasProject = projects.some((row) => row && (row.name || row.summary));
  return hasExperience || hasProject;
}

function chatSelectedJob() {
  const jobs = state.snapshot && Array.isArray(state.snapshot.jobs) ? state.snapshot.jobs : [];
  const id = dom.chatJob ? String(dom.chatJob.value || '') : '';
  if (!id) return null;
  return jobs.find((job) => String(job.id) === id) || null;
}

function chatGenericRole() {
  const jd = dom.chatJd ? String(dom.chatJd.value || '').trim() : '';
  return !jd && !chatSelectedJob();
}

function chatLibraryStorageKey(mode) {
  return `${CHAT_LIBRARY_KEY_PREFIX}${mode || state.mode}`;
}

function chatNormalizeKey(text) {
  return String(text || '')
    .trim()
    .toLowerCase()
    .replace(/[\u3000]/g, '')
    .replace(/[/\-·_（）()\s]/g, '');
}

function chatFieldMatch(left, right) {
  const a = chatNormalizeKey(left);
  const b = chatNormalizeKey(right);
  if (a.length < 2 || b.length < 2) return false;
  return a === b || a.includes(b) || b.includes(a);
}

function chatStripRoleAffixes(text) {
  let value = chatNormalizeKey(text);
  CHAT_ROLE_AFFIXES.forEach((affix) => {
    const token = chatNormalizeKey(affix);
    if (token) value = value.split(token).join('');
  });
  return value;
}

function chatExtractDirections(text) {
  const norm = chatNormalizeKey(text);
  if (!norm) return [];
  return CHAT_ROLE_DIRECTIONS.filter((word) => {
    const token = chatNormalizeKey(word);
    return token && norm.includes(token);
  });
}

function chatSameRole(left, right) {
  const a = chatStripRoleAffixes(left);
  const b = chatStripRoleAffixes(right);
  if (a.length < 2 || b.length < 2) return false;
  return a === b || a.includes(b) || b.includes(a);
}

function chatSimilarRole(left, right) {
  const leftDirs = chatExtractDirections(left).filter((word) => !CHAT_GENERIC_ROLE_TOKENS.includes(word));
  const rightDirs = new Set(chatExtractDirections(right).filter((word) => !CHAT_GENERIC_ROLE_TOKENS.includes(word)));
  return leftDirs.some((word) => rightDirs.has(word));
}

function chatItemRoleText(item) {
  return String((item && item.role) || '').trim() || String((item && item.title) || '').trim();
}

function chatHasStartTarget() {
  const jd = dom.chatJd ? String(dom.chatJd.value || '').trim() : '';
  return Boolean(chatSelectedJob() || jd);
}

function chatIsQuestionBankItem(item) {
  if (!item || typeof item !== 'object') return true;
  if (item.kind !== 'jingyan' && item.kind !== 'knowledge') return true;
  if (item.source === 'question_bank' || item.worksheet) return true;
  return false;
}

function chatQuestionBankTexts() {
  const snapshot = state.snapshot || {};
  const bank = snapshot.question_bank && Array.isArray(snapshot.question_bank.questions)
    ? snapshot.question_bank.questions
    : [];
  return bank.map((row) => String((row && row.question) || '').trim()).filter(Boolean);
}

function matchChatLibraryForSession() {
  const job = chatSelectedJob();
  const jd = dom.chatJd ? String(dom.chatJd.value || '').trim() : '';
  const company = job ? String(job.company || '').trim() : '';
  const role = job ? String(job.title || '').trim() : '';
  if (!company && !role && !jd) {
    return { matched: [], hasTargetKnowledge: false };
  }
  const library = state.interviewChat.materials.filter((item) => !chatIsQuestionBankItem(item));
  const target = company
    ? library.filter((item) => chatFieldMatch(item.company, company)).map((item) => Object.assign({}, item, {
      match_tier: 'target_company'
    }))
    : [];
  const targetJingyanCount = target.filter((item) => item.kind === 'jingyan').length;
  const roleText = role || (jd ? jd.slice(0, 200) : '');
  const peers = [];
  if (targetJingyanCount === 0 && roleText) {
    library.forEach((item) => {
      if (item.kind !== 'jingyan') return;
      if (company && chatFieldMatch(item.company, company)) return;
      const itemRole = chatItemRoleText(item);
      let matchTier = '';
      if (role && chatSameRole(itemRole, role)) matchTier = 'peer_same_role';
      else if (chatSimilarRole(itemRole, roleText)) matchTier = 'peer_similar_role';
      if (!matchTier) return;
      peers.push(Object.assign({}, item, { match_tier: matchTier }));
    });
  }
  const matched = target.concat(peers);
  const hasTargetKnowledge = target.some((item) => (
    item.kind === 'knowledge' && String(item.body || '').trim()
  ));
  return { matched, hasTargetKnowledge };
}

function chatWebSearchConfig() {
  const cfg = state.interviewChat.webSearch;
  return {
    configured: Boolean(cfg && cfg.configured),
    results: cfg && Array.isArray(cfg.results) ? cfg.results.slice() : []
  };
}

function setChatWebSearchConfig(options) {
  const src = options && typeof options === 'object' ? options : {};
  state.interviewChat.webSearch = {
    configured: Boolean(src.configured),
    results: Array.isArray(src.results) ? src.results.slice(0, 3) : []
  };
  return chatWebSearchConfig();
}

function chatHttpUrl(value) {
  const url = String(value || '').trim();
  return /^https?:\/\//i.test(url) ? url : '';
}

function chatParseWebSearchHits(rawRows) {
  const rows = Array.isArray(rawRows) ? rawRows : [];
  const hits = [];
  rows.forEach((row) => {
    if (hits.length >= 3 || !row || typeof row !== 'object') return;
    const url = chatHttpUrl(row.url || row.link || row.source_url || row.href);
    const title = String(row.title || row.name || '').trim();
    const body = String(row.body || row.content || row.snippet || row.text || row.description || '').trim();
    if (!url || (!title && !body)) return;
    const kind = row.kind === 'knowledge' ? 'knowledge' : 'jingyan';
    hits.push({
      kind,
      title: title || Array.from(body).slice(0, 24).join('') || (kind === 'knowledge' ? '岗位知识' : '面经'),
      body: body || title,
      source_urls: [url]
    });
  });
  return hits;
}

function mockResolveWebSupplement(job) {
  const cfg = chatWebSearchConfig();
  if (!cfg.configured) {
    return { status: 'unavailable', items: [] };
  }
  const hits = chatParseWebSearchHits(cfg.results);
  if (!hits.length) {
    return { status: 'unavailable', items: [] };
  }
  const now = new Date().toISOString();
  const written = hits.map((hit) => {
    const item = normalizeChatLibraryItem({
      id: `lib-web-${state.interviewChat.materialSeq++}`,
      kind: hit.kind,
      title: hit.title,
      body: hit.body,
      company: job && job.company ? String(job.company) : '',
      role: job && job.title ? String(job.title) : '',
      source: 'web',
      source_urls: hit.source_urls,
      created_at: now,
      updated_at: now
    }, 0);
    state.interviewChat.materials.push(item);
    return item;
  });
  persistChatLibrary();
  renderChatLibrary();
  return { status: 'written', items: written };
}

function chatJoinPeriod(left, right) {
  const a = String(left || '').trim();
  const b = String(right || '').trim();
  if (!a) return b;
  if (!b) return a;
  const head = a.replace(/[。.!！]+$/u, '');
  const tail = b.replace(/^[。.!！]+/u, '');
  return `${head}。${tail}`;
}

function chatPeerTier(item) {
  const tier = item && item.match_tier;
  return tier === 'peer_same_role' || tier === 'peer_similar_role' ? tier : '';
}

function chatLibraryDisplayLabel(item) {
  if (!item) return '';
  if (item.source === 'web') return CHAT_WEB_LABEL;
  if (chatPeerTier(item)) return CHAT_PEER_LABEL;
  return '';
}

function normalizeChatLibraryItem(raw, index) {
  const item = raw && typeof raw === 'object' ? raw : {};
  const kind = item.kind === 'knowledge' ? 'knowledge' : 'jingyan';
  const body = String(item.body || '').trim();
  const source = item.source === 'web' ? 'web' : 'user';
  const title = String(item.title || '').trim()
    || Array.from(body).slice(0, 24).join('')
    || (kind === 'knowledge' ? '岗位知识' : '面经');
  const id = String(item.id || '').trim() || `lib-${Date.now()}-${index + 1}`;
  const matchTier = chatPeerTier(item);
  return {
    id,
    kind,
    title,
    body,
    company: String(item.company || '').trim(),
    role: String(item.role || '').trim(),
    source,
    source_label: source === 'web' ? CHAT_WEB_LABEL : '',
    match_tier: matchTier,
    jingyan_is_not_official: kind === 'jingyan' || source === 'web',
    created_at: String(item.created_at || new Date().toISOString()),
    updated_at: String(item.updated_at || item.created_at || new Date().toISOString()),
    source_urls: source === 'web' && Array.isArray(item.source_urls) ? item.source_urls.slice() : []
  };
}

function persistChatLibrary() {
  safeLocalSet(chatLibraryStorageKey(), JSON.stringify(state.interviewChat.materials));
  renderInterviewHub();
}

function loadChatLibrary() {
  const raw = safeLocalGet(chatLibraryStorageKey());
  if (raw == null) {
    state.interviewChat.materials = [];
    persistChatLibrary();
  } else {
    try {
      const parsed = JSON.parse(raw);
      const rows = Array.isArray(parsed) ? parsed : [];
      state.interviewChat.materials = rows.map((item, index) => normalizeChatLibraryItem(item, index));
    } catch (error) {
      state.interviewChat.materials = [];
    }
  }
  const maxSeq = state.interviewChat.materials.reduce((max, item) => {
    const match = String(item.id || '').match(/(\d+)$/);
    const value = match ? Number(match[1]) : 0;
    return Number.isFinite(value) && value > max ? value : max;
  }, 0);
  state.interviewChat.materialSeq = Math.max(state.interviewChat.materialSeq, maxSeq + 1);
  state.interviewChat.libraryEditingId = null;
  clearChatLibraryForm();
  renderChatLibrary();
}

function chatLibraryBodyValue() {
  return dom.chatLibraryBody ? String(dom.chatLibraryBody.value || '').trim() : '';
}

function syncChatLibrarySave() {
  if (!dom.chatLibrarySave) return;
  dom.chatLibrarySave.disabled = !chatLibraryBodyValue();
}

function clearChatLibraryForm() {
  state.interviewChat.libraryEditingId = null;
  if (dom.chatLibraryKind) dom.chatLibraryKind.value = 'jingyan';
  if (dom.chatLibraryTitle) dom.chatLibraryTitle.value = '';
  if (dom.chatLibraryCompany) dom.chatLibraryCompany.value = '';
  if (dom.chatLibraryRole) dom.chatLibraryRole.value = '';
  if (dom.chatLibraryBody) dom.chatLibraryBody.value = '';
  if (dom.chatLibrarySave) dom.chatLibrarySave.textContent = '保存到知识库';
  if (dom.chatLibraryCancel) dom.chatLibraryCancel.hidden = true;
  syncChatLibrarySave();
}

function fillChatLibraryForm(item) {
  if (!item) {
    clearChatLibraryForm();
    return;
  }
  state.interviewChat.libraryEditingId = item.id;
  if (dom.chatLibraryKind) dom.chatLibraryKind.value = item.kind === 'knowledge' ? 'knowledge' : 'jingyan';
  if (dom.chatLibraryTitle) dom.chatLibraryTitle.value = item.title || '';
  if (dom.chatLibraryCompany) dom.chatLibraryCompany.value = item.company || '';
  if (dom.chatLibraryRole) dom.chatLibraryRole.value = item.role || '';
  if (dom.chatLibraryBody) dom.chatLibraryBody.value = item.body || '';
  if (dom.chatLibrarySave) dom.chatLibrarySave.textContent = '保存修改';
  if (dom.chatLibraryCancel) dom.chatLibraryCancel.hidden = false;
  syncChatLibrarySave();
}

function buildChatRulesText(round, duration, generic) {
  const roundLabel = CHAT_ROUND_LABELS[round] || '业务专业';
  const prefix = generic ? '本轮是通用岗位模拟。' : '';
  const text = `${prefix}本场是${roundLabel}面试，时长 ${duration} 分钟。一次只问一问。过程中不点评对错。结束后再复盘。`;
  return Array.from(text).slice(0, 120).join('');
}

function buildChatMains(round, materials, options = {}) {
  const first = {
    id: 'q1',
    text: '请讲一次你在实习里把需求范围缩小的经历。'
  };
  if (round === 'hr') {
    first.text = '请讲一次你在实习里和业务方对齐需求、把范围缩小的经历。';
  } else if (round === 'tech') {
    first.text = '请讲一次你在项目里把需求范围缩小、并推动按时上线的经历。';
  } else if (round === 'manager') {
    first.text = '请讲一次你作为负责人把需求范围缩小、并带团队交付的经历。';
  }
  const bankTexts = chatQuestionBankTexts();
  const scenarioSource = Array.isArray(materials) ? materials.find((item) => {
    if (!item || chatPeerTier(item)) return false;
    if (item.match_tier !== 'target_company') return false;
    if (item.kind !== 'knowledge' && item.source !== 'web') return false;
    const body = String(item.body || '').trim();
    if (!body) return false;
    return !bankTexts.includes(body);
  }) : null;
  const jd = String(options.jd || '').trim();
  const snippet = scenarioSource
    ? String(scenarioSource.body || '').trim()
    : (options.hasScenario && jd ? jd : '');
  const leaked = snippet && bankTexts.some((text) => text && snippet.includes(text));
  const second = snippet && !leaked
    ? {
      id: 'q2',
      text: `材料里写到「${Array.from(snippet).slice(0, 36).join('')}」。请说明你会怎么处理这个业务场景，不要复述简历。`
    }
    : {
      id: 'q2',
      text: '如果业务方坚持把已经缩小的首期范围加回来，你会怎么处理？'
    };
  return [first, second];
}

function chatLooksVague(text) {
  const t = String(text || '').trim();
  if (t.length < 12) return true;
  if (/大概|可能吧|还行|挺好的/.test(t)) return true;
  if (/我们/.test(t) && !/我/.test(t)) return true;
  return false;
}

function chatFollowupText() {
  return '刚才这句还比较含糊。请把其中的角色、做法和结果说具体一点。';
}

function chatCandidateTexts(session) {
  const turns = session && Array.isArray(session.turns) ? session.turns : [];
  return turns
    .filter((turn) => turn && turn.role === 'candidate')
    .map((turn) => String(turn.text || '').trim())
    .filter(Boolean);
}

function chatPairedTurns(session) {
  const turns = session && Array.isArray(session.turns) ? session.turns : [];
  const pairs = [];
  let question = '';
  turns.forEach((turn) => {
    if (!turn) return;
    if (turn.role === 'interviewer' && !turn.incomplete) {
      question = String(turn.text || '').trim();
      return;
    }
    if (turn.role === 'candidate' && question) {
      pairs.push({
        question,
        answer: String(turn.text || '').trim()
      });
      question = '';
    }
  });
  return pairs;
}

function chatMentionedNumbers(text) {
  return String(text || '').match(/\d+(?:\.\d+)?/g) || [];
}

function chatEvidenceSpan(texts, pattern) {
  const list = Array.isArray(texts) ? texts : [];
  for (let i = 0; i < list.length; i += 1) {
    const text = String(list[i] || '');
    const match = text.match(pattern);
    if (!match || match.index === undefined) continue;
    const start = Math.max(0, match.index - 6);
    const end = Math.min(text.length, match.index + match[0].length + 28);
    return text.slice(start, end).trim();
  }
  return '';
}

function chatAdjacentPrompt(question) {
  const original = String(question || '').trim();
  if (!original) return '换个问法：当时你为什么做这个选择，而不是把范围再放大？';
  return `换个问法：${original.replace(/。$/, '')}，请从取舍原因而不是过程复述说起。`;
}

function chatSingleGap(texts) {
  const joined = texts.join('\n');
  if (!chatMentionedNumbers(joined).length && !/两周|一周|三天|百分之/.test(joined)) {
    return '缺少可核对的结果数字';
  }
  if (!/范围|首期|取舍/.test(joined)) {
    return '没有说清当时缩小了什么、留下了什么';
  }
  return '结果和范围还没有对齐到同一段经历';
}

function buildMockDebriefCard(session) {
  const texts = chatCandidateTexts(session);
  const pairs = chatPairedTurns(session);
  const joined = texts.join('\n');
  const scopeEvidence = chatEvidenceSpan(texts, /范围|首期|注册|支付|取舍/);
  const resultEvidence = chatEvidenceSpan(texts, /\d|两周|一周|三天|上线|百分之/);
  const collabEvidence = chatEvidenceSpan(texts, /业务方|团队|对齐|负责人|我把|我负责/);
  const thin = !texts.length || texts.every((text) => text.length < 8);
  const vagueOnly = texts.length > 0 && texts.every((text) => chatLooksVague(text)) && !resultEvidence;
  let readiness = 'needs_practice';
  let reason = '回答里有经历轮廓，但范围和结果还没有同时说清。';
  if (thin) {
    readiness = 'insufficient_evidence';
    reason = '这场几乎没有可引用的完整回答，只能标成证据不足。';
  } else if (scopeEvidence && resultEvidence) {
    readiness = 'almost_ready';
    reason = '已经能引用范围和结果，再补一句取舍原因就会更完整。';
  } else if (vagueOnly) {
    readiness = 'needs_practice';
    reason = '回答偏含糊，练习准备度还不够，不能据此给高分。';
  }
  const labels = CHAT_SCORE_LABELS[session.round] || CHAT_SCORE_LABELS.business;
  const evidenceByIndex = [scopeEvidence, collabEvidence, resultEvidence];
  const scores = labels.map((label, index) => {
    const evidence = evidenceByIndex[index] || '';
    if (!evidence) {
      return {
        id: `s${index + 1}`,
        label,
        score: null,
        evidence: '',
        missing: CHAT_MISSING_EVIDENCE,
        confidence: 'low'
      };
    }
    return {
      id: `s${index + 1}`,
      label,
      score: 3,
      evidence,
      missing: '',
      confidence: 'medium'
    };
  });
  const reviews = pairs.map((pair) => ({
    question: pair.question,
    answer: pair.answer,
    comment: chatLooksVague(pair.answer)
      ? '这句还缺少可核对的做法和结果，不能只凭流畅度给分。'
      : '这句已经能对上经历，仍要避免补上没说过的指标。',
    suggested_structure: chatMentionedNumbers(pair.answer).length
      ? '先说你负责的范围，再复述你已经说过的结果。'
      : '先说你负责的范围，请补充真实数字。'
  }));
  const gap = chatSingleGap(texts);
  const drillSource = pairs.slice(0, 3);
  const drillItems = (drillSource.length ? drillSource : [{
    question: session.current_question || '请再讲一次你缩小需求范围的经历。',
    answer: ''
  }]).slice(0, 3).map((pair, index) => ({
    id: `drill-${session.id}-${index + 1}`,
    question: pair.question,
    gap,
    nearby_question: chatAdjacentPrompt(pair.question)
  }));
  const resumeEvidence = scopeEvidence || resultEvidence || texts[0] || '';
  const resumeSuggestion = resumeEvidence
    ? '简历里的该项目补上首期范围和可核对的上线结果，不写未提到的指标。'
    : '在实习或项目经历里补上可核对的范围和结果，不写这场没有出现的指标。';
  return {
    session_id: session.id,
    round: session.round,
    readiness,
    reason,
    scores,
    reviews,
    priority_fix: gap === '缺少可核对的结果数字'
      ? '下次只补一个缺口：把结果说成可核对的数字或时间。'
      : `下次只改一处：${gap}。`,
    resume_edit_points: [
      {
        suggestion: resumeSuggestion,
        evidence: resumeEvidence
      }
    ],
    drill_items: drillItems,
    not_an_offer: true,
    evidence_note: '分数只依据本场回答；修改点未写入定制简历；不表示录用。'
  };
}

function chatDelay(ms, signal) {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms);
    if (!signal) return;
    const fail = () => {
      window.clearTimeout(timer);
      const error = new Error('aborted');
      error.name = 'AbortError';
      reject(error);
    };
    if (signal.aborted) {
      fail();
      return;
    }
    signal.addEventListener('abort', fail, { once: true });
  });
}

function stopChatClock() {
  if (state.interviewChat.timerId) {
    window.clearInterval(state.interviewChat.timerId);
    state.interviewChat.timerId = null;
  }
}

function remainingMinutesFromSession(session) {
  if (!session) return chatDurationValue();
  const seconds = Number(session.remaining_seconds);
  if (!Number.isFinite(seconds)) return session.duration_minutes || chatDurationValue();
  return Math.max(0, Math.ceil(seconds / 60));
}

function setInlineError(node, message) {
  if (!node) return;
  if (!message) {
    node.hidden = true;
    node.textContent = '';
    return;
  }
  node.hidden = false;
  node.textContent = message;
}

function setChatError(message) {
  setInlineError(dom.chatError, message);
}

function setLibraryError(message) {
  setInlineError(dom.chatLibraryError, message);
}

function setChatRules(text) {
  if (!dom.chatRules) return;
  if (!text) {
    dom.chatRules.hidden = true;
    dom.chatRules.textContent = '';
    return;
  }
  dom.chatRules.hidden = false;
  dom.chatRules.textContent = text;
}

function setChatWebNotice(text, code) {
  if (!dom.chatWebNotice) return;
  if (!text) {
    dom.chatWebNotice.hidden = true;
    dom.chatWebNotice.textContent = '';
    dom.chatWebNotice.removeAttribute('data-web-supplement');
    return;
  }
  dom.chatWebNotice.hidden = false;
  dom.chatWebNotice.textContent = text;
  if (code) dom.chatWebNotice.setAttribute('data-web-supplement', code);
  else dom.chatWebNotice.removeAttribute('data-web-supplement');
}

function syncChatContextLabels() {
  const session = state.interviewChat.session;
  const generic = session ? Boolean(session.generic_role) : chatGenericRole();
  const display = session && session.display ? session.display : null;
  const job = display || chatSelectedJob();
  if (dom.chatGenericNote) {
    dom.chatGenericNote.hidden = !generic;
    if (generic) dom.chatGenericNote.textContent = '本轮是通用岗位模拟';
  }
  if (dom.chatRoleLine) {
    if (job && (job.company || job.title)) {
      const company = String(job.company || '').trim();
      const title = String(job.title || '').trim();
      dom.chatRoleLine.hidden = false;
      dom.chatRoleLine.textContent = [company, title].filter(Boolean).join('，');
    } else {
      dom.chatRoleLine.hidden = true;
      dom.chatRoleLine.textContent = '';
    }
  }
}

function updateChatProgress() {
  if (!dom.chatProgress) return;
  const idle = chatPhase() === 'idle';
  const minutes = idle ? chatDurationValue() : remainingMinutesFromSession(state.interviewChat.session);
  dom.chatProgress.textContent = `${idle ? '预计' : '剩余'} ${minutes} 分钟`;
}

function chatPhase() {
  const session = state.interviewChat.session;
  const internal = state.interviewChat.internal;
  if (!session || session.user_status === 'idle') return 'idle';
  if (internal && internal.streaming && session.user_status === 'preparing') return 'preparing';
  if (internal && internal.streaming) return 'asking';
  if (internal && internal.incomplete) return 'retry';
  if (session.user_status === 'ending') return 'ending';
  if (session.user_status === 'debriefed' || session.user_status === 'drilling') return 'done';
  if (session.end_available || session.user_status === 'ready_to_end') return 'end';
  if (session.user_status === 'preparing') return 'preparing';
  return 'send';
}

function syncChatPrimary() {
  if (!dom.chatPrimary) return;
  const phase = chatPhase();
  const labels = {
    idle: '开始这场面试',
    preparing: '正在根据简历准备问题',
    asking: '正在提问',
    send: '发送回答',
    retry: '重试这一问',
    end: '结束面试',
    ending: '正在生成复盘',
    done: '本场已结束'
  };
  const busy = phase === 'preparing' || phase === 'asking' || phase === 'ending';
  let disabled = busy || phase === 'done';
  if (phase === 'send') {
    disabled = !String(dom.chatAnswer && dom.chatAnswer.value || '').trim();
  }
  dom.chatPrimary.textContent = labels[phase] || labels.idle;
  dom.chatPrimary.disabled = disabled;
  dom.chatPrimary.hidden = phase === 'done';
  if (busy) dom.chatPrimary.setAttribute('aria-busy', 'true');
  else dom.chatPrimary.removeAttribute('aria-busy');
  if (dom.chatRestart) {
    const active = Boolean(state.interviewChat.session && state.interviewChat.session.user_status !== 'idle');
    dom.chatRestart.hidden = !active;
  }
  if (dom.chatAnswer) {
    const lockInput = phase === 'preparing' || phase === 'asking' || phase === 'ending' || phase === 'done' || phase === 'end';
    // 走查第 3 条：未开始时直接隐藏答题框，而不是留一个禁用但可见的输入区。
    dom.chatAnswer.hidden = phase === 'idle';
    dom.chatAnswer.disabled = phase === 'idle' || lockInput;
    dom.chatAnswer.placeholder = phase === 'idle'
      ? '开始后再输入回答。'
      : '输入这一问的回答。空白内容不会发送。';
  }
  const mockTools = document.getElementById('sg-chat-mock-tools');
  if (mockTools) mockTools.hidden = phase === 'idle';
  const chatPanel = document.getElementById('interview-chat');
  if (chatPanel) chatPanel.classList.toggle('is-idle', phase === 'idle');
  const reason = document.getElementById('sg-chat-reason');
  if (reason) {
    let text = '';
    if (phase === 'idle') text = '先点「开始这场面试」。';
    else if (phase === 'send' && !String(dom.chatAnswer && dom.chatAnswer.value || '').trim()) text = '输入回答后才能发送。';
    else if (busy) text = '正在处理，请稍候。';
    reason.textContent = text;
    reason.hidden = !text;
  }
}

function renderChatLibrary() {
  const renderList = (node, kind, emptyText) => {
    if (!node) return;
    clear(node);
    const rows = state.interviewChat.materials.filter((item) => item.kind === kind);
    if (!rows.length) {
      node.append(el('p', { className: 'hint', text: emptyText }));
      return;
    }
    rows.forEach((item) => {
      const row = el('div', {
        className: 'chat-library-item',
        attrs: {
          'data-library-id': item.id,
          'data-library-source': item.source
        }
      });
      const main = el('div', { className: 'chat-library-main' });
      main.append(el('span', { className: 'chat-library-title', text: item.title }));
      const label = chatLibraryDisplayLabel(item);
      if (label) {
        main.append(el('span', {
          className: 'chat-library-source',
          text: label,
          attrs: {
            'data-library-source-label': item.source === 'web' ? 'web' : 'peer'
          }
        }));
      }
      const actions = el('div', { className: 'chat-library-actions' });
      actions.append(el('button', {
        className: 'button button-quiet button-small',
        text: '修改',
        attrs: { type: 'button', 'data-library-edit': item.id }
      }));
      actions.append(el('button', {
        className: 'button button-quiet button-small',
        text: '删除',
        attrs: { type: 'button', 'data-library-delete': item.id }
      }));
      row.append(main, actions);
      node.append(row);
    });
  };
  renderList(dom.chatJingyanList, 'jingyan', '还没有已保存的面经，请先新增。');
  renderList(dom.chatKnowledgeList, 'knowledge', '还没有已保存的岗位知识，请先新增。');
}

function renderChatLog() {
  if (!dom.chatLog) return;
  const session = state.interviewChat.session;
  const turns = session && Array.isArray(session.turns) ? session.turns : [];
  clear(dom.chatLog);
  turns.forEach((turn) => {
    const role = turn.role === 'candidate' ? 'candidate' : 'interviewer';
    const className = [
      'chat-turn',
      role === 'candidate' ? 'chat-turn-candidate' : 'chat-turn-interviewer',
      turn.incomplete ? 'chat-turn-incomplete' : ''
    ].filter(Boolean).join(' ');
    const node = el('div', {
      className,
      attrs: { 'data-chat-role': role }
    });
    node.append(el('span', { text: String(turn.text || '') }));
    if (turn.incomplete) {
      node.append(el('span', { className: 'chat-turn-note', text: CHAT_INCOMPLETE_NOTE }));
    }
    dom.chatLog.append(node);
  });
  if (turns.length) {
    const last = dom.chatLog.lastElementChild;
    if (last && typeof last.scrollIntoView === 'function') {
      last.scrollIntoView({ block: 'nearest', behavior: 'auto' });
    }
  }
}

function patchLastChatTurn() {
  if (!dom.chatLog || !state.interviewChat.session) {
    renderChatLog();
    return;
  }
  const turns = state.interviewChat.session.turns;
  const turn = turns[turns.length - 1];
  const node = dom.chatLog.lastElementChild;
  if (!turn || !node) {
    renderChatLog();
    return;
  }
  const body = node.querySelector('span:not(.chat-turn-note)') || node.firstChild;
  if (body) body.textContent = String(turn.text || '');
  node.classList.toggle('chat-turn-incomplete', Boolean(turn.incomplete));
  let note = node.querySelector('.chat-turn-note');
  if (turn.incomplete && !note) {
    node.append(el('span', { className: 'chat-turn-note', text: CHAT_INCOMPLETE_NOTE }));
  } else if (!turn.incomplete && note) {
    note.remove();
  }
  if (typeof node.scrollIntoView === 'function') {
    node.scrollIntoView({ block: 'nearest', behavior: 'auto' });
  }
}

function fillChatJobOptions(snapshot) {
  if (!dom.chatJob) return;
  const current = String(dom.chatJob.value || '');
  const jobs = snapshot && Array.isArray(snapshot.jobs) ? snapshot.jobs : [];
  clear(dom.chatJob);
  dom.chatJob.append(el('option', { text: '不选岗位', props: { value: '' } }));
  jobs.forEach((job) => {
    const label = [job.company, job.title].filter(Boolean).join('，') || String(job.id || '岗位');
    dom.chatJob.append(el('option', {
      text: label,
      props: { value: String(job.id || '') }
    }));
  });
  const still = Array.from(dom.chatJob.options).some((option) => option.value === current);
  dom.chatJob.value = still ? current : '';
  syncChatContextLabels();
}

function startChatClock() {
  stopChatClock();
  const session = state.interviewChat.session;
  const internal = state.interviewChat.internal;
  if (!session || !internal || !internal.startedAt) return;
  const tick = () => {
    const elapsed = Math.floor((Date.now() - internal.startedAt) / 1000);
    session.remaining_seconds = Math.max(0, session.duration_minutes * 60 - elapsed);
    if (session.remaining_seconds === 0) session.time_up = true;
    updateChatProgress();
    if (session.remaining_seconds === 0) stopChatClock();
  };
  tick();
  state.interviewChat.timerId = window.setInterval(tick, 1000);
}

function resetInterviewChat(options = {}) {
  if (options.archiveDebrief && state.interviewChat.card) {
    const card = state.interviewChat.card;
    const exists = state.interviewChat.debriefHistory.some((item) => item && item.session_id === card.session_id);
    if (!exists) state.interviewChat.debriefHistory.unshift(card);
  }
  if (state.interviewChat.streamAbort) {
    try {
      state.interviewChat.streamAbort.abort();
    } catch (error) {
      /* ignore */
    }
  }
  stopChatClock();
  state.interviewChat.session = null;
  state.interviewChat.internal = null;
  state.interviewChat.interruptNext = false;
  state.interviewChat.streamAbort = null;
  state.interviewChat.card = null;
  state.interviewChat.drill = null;
  setChatError('');
  setChatRules('');
  setChatWebNotice('');
  renderChatLog();
  renderChatDebrief();
  if (dom.chatAnswer) {
    dom.chatAnswer.value = '';
    dom.chatAnswer.disabled = false;
  }
  if (dom.chatPrimary) dom.chatPrimary.hidden = false;
  syncChatContextLabels();
  updateChatProgress();
  syncChatPrimary();
  renderInterviewHub();
}

function mockSaveLibraryItem() {
  const body = chatLibraryBodyValue();
  if (!body) {
    setLibraryError(CHAT_EMPTY_MATERIAL);
    setStatus(CHAT_EMPTY_MATERIAL, 'error');
    syncChatLibrarySave();
    return;
  }
  const kind = dom.chatLibraryKind && dom.chatLibraryKind.value === 'knowledge' ? 'knowledge' : 'jingyan';
  const titleInput = dom.chatLibraryTitle ? String(dom.chatLibraryTitle.value || '').trim() : '';
  const company = dom.chatLibraryCompany ? String(dom.chatLibraryCompany.value || '').trim() : '';
  const role = dom.chatLibraryRole ? String(dom.chatLibraryRole.value || '').trim() : '';
  const editingId = state.interviewChat.libraryEditingId;
  const now = new Date().toISOString();
  if (editingId) {
    const current = state.interviewChat.materials.find((item) => item.id === editingId);
    if (!current) {
      setLibraryError('这条知识库条目不存在。');
      return;
    }
    current.kind = kind;
    current.body = body;
    current.title = titleInput || Array.from(body).slice(0, 24).join('') || (kind === 'knowledge' ? '岗位知识' : '面经');
    current.company = company;
    current.role = role;
    current.updated_at = now;
    if (current.source === 'web') {
      current.source_label = '来自联网';
      current.jingyan_is_not_official = true;
    } else {
      current.source = 'user';
      current.source_label = '';
      current.jingyan_is_not_official = current.kind === 'jingyan';
    }
    persistChatLibrary();
    renderChatLibrary();
    clearChatLibraryForm();
    setLibraryError('');
    setStatus('已更新这条知识库条目。', 'ok');
    return;
  }
  const duplicate = state.interviewChat.materials.find((item) => (
    item.kind === kind && String(item.body || '').trim() === body
  ));
  if (duplicate) {
    persistChatLibrary();
    renderChatLibrary();
    clearChatLibraryForm();
    setLibraryError('');
    setStatus(CHAT_LIBRARY_SAVED, 'ok');
    return;
  }
  const item = normalizeChatLibraryItem({
    id: `lib-${state.interviewChat.materialSeq++}`,
    kind,
    title: titleInput,
    body,
    company,
    role,
    source: 'user',
    created_at: now,
    updated_at: now
  }, 0);
  state.interviewChat.materials.push(item);
  persistChatLibrary();
  renderChatLibrary();
  clearChatLibraryForm();
  setLibraryError('');
  setStatus(CHAT_LIBRARY_SAVED, 'ok');
}

function mockEditLibraryItem(id) {
  const item = state.interviewChat.materials.find((row) => row.id === id);
  if (!item) return;
  fillChatLibraryForm(item);
}

function mockDeleteLibraryItem(id) {
  const index = state.interviewChat.materials.findIndex((row) => row.id === id);
  if (index < 0) {
    setLibraryError('这条知识库条目不存在。');
    return;
  }
  state.interviewChat.materials.splice(index, 1);
  if (state.interviewChat.libraryEditingId === id) clearChatLibraryForm();
  persistChatLibrary();
  renderChatLibrary();
  setLibraryError('');
  setStatus('已从知识库删除。', 'ok');
}

async function mockStreamQuestion(intent) {
  const session = state.interviewChat.session;
  const internal = state.interviewChat.internal;
  if (!session || !internal) return;
  const mains = internal.mains;
  let question = '';
  let move = 'main';
  if (intent === 'retry') {
    question = internal.pendingText || (mains[internal.mainIndex] && mains[internal.mainIndex].text) || '';
    move = internal.pendingMove || 'main';
  } else if (intent === 'first') {
    internal.mainIndex = 0;
    internal.followups = 0;
    question = mains[0].text;
    move = 'main';
    internal.currentMainId = mains[0].id;
  } else {
    const lastAnswer = internal.lastAnswer || '';
    const canFollow = internal.followups < 3 && chatLooksVague(lastAnswer);
    if (canFollow) {
      move = 'followup';
      internal.followups += 1;
      question = chatFollowupText();
    } else if (internal.mainIndex + 1 < mains.length) {
      move = 'main';
      internal.mainIndex += 1;
      internal.followups = 0;
      internal.currentMainId = mains[internal.mainIndex].id;
      question = mains[internal.mainIndex].text;
    } else {
      session.need_next = false;
      session.end_available = true;
      session.user_status = 'ready_to_end';
      syncChatPrimary();
      return;
    }
  }
  internal.pendingText = question;
  internal.pendingMove = move;
  const abort = new AbortController();
  state.interviewChat.streamAbort = abort;
  internal.streaming = true;
  internal.incomplete = false;
  const existing = session.turns[session.turns.length - 1];
  const reuse = intent === 'retry' && existing && existing.role === 'interviewer' && existing.incomplete;
  const turn = reuse ? existing : { role: 'interviewer', text: '' };
  turn.text = '';
  turn.incomplete = false;
  if (!reuse) session.turns.push(turn);
  renderChatLog();
  syncChatPrimary();
  let shown = '';
  const chars = Array.from(question);
  try {
    for (let i = 0; i < chars.length; i += 1) {
      if (abort.signal.aborted) {
        const error = new Error('aborted');
        error.name = 'AbortError';
        throw error;
      }
      if (state.interviewChat.interruptNext && shown.length >= 8) {
        state.interviewChat.interruptNext = false;
        throw new Error('interrupt');
      }
      shown += chars[i];
      turn.text = shown;
      patchLastChatTurn();
      await chatDelay(28, abort.signal);
    }
    turn.incomplete = false;
    session.current_question = shown;
    internal.streaming = false;
    internal.incomplete = false;
    internal.pendingText = shown;
    if (intent === 'first' || session.user_status === 'preparing') {
      session.user_status = 'in_progress';
      if (!internal.startedAt) {
        internal.startedAt = Date.now();
        startChatClock();
      }
    }
    patchLastChatTurn();
    syncChatPrimary();
  } catch (error) {
    internal.streaming = false;
    if (error && error.name === 'AbortError') return;
    turn.text = shown;
    turn.incomplete = true;
    internal.incomplete = true;
    patchLastChatTurn();
    setStatus('这一问没有问完：模型中断或超时。已经出现的半句会保留并标为未完成，不计入进度；可以重试，你提交过的回答还在。', 'warn');
    syncChatPrimary();
  } finally {
    if (state.interviewChat.streamAbort === abort) state.interviewChat.streamAbort = null;
  }
}

async function mockStartInterview() {
  if (state.interviewChat.session) return;
  const round = chatRoundValue();
  const duration = chatDurationValue();
  if (!CHAT_ROUND_LABELS[round] || (duration !== 20 && duration !== 30)) {
    setChatError('请选择 HR、业务专业、技术口述或主管，以及 20 或 30 分钟。');
    return;
  }
  const profile = state.snapshot && state.snapshot.profile;
  if (!chatHasResumeEvidence(profile)) {
    setChatError(CHAT_NO_RESUME);
    setStatus(CHAT_NO_RESUME, 'error');
    return;
  }
  const job = chatSelectedJob();
  const generic = chatGenericRole();
  const hasTarget = chatHasStartTarget();
  const jd = dom.chatJd ? String(dom.chatJd.value || '').trim() : '';
  const matched = hasTarget ? matchChatLibraryForSession() : { matched: [], hasTargetKnowledge: false };
  let materials = matched.matched.slice();
  let webSupplement = 'skipped_generic';
  let webNotice = '';
  if (!hasTarget) {
    webSupplement = 'skipped_generic';
    materials = [];
  } else if (matched.hasTargetKnowledge) {
    webSupplement = 'not_needed';
  } else {
    const search = mockResolveWebSupplement(job);
    if (search.status === 'written' && search.items.length) {
      const written = search.items.map((item) => Object.assign({}, item, { match_tier: 'target_company' }));
      materials = materials.concat(written);
      webSupplement = 'written';
      webNotice = CHAT_WEB_WRITTEN;
    } else {
      webSupplement = 'unavailable';
      webNotice = CHAT_WEB_UNAVAILABLE;
    }
  }
  const hasScenario = Boolean(jd) || webSupplement === 'written' || materials.some((item) => (
    item.match_tier === 'target_company' && item.kind === 'knowledge' && String(item.body || '').trim()
  ));
  const rules = buildChatRulesText(round, duration, generic);
  state.interviewChat.session = {
    id: `mock-${Date.now()}`,
    round,
    duration_minutes: duration,
    rules_text: rules,
    generic_role: generic,
    display: job ? { company: job.company || '', title: job.title || '' } : {},
    user_status: 'preparing',
    remaining_seconds: duration * 60,
    end_available: false,
    time_up: false,
    current_question: '',
    turns: [],
    web_supplement: webSupplement,
    web_supplement_notice: webNotice,
    library_match_count: materials.length
  };
  state.interviewChat.internal = {
    mains: buildChatMains(round, materials, { jd, hasScenario }),
    materialIds: materials.map((item) => item.id),
    matchTiers: materials.map((item) => item.match_tier || ''),
    mainIndex: 0,
    followups: 0,
    currentMainId: 'q1',
    lastAnswer: '',
    startedAt: null,
    streaming: false,
    incomplete: false,
    pendingText: '',
    pendingMove: 'main'
  };
  setChatError('');
  setChatRules(rules);
  setChatWebNotice(webNotice, webSupplement);
  syncChatContextLabels();
  updateChatProgress();
  renderChatLog();
  syncChatPrimary();
  renderInterviewHub();
  await mockStreamQuestion('first');
}

async function mockSendAnswer() {
  const session = state.interviewChat.session;
  const internal = state.interviewChat.internal;
  if (!session || !internal) return;
  if (internal.incomplete || internal.streaming) return;
  const answer = String(dom.chatAnswer.value || '').trim();
  if (!answer) {
    setStatus(CHAT_EMPTY_ANSWER, 'error');
    syncChatPrimary();
    return;
  }
  session.turns.push({ role: 'candidate', text: answer });
  internal.lastAnswer = answer;
  dom.chatAnswer.value = '';
  renderChatLog();
  const timeUp = Boolean(session.time_up) || Number(session.remaining_seconds) <= 0;
  const lastMain = internal.mainIndex >= internal.mains.length - 1;
  const wouldFollow = !timeUp && internal.followups < 3 && chatLooksVague(answer);
  const hasNextMain = !timeUp && !wouldFollow && internal.mainIndex + 1 < internal.mains.length;
  if (timeUp || (lastMain && !wouldFollow)) {
    session.need_next = false;
    session.end_available = true;
    session.user_status = 'ready_to_end';
    if (timeUp) session.time_up = true;
    updateChatProgress();
    syncChatPrimary();
    return;
  }
  session.need_next = true;
  session.end_available = false;
  syncChatPrimary();
  if (hasNextMain || wouldFollow) await mockStreamQuestion('next');
}

async function mockRetryQuestion() {
  const internal = state.interviewChat.internal;
  if (!internal || !internal.incomplete) return;
  await mockStreamQuestion('retry');
}

function chatCurrentDrillItem() {
  const card = state.interviewChat.card;
  const drill = state.interviewChat.drill;
  if (!card || !drill) return null;
  const items = Array.isArray(card.drill_items) ? card.drill_items : [];
  return items.find((item) => item && item.id === drill.item_id) || null;
}

function chatDrillPrompt(item, attempt) {
  if (!item) return '';
  if (attempt >= 4) return String(item.nearby_question || chatAdjacentPrompt(item.question));
  return String(item.question || '');
}

function buildDrillRecast(answer, session) {
  const text = String(answer || '').trim();
  if (!text) return '';
  const spoken = `${chatCandidateTexts(session).join('\n')}\n${text}`;
  const allowedNums = new Set(chatMentionedNumbers(spoken));
  const rewritten = `可以改成：${text}`;
  const leaked = chatMentionedNumbers(rewritten).some((num) => !allowedNums.has(num));
  if (leaked) return '请补充真实数字。';
  if (!allowedNums.size) {
    return chatJoinPeriod(rewritten.replace(/[。.!！]+$/u, ''), '请补充真实数字');
  }
  return rewritten.replace(/[。.!！]{2,}/gu, '。');
}

function mockDrillResponse(answer) {
  const session = state.interviewChat.session;
  const card = state.interviewChat.card;
  if (!session || !card) {
    setChatError('结束并生成复盘后才能重练。');
    return;
  }
  if (session.user_status !== 'debriefed' && session.user_status !== 'drilling') {
    setChatError('结束并生成复盘后才能重练。');
    return;
  }
  const item = chatCurrentDrillItem();
  if (!item) return;
  const drill = state.interviewChat.drill;
  const attempt = Number(drill.attempt) || 1;
  const trimmed = String(answer || '').trim();
  drill.gap = item.gap;
  drill.prompt = chatDrillPrompt(item, attempt);
  drill.recast = trimmed ? buildDrillRecast(trimmed, session) : '';
  drill.last_answer = trimmed;
  session.user_status = 'drilling';
  renderChatDebrief();
  syncChatPrimary();
}

function mockStartDrill(itemId) {
  const card = state.interviewChat.card;
  const session = state.interviewChat.session;
  if (!card || !session) {
    setChatError('结束并生成复盘后才能重练。');
    return;
  }
  const items = Array.isArray(card.drill_items) ? card.drill_items : [];
  const item = items.find((row) => row && row.id === itemId);
  if (!item) return;
  state.interviewChat.drill = {
    item_id: item.id,
    attempt: 1,
    gap: item.gap,
    prompt: '',
    recast: '',
    last_answer: ''
  };
  setChatError('');
  mockDrillResponse('');
}

function mockSubmitDrill() {
  const drill = state.interviewChat.drill;
  if (!drill) return;
  const input = document.getElementById('chat-drill-answer');
  const answer = input ? String(input.value || '') : '';
  drill.attempt = Math.max(1, Number(drill.attempt) || 1) + 1;
  mockDrillResponse(answer);
}

async function mockEndInterview() {
  const session = state.interviewChat.session;
  if (!session || !session.end_available) return;
  if (session.user_status === 'debriefed' || session.user_status === 'drilling') return;
  const token = session.id;
  session.user_status = 'ending';
  stopChatClock();
  syncChatPrimary();
  const abort = new AbortController();
  state.interviewChat.streamAbort = abort;
  try {
    await chatDelay(420, abort.signal);
  } catch (error) {
    if (error && error.name === 'AbortError') return;
    throw error;
  } finally {
    if (state.interviewChat.streamAbort === abort) state.interviewChat.streamAbort = null;
  }
  if (!state.interviewChat.session || state.interviewChat.session.id !== token) return;
  if (state.interviewChat.session.user_status !== 'ending') return;
  const card = buildMockDebriefCard(session);
  state.interviewChat.card = card;
  state.interviewChat.drill = null;
  session.user_status = 'debriefed';
  renderChatDebrief();
  syncChatPrimary();
  renderInterviewHub();
  showInterviewModule('debrief');
  setStatus('本场已结束，准备度复盘在「面试复盘」里；这里不能再发送回答。', 'ok');
}

function mockExpireTime() {
  const session = state.interviewChat.session;
  const internal = state.interviewChat.internal;
  if (!session || !internal) return;
  session.remaining_seconds = 0;
  session.time_up = true;
  if (internal.startedAt) internal.startedAt = Date.now() - session.duration_minutes * 60 * 1000;
  updateChatProgress();
  const waitingAnswer = session.user_status === 'in_progress' && !internal.streaming && !internal.incomplete;
  if (!waitingAnswer && !internal.streaming) {
    session.end_available = true;
    session.user_status = 'ready_to_end';
  }
  syncChatPrimary();
}

async function onChatPrimary() {
  const phase = chatPhase();
  if (phase === 'idle') {
    await mockStartInterview();
    return;
  }
  if (phase === 'retry') {
    await mockRetryQuestion();
    return;
  }
  if (phase === 'send') {
    await mockSendAnswer();
    return;
  }
  if (phase === 'end') {
    await mockEndInterview();
  }
}

function buildChatScoreNode(score) {
  const node = el('div', { className: 'chat-score' });
  const value = score && score.score;
  const hasScore = Number.isFinite(Number(value));
  const evidence = score && String(score.evidence || '').trim();
  const label = score && score.label ? String(score.label) : '练习项';
  if (!evidence) {
    node.append(el('p', {
      className: 'chat-score-label',
      text: `${label}：${CHAT_MISSING_EVIDENCE}`,
      attrs: { 'data-chat-score-value': 'missing' }
    }));
    node.append(el('p', { className: 'chat-score-evidence', text: String((score && score.missing) || CHAT_MISSING_EVIDENCE) }));
    return node;
  }
  const shown = hasScore ? `${label}：${Number(value)} 分` : `${label}：${CHAT_MISSING_EVIDENCE}`;
  node.append(el('p', {
    className: 'chat-score-label',
    text: shown,
    attrs: { 'data-chat-score-value': hasScore ? String(Number(value)) : 'missing' }
  }));
  node.append(el('p', { className: 'chat-score-evidence', text: `证据：${evidence}` }));
  return node;
}

function buildChatDebriefNode(card, options = {}) {
  const history = Boolean(options.history);
  const readiness = card && CHAT_READINESS_LABELS[card.readiness] ? card.readiness : 'insufficient_evidence';
  const node = el('article', {
    className: history ? 'chat-debrief' : '',
    attrs: {
      'data-chat-readiness': readiness,
      'data-chat-not-an-offer': card && card.not_an_offer ? 'true' : 'false'
    }
  });
  node.append(el('h4', {
    className: 'chat-debrief-heading',
    text: history ? '历史复盘卡' : '本场复盘',
    attrs: history ? {} : { id: 'chat-debrief-title' }
  }));
  node.append(el('p', {
    className: 'chat-debrief-reason',
    text: `${CHAT_READINESS_LABELS[readiness]}。${String((card && card.reason) || '')}`
  }));
  node.append(el('p', {
    className: 'chat-not-offer',
    text: CHAT_NOT_AN_OFFER
  }));

  const scoreWrap = el('div', { className: 'chat-debrief-section' });
  scoreWrap.append(el('h5', { className: 'chat-debrief-heading', text: '带证据的分数' }));
  const scores = card && Array.isArray(card.scores) ? card.scores : [];
  if (!scores.length) {
    scoreWrap.append(el('p', { className: 'chat-score-evidence', text: CHAT_MISSING_EVIDENCE }));
  } else {
    scores.forEach((score) => scoreWrap.append(buildChatScoreNode(score)));
  }
  node.append(scoreWrap);

  const reviewWrap = el('div', { className: 'chat-debrief-section' });
  reviewWrap.append(el('h5', { className: 'chat-debrief-heading', text: '逐题点评' }));
  const reviews = card && Array.isArray(card.reviews) ? card.reviews : [];
  if (!reviews.length) {
    reviewWrap.append(el('p', { className: 'chat-disclaimer', text: '本场没有完整问答可点评。' }));
  } else {
    reviews.forEach((review) => {
      const item = el('div', { className: 'chat-review' });
      item.append(el('p', { text: `问：${String(review.question || '')}` }));
      item.append(el('p', { text: `答：${String(review.answer || '')}` }));
      item.append(el('p', { className: 'chat-disclaimer', text: String(review.comment || '') }));
      item.append(el('p', { className: 'chat-disclaimer', text: String(review.suggested_structure || '') }));
      reviewWrap.append(item);
    });
  }
  node.append(reviewWrap);

  node.append(el('div', { className: 'chat-debrief-section' }, [
    el('h5', { className: 'chat-debrief-heading', text: '优先修正项' }),
    el('p', { className: 'chat-debrief-fix', text: String((card && card.priority_fix) || '') })
  ]));

  const resumeWrap = el('div', { className: 'chat-debrief-section' });
  resumeWrap.append(el('h5', { className: 'chat-debrief-heading', text: '简历修改点' }));
  resumeWrap.append(el('p', { className: 'chat-disclaimer', text: CHAT_RESUME_DISCLAIMER }));
  const points = card && Array.isArray(card.resume_edit_points) ? card.resume_edit_points : [];
  const list = el('ol', { className: 'chat-resume-points' });
  if (!points.length) {
    list.append(el('li', { text: '本场没有可写入简历的修改点。' }));
  } else {
    points.forEach((point) => {
      const suggestion = String((point && point.suggestion) || '');
      const evidence = String((point && point.evidence) || '').trim();
      list.append(el('li', { text: evidence ? `${suggestion} 依据：${evidence}` : suggestion }));
    });
  }
  resumeWrap.append(list);
  node.append(resumeWrap);

  if (card && card.evidence_note) {
    node.append(el('p', { className: 'chat-disclaimer', text: String(card.evidence_note) }));
  }

  if (history) return node;

  const drillWrap = el('div', { className: 'chat-debrief-section' });
  drillWrap.append(el('h5', { className: 'chat-debrief-heading', text: '重练一题' }));
  const items = card && Array.isArray(card.drill_items) ? card.drill_items : [];
  const drillList = el('div', { className: 'chat-drill-list' });
  items.forEach((item) => {
    const current = state.interviewChat.drill && state.interviewChat.drill.item_id === item.id;
    drillList.append(el('button', {
      className: 'button button-quiet',
      text: current ? '正在重练这题' : '重练这题',
      attrs: {
        type: 'button',
        'data-chat-drill-start': String(item.id || ''),
        'data-chat-drill-question': String(item.question || '')
      },
      props: { disabled: Boolean(current) }
    }));
  });
  drillWrap.append(drillList);

  const drill = state.interviewChat.drill;
  if (drill && drill.prompt) {
    const panel = el('div', { className: 'chat-drill-panel' });
    panel.append(el('p', {
      className: 'chat-score-label',
      text: drill.prompt,
      attrs: { 'data-chat-drill-prompt': 'true', 'data-chat-drill-attempt': String(drill.attempt || 1) }
    }));
    panel.append(el('p', {
      className: 'chat-score-evidence',
      text: `本次缺口：${String(drill.gap || '')}`,
      attrs: { 'data-chat-drill-gap': 'true' }
    }));
    if (drill.recast) {
      panel.append(el('p', {
        className: 'chat-disclaimer',
        text: `示范：${drill.recast}`,
        attrs: { 'data-chat-drill-recast': 'true' }
      }));
    }
    panel.append(el('label', { className: 'chat-sr-only', text: '重练回答', attrs: { for: 'chat-drill-answer' } }));
    panel.append(el('textarea', {
      attrs: {
        id: 'chat-drill-answer',
        rows: '3',
        placeholder: '可空提交，只会再提示同一个缺口；有内容则给出示范。'
      },
      props: { value: '' }
    }));
    panel.append(el('button', {
      className: 'button',
      text: '提交这次重练',
      attrs: { type: 'button', 'data-chat-drill-submit': 'true' }
    }));
    drillWrap.append(panel);
  }
  node.append(drillWrap);
  return node;
}

function renderChatDebrief() {
  const emptyNote = document.getElementById('chat-debrief-empty');
  let showCurrent = false;
  if (dom.chatDebrief) {
    const session = state.interviewChat.session;
    const card = state.interviewChat.card;
    showCurrent = Boolean(card && session && (session.user_status === 'debriefed' || session.user_status === 'drilling'));
    clear(dom.chatDebrief);
    if (showCurrent) {
      dom.chatDebrief.hidden = false;
      dom.chatDebrief.append(buildChatDebriefNode(card, { history: false }));
    } else {
      dom.chatDebrief.hidden = true;
    }
  }
  let showHistory = false;
  if (dom.chatDebriefHistory && dom.chatDebriefHistoryList) {
    const history = Array.isArray(state.interviewChat.debriefHistory) ? state.interviewChat.debriefHistory : [];
    clear(dom.chatDebriefHistoryList);
    showHistory = history.length > 0;
    if (!showHistory) {
      dom.chatDebriefHistory.hidden = true;
    } else {
      dom.chatDebriefHistory.hidden = false;
      history.forEach((card) => {
        dom.chatDebriefHistoryList.append(buildChatDebriefNode(card, { history: true }));
      });
    }
  }
  if (emptyNote) emptyNote.hidden = showCurrent || showHistory;
}

function bindInterviewChat() {
  if (!dom.chatPrimary) return;
  const setupForm = document.getElementById('chat-setup-form');
  if (setupForm) {
    setupForm.addEventListener('submit', (event) => event.preventDefault());
  }
  if (dom.chatLibraryForm) {
    dom.chatLibraryForm.addEventListener('submit', (event) => event.preventDefault());
  }
  document.querySelectorAll('input[name="chat-round"], input[name="chat-duration"]').forEach((input) => {
    input.addEventListener('change', () => {
      if (!state.interviewChat.session) updateChatProgress();
      syncChatContextLabels();
    });
  });
  if (dom.chatJob) {
    dom.chatJob.addEventListener('change', syncChatContextLabels);
  }
  if (dom.chatJd) {
    dom.chatJd.addEventListener('input', syncChatContextLabels);
  }
  if (dom.chatLibraryBody) {
    dom.chatLibraryBody.addEventListener('input', syncChatLibrarySave);
  }
  if (dom.chatLibrarySave) {
    dom.chatLibrarySave.addEventListener('click', mockSaveLibraryItem);
  }
  if (dom.chatLibraryCancel) {
    dom.chatLibraryCancel.addEventListener('click', () => {
      clearChatLibraryForm();
    });
  }
  const libraryRoot = document.getElementById('interview-module-library') || dom.chatLibrary;
  if (libraryRoot) {
    libraryRoot.addEventListener('click', (event) => {
      const edit = event.target.closest('[data-library-edit]');
      if (edit) {
        mockEditLibraryItem(edit.getAttribute('data-library-edit'));
        return;
      }
      const remove = event.target.closest('[data-library-delete]');
      if (remove) {
        mockDeleteLibraryItem(remove.getAttribute('data-library-delete'));
      }
    });
  }
  document.querySelectorAll('[data-interview-back]').forEach((button) => {
    button.addEventListener('click', () => showInterviewModule(null));
  });
  if (dom.chatAnswer) {
    dom.chatAnswer.addEventListener('input', syncChatPrimary);
  }
  dom.chatPrimary.addEventListener('click', () => {
    onChatPrimary();
  });
  if (dom.chatRestart) {
    dom.chatRestart.addEventListener('click', () => {
      const session = state.interviewChat.session;
      const finished = Boolean(
        state.interviewChat.card
        && session
        && (session.user_status === 'debriefed' || session.user_status === 'drilling')
      );
      resetInterviewChat({ archiveDebrief: finished });
      setStatus(
        finished ? '对话已替换，已完成的复盘仍保留。' : '未完成的对话已替换，没有生成复盘。',
        'ok'
      );
    });
  }
  if (dom.chatDebrief) {
    dom.chatDebrief.addEventListener('click', (event) => {
      const start = event.target.closest('[data-chat-drill-start]');
      if (start) {
        mockStartDrill(start.getAttribute('data-chat-drill-start'));
        return;
      }
      if (event.target.closest('[data-chat-drill-submit]')) {
        mockSubmitDrill();
      }
    });
  }
  if (dom.chatMockInterrupt) {
    dom.chatMockInterrupt.addEventListener('click', () => {
      state.interviewChat.interruptNext = true;
      setStatus('下一次提问将在半句后中断。', 'info');
    });
  }
  if (dom.chatMockTimeup) {
    dom.chatMockTimeup.addEventListener('click', () => {
      mockExpireTime();
      setStatus('已模拟时长用完。当前问仍可答完，之后不再出新题。', 'info');
    });
  }
  loadChatLibrary();
  renderChatDebrief();
  syncChatContextLabels();
  updateChatProgress();
  syncChatPrimary();
  window.__interviewChatMock = {
    interruptNext() {
      state.interviewChat.interruptNext = true;
    },
    expireTime: mockExpireTime,
    session() {
      const session = state.interviewChat.session;
      if (!session) return null;
      return {
        id: session.id,
        round: session.round,
        duration_minutes: session.duration_minutes,
        rules_text: session.rules_text,
        generic_role: session.generic_role,
        display: session.display,
        user_status: session.user_status,
        remaining_seconds: session.remaining_seconds,
        end_available: session.end_available,
        time_up: session.time_up,
        current_question: session.current_question,
        turns: session.turns,
        web_supplement: session.web_supplement,
        web_supplement_notice: session.web_supplement_notice,
        library_match_count: session.library_match_count
      };
    },
    library() {
      return state.interviewChat.materials.map((item) => ({
        id: item.id,
        kind: item.kind,
        title: item.title,
        company: item.company,
        role: item.role,
        source: item.source,
        source_label: item.source_label,
        match_tier: item.match_tier || '',
        source_urls: Array.isArray(item.source_urls) ? item.source_urls.slice() : []
      }));
    },
    webSearch: chatWebSearchConfig,
    setWebSearch: setChatWebSearchConfig,
    debrief() {
      return state.interviewChat.card;
    },
    drill() {
      const drill = state.interviewChat.drill;
      if (!drill) return null;
      return {
        item_id: drill.item_id,
        attempt: drill.attempt,
        gap: drill.gap,
        prompt: drill.prompt,
        recast: drill.recast
      };
    },
    history() {
      return state.interviewChat.debriefHistory.slice();
    },
    emptyResume() {
      const profile = state.snapshot && state.snapshot.profile;
      if (!profile) return false;
      if (!state.interviewChat.profileBackup) {
        state.interviewChat.profileBackup = {
          experiences: profile.experiences,
          projects: profile.projects
        };
      }
      profile.experiences = [];
      profile.projects = [];
      return true;
    },
    restoreResume() {
      const profile = state.snapshot && state.snapshot.profile;
      const backup = state.interviewChat.profileBackup;
      if (!profile || !backup) return false;
      profile.experiences = backup.experiences;
      profile.projects = backup.projects;
      state.interviewChat.profileBackup = null;
      return true;
    }
  };
}

/* Render: interview */

function listSection(title, items) {
  const wrap = el('div');
  wrap.append(el('p', { className: 'card-subtitle', text: title }));
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    wrap.append(el('p', { className: 'card-meta', text: '无显式记录。' }));
    return wrap;
  }
  const ul = el('ul');
  list.forEach((item) => ul.append(el('li', { text: String(item) })));
  wrap.append(ul);
  return wrap;
}

function buildDebriefCard(card, collapsible) {
  const node = collapsible ? el('details', { className: 'card' }) : el('article', { className: 'card' });
  if (collapsible) {
    node.append(el('summary', {
      text: `${formatDateTime(card.created_at)}，${String(card.source || '网页输入')}`
    }));
  } else {
    node.append(el('p', { className: 'result-title', text: '复盘卡片' }));
    node.append(el('p', {
      className: 'card-meta',
      text: `${formatDateTime(card.created_at)}，${String(card.source || '网页输入')}`
    }));
  }
  const tags = Array.isArray(card.weakness_tags) ? card.weakness_tags : [];
  if (tags.length) {
    const chipRow = el('div', { className: 'chip-row' });
    tags.forEach((tag) => chipRow.append(el('span', { className: 'chip', text: String(tag) })));
    node.append(chipRow);
  }
  node.append(listSection('面试官问题', card.interviewer_questions));
  node.append(listSection('回答摘录', card.answer_highlights));
  node.append(listSection('逻辑缺口', card.logic_gaps));
  node.append(listSection('新问题', card.new_questions));
  node.append(listSection('下一步', card.next_actions));

  const anomalies = Array.isArray(card.input_anomalies) ? card.input_anomalies : [];
  if (anomalies.length) {
    const wrap = el('div');
    wrap.append(el('p', {
      className: 'card-subtitle',
      text: '检测到可疑输入（只当文本显示，不会执行）'
    }));
    const ul = el('ul');
    anomalies.forEach((item) => {
      const quote = item && typeof item === 'object' ? String(item.quote || '') : String(item);
      const action = item && typeof item === 'object' ? String(item.action || '') : '';
      ul.append(el('li', { text: action ? `${quote} → ${action}` : quote }));
    });
    wrap.append(ul);
    node.append(wrap);
  }
  if (card.evidence_note) {
    node.append(el('p', { className: 'card-meta', text: String(card.evidence_note) }));
  }
  return node;
}

function renderInterview(snapshot) {
  fillChatJobOptions(snapshot);
  renderInterviewHub();
  const debriefs = Array.isArray(snapshot.debriefs) ? snapshot.debriefs : [];
  clear(dom.debriefList);
  if (!debriefs.length) {
    dom.debriefList.append(el('p', {
      className: 'empty-state',
      text: '当前筛选下暂无复盘卡片。粘贴逐字稿后可生成。'
    }));
  } else {
    debriefs.forEach((card) => dom.debriefList.append(buildDebriefCard(card, true)));
  }

  const bank = snapshot.question_bank && Array.isArray(snapshot.question_bank.questions)
    ? snapshot.question_bank.questions
    : [];
  renderTable(dom.bankList, {
    caption: '表：本地题库',
    columns: ['题目', '分段', '来源'],
    rows: bank.map((question) => [
      el('div', { className: 'cell-text', text: String(question.question || '') }),
      String(question.section || '—'),
      String(question.source || '—')
    ]),
    emptyText: '题库为空，需补充题目。',
    className: 'data-table-wide'
  });

  renderVariants(snapshot);
}

/* Render: resume variants (read-only master comparison) */

function renderVariants(snapshot) {
  const variants = snapshot && Array.isArray(snapshot.variants) ? snapshot.variants : [];
  renderTable(dom.variantList, {
    caption: '表：已保存的经历变体',
    // SHA-256 收进项目单元格，保证「主稿对比」在桌面首屏可见。
    columns: ['项目', '保存时间', '经历原文', '主稿对比'],
    rows: variants.map((variant) => {
      const project = String(variant.project || '');
      const compareButton = el('button', {
        className: 'button button-small button-quiet resume-compare-button',
        text: '与主稿对比',
        attrs: {
          type: 'button',
          'aria-label': `与主稿对比：${project || '未命名项目'}`,
          'data-resume-action': 'compare-variant'
        }
      });
      compareButton.addEventListener('click', () => compareVariantWithMaster(variant, compareButton));
      const projectCell = el('div', { className: 'sg-variant-project' });
      projectCell.append(el('span', { className: 'cell-text', text: project || '—' }));
      projectCell.append(el('span', {
        className: 'cell-mono sg-variant-sha',
        text: `SHA-256 ${String(variant.sha256 || '').slice(0, 16) || '—'}`
      }));
      return [
        projectCell,
        formatDateTime(variant.created_at),
        el('div', { className: 'cell-text', text: String(variant.text || '') }),
        el('div', { className: 'resume-compare-cell' }, [compareButton])
      ];
    }),
    emptyText: '还没有保存经历变体；保存后才能与主稿对比。',
    className: 'data-table-wide'
  });
}

function renderVariantCompareMessage(kind, message) {
  const container = dom.variantCompareResult;
  if (!container) return;
  clear(container);
  container.className = `action-result action-result-${kind} resume-compare-result`;
  container.hidden = false;
  container.append(el('p', { className: 'resume-compare-meta', text: message }));
}

function variantSegmentKindLabel(segment) {
  if (!segment || segment.kind === 'added') return '新增段落';
  if (segment.kind === 'removed') return '主稿有此段，变体未保留';
  return '改写';
}

function variantSegmentText(value) {
  return String(value === undefined || value === null ? '' : value);
}

function renderVariantCompareResult(data, variant) {
  const container = dom.variantCompareResult;
  if (!container) return;
  const info = data && typeof data === 'object' ? data : {};
  const summary = info.summary && typeof info.summary === 'object' ? info.summary : {};
  const segments = Array.isArray(info.segments) ? info.segments : [];
  const project = String(info.project || (variant && variant.project) || '').trim();
  clear(container);
  container.className = 'action-result action-result-ok resume-compare-result';
  container.hidden = false;
  container.append(el('p', {
    className: 'result-title',
    text: `与主稿对比：${project || '未命名项目'}`
  }));
  container.append(el('p', {
    className: 'resume-compare-meta',
    text: [
      `主稿来源：${String(info.master_source || '未提供')}`,
      `新增 ${toInt(summary.added)} 段`,
      `删除 ${toInt(summary.removed)} 段`,
      `改写 ${toInt(summary.changed)} 段`,
      `未改 ${toInt(summary.unchanged)} 段`
    ].join('，')
  }));
  if (info.identical === true || !segments.length) {
    container.append(el('p', {
      className: 'resume-compare-empty',
      text: '与主稿逐段一致，未发现新增、删除或改写。'
    }));
    return;
  }
  const list = el('ol', { className: 'resume-compare-list' });
  segments.forEach((segment) => {
    const kind = segment && segment.kind ? String(segment.kind) : 'changed';
    const item = el('li', { className: `resume-compare-segment is-${kind}` });
    item.append(el('span', {
      className: 'resume-compare-kind',
      text: variantSegmentKindLabel(segment)
    }));
    if (kind === 'changed') {
      const pair = el('div', { className: 'resume-compare-pair' });
      pair.append(el('span', { className: 'resume-compare-label', text: '主稿' }));
      pair.append(el('p', { className: 'resume-compare-text', text: variantSegmentText(segment.before) }));
      pair.append(el('span', { className: 'resume-compare-label', text: '变体' }));
      pair.append(el('p', { className: 'resume-compare-text', text: variantSegmentText(segment.after) }));
      item.append(pair);
    } else {
      item.append(el('p', {
        className: 'resume-compare-text',
        text: variantSegmentText(segment.text)
      }));
    }
    list.append(item);
  });
  container.append(list);
}

async function compareVariantWithMaster(variant, button) {
  if (button) {
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
  }
  try {
    const data = await postAction('compare-variant', {
      variant_id: String((variant && variant.id) || ''),
      project: String((variant && variant.project) || ''),
      text: String((variant && variant.text) || '')
    });
    renderVariantCompareResult(data, variant);
    setStatus('已生成对比；主稿和变体都没有改动。', 'ok');
  } catch (error) {
    const message = friendlyError(error);
    renderVariantCompareMessage('warn', message);
    setStatus(message, 'warn');
  } finally {
    if (button) {
      button.removeAttribute('aria-busy');
      button.disabled = false;
    }
  }
}

/* Render: data and reports */

// 相邻且标题、详情完全相同的记录合并成一组，用 ×N 表示次数（首页与设置页共用）；
// 详情里的 auto_submit 参数只对调试有用，这里去掉。
function groupActivityRows(rows) {
  const groups = [];
  (Array.isArray(rows) ? rows : []).forEach((row) => {
    const title = String((row && (row.title || row.action)) || '操作');
    const detail = String((row && row.detail) || '').replace(/；?\s*auto_submit=\w+/g, '').trim();
    const last = groups[groups.length - 1];
    if (last && last.title === title && last.detail === detail) {
      last.count += 1;
      return;
    }
    groups.push({ row: row || {}, title, detail, count: 1 });
  });
  return groups;
}

function renderActivity(container, activity) {
  if (!container) return;
  clear(container);
  const rows = Array.isArray(activity) ? activity : [];
  if (!rows.length) {
    container.append(el('p', { className: 'empty-state', text: '暂无操作记录。' }));
    return;
  }
  const groups = groupActivityRows(rows);
  const list = el('ul', { className: 'activity-list' });
  groups.forEach((group) => {
    const item = el('li', { className: 'activity-item' });
    item.append(el('span', { className: 'activity-time', text: formatDateTime(group.row.at) }));
    item.append(el('span', {
      className: 'activity-title',
      text: group.count > 1 ? `${group.title} ×${group.count}` : group.title
    }));
    const statusBadge = group.row.ok === false
      ? badge('拒绝', 'bad', '×')
      : badge('完成', 'good', '✓');
    statusBadge.classList.add('activity-state');
    item.append(statusBadge);
    if (group.detail) {
      item.append(el('span', { className: 'activity-detail', text: group.detail }));
    }
    list.append(item);
  });
  container.append(list);
}

function renderDefinitionList(container, rows) {
  if (!container) return;
  clear(container);
  const list = el('dl', { className: 'detail-list' });
  rows.forEach(([label, value]) => {
    list.append(el('dt', { text: label }), el('dd', { text: value }));
  });
  container.append(list);
}

function renderBoundaries(snapshot) {
  const boundaries = snapshot.boundaries && typeof snapshot.boundaries === 'object'
    ? snapshot.boundaries
    : {};
  const preferred = [
    'auto_submit', 'platform_scraping', 'browser_takeover', 'wechat_hook',
    'external_api', 'real_imap', 'real_feishu_http', 'real_asr'
  ];
  const keys = [
    ...preferred.filter((key) => Object.prototype.hasOwnProperty.call(boundaries, key)),
    ...Object.keys(boundaries).filter((key) => !preferred.includes(key))
  ];
  renderTable(dom.boundariesTable, {
    caption: '表：不可绕过的运行边界',
    columns: ['边界', '当前状态'],
    rows: keys.map((key) => [boundaryLabel(key), boundaryValue(boundaries[key])]),
    emptyText: '没有读到运行边界。',
    className: 'data-table-wide'
  });
}

function renderConfig(snapshot) {
  const config = snapshot.config && typeof snapshot.config === 'object' ? snapshot.config : {};
  const listText = (value) => (Array.isArray(value) && value.length ? value.join('、') : '—');
  const rows = [
    ['目标城市', listText(config.target_cities)],
    ['排除词', listText(config.excluded_terms)],
    ['岗位关键词', listText(config.title_keywords)],
    ['薪资下限', config.salary_min_threshold === undefined || config.salary_min_threshold === null
      ? '—'
      : `${toInt(config.salary_min_threshold)} 元`],
    ['筛选规则', '按岗位文档评分和必备条件自动筛选，不设分数门槛'],
    ['弱点标签', listText(config.weakness_tags)],
    ['简历技能命中', listText(snapshot.cv_skills)]
  ];
  renderDefinitionList(dom.configSummary, rows);
}

/* AI settings (08 设置): the stored API key is never sent back to the page. */

function renderAiSettings(settings) {
  if (!dom.aiSettingsForm || !settings) return;
  dom.aiSettingsService.value = settings.service || 'anthropic';
  dom.aiSettingsService.dataset.previousService = dom.aiSettingsService.value;
  dom.aiSettingsModel.value = settings.model || '';
  dom.aiSettingsBaseUrl.value = settings.base_url || '';
  dom.aiSettingsKey.value = '';
  dom.aiSettingsKey.placeholder = settings.key_configured ? '已保存密钥；留空表示不修改' : '尚未保存密钥';
  dom.aiSettingsBadge.textContent = settings.key_configured ? '已配置' : '未配置密钥';
  dom.aiSettingsBadge.className = `badge ${settings.key_configured ? 'badge-good' : 'badge-warn'}`;
}

function applyAiProviderDefaults() {
  if (!dom.aiSettingsService) return;
  const service = dom.aiSettingsService.value;
  const defaults = AI_PROVIDER_DEFAULTS[service] || AI_PROVIDER_DEFAULTS.custom;
  const previous = dom.aiSettingsService.dataset.previousService || '';
  const previousDefaults = AI_PROVIDER_DEFAULTS[previous] || { model: '', base_url: '' };
  // 只有仍是上一家默认值（或为空）时才替换，手填的值保留。
  if (dom.aiSettingsBaseUrl) {
    const current = dom.aiSettingsBaseUrl.value.trim();
    if (!current || current === previousDefaults.base_url) {
      dom.aiSettingsBaseUrl.value = defaults.base_url || '';
    }
  }
  if (dom.aiSettingsModel) {
    const current = dom.aiSettingsModel.value.trim();
    if (!current || current === previousDefaults.model) {
      dom.aiSettingsModel.value = defaults.model || '';
    }
  }
  dom.aiSettingsService.dataset.previousService = service;
  if (!dom.aiSettingsResult) return;
  const label = dom.aiSettingsService.selectedOptions[0]
    ? dom.aiSettingsService.selectedOptions[0].textContent
    : service;
  const baseUrl = dom.aiSettingsBaseUrl ? dom.aiSettingsBaseUrl.value.trim() : '';
  const model = dom.aiSettingsModel ? dom.aiSettingsModel.value.trim() : '';
  // Claude 官方预设的 Base URL 本来就是空（走官方默认地址），留空是合法的；
  // 其余服务商的 Base URL 有预设，只有「自定义」必须手填。
  const needsBaseUrl = service !== 'anthropic';
  if (needsBaseUrl && !baseUrl && !model) {
    showInline(dom.aiSettingsResult, '请填写 Base URL 与模型名', 'info');
    return;
  }
  if (needsBaseUrl && !baseUrl) {
    showInline(dom.aiSettingsResult, '请填写 Base URL', 'info');
    return;
  }
  if (!model) {
    showInline(dom.aiSettingsResult, '请填写模型名', 'info');
    return;
  }
  if (!defaults.base_url && !defaults.model) {
    showInline(dom.aiSettingsResult, `已切到 ${label}，保存后生效。`, 'info');
    return;
  }
  if (defaults.model && model !== defaults.model) {
    showInline(dom.aiSettingsResult, `已填入 ${label} 的 Base URL；模型名沿用当前值，保存前请确认。`, 'info');
    return;
  }
  const parts = [];
  if (defaults.base_url) parts.push('Base URL');
  if (defaults.model) parts.push('模型名');
  showInline(dom.aiSettingsResult, `已填入 ${label} 的默认 ${parts.join('与')}，保存后生效。`, 'info');
}

async function loadAiSettings() {
  if (!dom.aiSettingsForm) return;
  try {
    const data = await postAction('get-ai-settings');
    renderAiSettings(data);
  } catch (error) {
    dom.aiSettingsBadge.textContent = '读取失败';
    showInline(dom.aiSettingsResult, friendlyError(error), 'error');
  }
}

async function saveAiSettings(event) {
  event.preventDefault();
  const payload = {
    service: dom.aiSettingsService.value,
    model: dom.aiSettingsModel.value.trim(),
    base_url: dom.aiSettingsBaseUrl.value.trim(),
    api_key: dom.aiSettingsKey.value.trim()
  };
  const data = await runAction(dom.aiSettingsSave, () => postAction('save-ai-settings', payload));
  dom.aiSettingsKey.value = '';
  if (!data) return;
  renderAiSettings(data.settings);
  showInline(dom.aiSettingsResult, data.message || 'AI 接口已保存', 'ok');
  setStatus(data.message || 'AI 接口已保存', 'ok');
}

async function testAiSettings() {
  const data = await runAction(dom.aiSettingsTest, () => postAction('test-ai-connection'));
  if (!data) return;
  if (data.ok) {
    showInline(dom.aiSettingsResult, `连接成功：模型 ${data.model || ''}，耗时 ${data.elapsed_ms} 毫秒，回复「${data.reply || ''}」`, 'ok');
  } else {
    showInline(dom.aiSettingsResult, `连接失败：${data.reason || '未知原因'}`, 'error');
  }
}

function renderData(snapshot) {
  const downloads = Array.isArray(snapshot.downloads) ? snapshot.downloads : [];
  renderTable(dom.downloadsTable, {
    caption: '表：本地下载文件',
    columns: ['文件名', '大小', '修改时间', '操作'],
    rows: downloads.map((row) => [
      el('span', { className: 'cell-mono', text: String(row.name || '') }),
      formatBytes(row.bytes),
      formatDateTime(row.modified),
      downloadLink(String(row.name || ''), '下载')
    ]),
    emptyText: '暂无下载文件。生成准备清单、日历文件、题单或报告后会出现在这里。',
    className: 'data-table-wide'
  });
  renderBoundaries(snapshot);
  renderConfig(snapshot);
}

/* Top-level render */

function renderAll(snapshot) {
  renderMeta(snapshot);
  renderHomeToday(snapshot);
  renderPipeline(snapshot);
  renderProfile(snapshot.profile);
  renderOfferPilot(snapshot.pipeline && snapshot.pipeline.offerpilot);
  renderBelt(snapshot);
  renderKpis(snapshot);
  renderChannelChart(snapshot);
  renderQuarterChart(snapshot);
  renderWeaknessChart(snapshot);
  renderMailChart(snapshot);
  renderJobs(snapshot);
  renderQueue(snapshot);
  renderMails(snapshot);
  renderInterview(snapshot);
  renderData(snapshot);
  renderActivity(dom.activityData, snapshot.activity);
}

/* ATS */

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      const comma = result.indexOf(',');
      if (comma < 0) {
        reject(new Error('无法读取 PDF 内容。'));
        return;
      }
      resolve(result.slice(comma + 1));
    };
    reader.onerror = () => reject(new Error('读取本地 PDF 失败。'));
    reader.readAsDataURL(file);
  });
}

function renderAtsResult(result) {
  const info = result && typeof result === 'object' ? result : {};
  const container = dom.atsResult;
  clear(container);
  container.hidden = false;
  const verdict = String(info.verdict || 'needs_manual_check');
  const kind = verdict === 'pass' ? 'good' : verdict === 'fail' ? 'bad' : 'warn';
  const symbol = verdict === 'pass' ? '✓' : verdict === 'fail' ? '×' : '!';
  container.className = `action-result action-result-${kind === 'good' ? 'ok' : kind === 'bad' ? 'error' : 'warn'}`;
  container.append(el('p', { className: 'result-title', text: 'ATS 检查结果' }));
  const verdictLine = el('p');
  verdictLine.append(el('span', { text: 'verdict：' }), badge(verdictLabel(verdict), kind, symbol));
  container.append(verdictLine);

  const details = el('dl', { className: 'detail-list' });
  [
    ['文件', String(info.uploaded_filename || '—')],
    ['text_layer', textLayerLabel(String(info.text_layer || 'unavailable'))],
    ['页数提示', info.page_count_hint === null || info.page_count_hint === undefined
      ? '未知'
      : String(info.page_count_hint)],
    ['提取到的字数', String(toInt(info.extracted_text_chars))],
    ['关键词是否全部找到', info.all_keywords_found === true
      ? '是'
      : info.all_keywords_found === false
        ? '否'
        : '未检查']
  ].forEach(([key, value]) => {
    details.append(el('dt', { text: key }), el('dd', { text: value }));
  });
  container.append(details);

  const matches = info.keyword_matches && typeof info.keyword_matches === 'object'
    ? info.keyword_matches
    : {};
  const matchRows = Object.keys(matches).map((keyword) => [keyword, keywordMatchLabel(matches[keyword])]);
  if (matchRows.length) {
    const mount = el('div');
    renderTable(mount, {
      caption: '表：关键词命中（仅基于可提取文字）',
      columns: ['关键词', '结果'],
      rows: matchRows,
      emptyText: '未提供关键词。'
    });
    container.append(mount);
  } else {
    container.append(el('p', { className: 'card-meta', text: '没有提供关键词，未做检查。' }));
  }

  const notes = Array.isArray(info.notes) ? info.notes : [];
  if (notes.length) {
    const wrap = el('div');
    wrap.append(el('p', { className: 'card-subtitle', text: '检查备注' }));
    const ul = el('ul');
    notes.forEach((note) => ul.append(el('li', { text: String(note) })));
    wrap.append(ul);
    container.append(wrap);
  }

  if (verdict === 'needs_manual_check') {
    container.append(el('p', {
      className: 'notice',
      text: '「需人工检查」不等于通过；请自己核对文字层、分栏、表格和扫描件。'
    }));
  }
}

/* Operations */

function showOpsResult(options) {
  const container = dom.opsResult;
  clear(container);
  container.hidden = false;
  container.className = `action-result action-result-${options.kind || 'ok'}`;
  container.append(el('p', { className: 'result-title', text: options.title || '操作结果' }));
  if (options.summary) container.append(el('p', { text: options.summary }));
  if (options.lines && options.lines.length) {
    const ul = el('ul');
    options.lines.forEach((line) => ul.append(el('li', { text: String(line) })));
    container.append(ul);
  }
  if (options.download) {
    const row = el('p', { className: 'download-row' });
    row.append(el('span', { text: '下载：' }), downloadLink(options.download));
    container.append(row);
  }
  if (options.pre) {
    container.append(el('pre', { className: 'code-block', text: String(options.pre) }));
  }
}

async function runTests() {
  const data = await runAction(dom.runTestsButton, () => postJson('/api/run-tests', {}));
  if (!data) return;
  const summary = data.summary || `运行 ${toInt(data.tests_run)} 项测试。`;
  setStatus(summary, data.ok ? 'ok' : 'warn');
  showOpsResult({
    title: '测试结果',
    summary,
    lines: [
      `测试数：${toInt(data.tests_run)}`,
      `失败：${toInt(data.failures)}`,
      `错误：${toInt(data.errors)}`
    ],
    pre: data.output || '（无输出）',
    kind: data.ok ? 'ok' : 'warn'
  });
}

async function generateWebReport() {
  const data = await runAction(dom.webReportButton, () => postJson('/api/web-report', { mode: state.mode }));
  if (!data) return;
  setStatus(data.message || '网页验收报告已生成。', data.ok ? 'ok' : 'warn');
  showOpsResult({
    title: '网页验收报告',
    summary: data.message || '',
    lines: data.tests ? [String(data.tests.summary || '')] : [],
    download: data.download || '',
    kind: data.ok ? 'ok' : 'warn'
  });
  await loadState();
}

async function exportData() {
  const data = await runAction(dom.exportButton, () => postJson('/api/export', { mode: state.mode }));
  if (!data) return;
  setStatus(data.message || '本地数据已导出。', data.ok ? 'ok' : 'warn');
  showOpsResult({
    title: '导出 JSON',
    summary: data.message || '',
    lines: data.bytes ? [`文件大小：${formatBytes(data.bytes)}`] : [],
    download: data.download || '',
    kind: data.ok ? 'ok' : 'warn'
  });
  await loadState();
}

/* Event handlers */

function bindEvents() {
  bindInterviewChat();
  dom.navItems.forEach((button) => {
    button.addEventListener('click', () => showView(button.dataset.view));
  });

  document.querySelectorAll('.ui-hub-tab').forEach((button) => {
    button.addEventListener('click', () => showView(button.dataset.view));
  });

  document.querySelectorAll('[data-view-link]').forEach((button) => {
    button.addEventListener('click', () => showView(button.dataset.viewLink));
  });

  
  dom.themeButtons.forEach((button) => {
    button.addEventListener('click', () => applyTheme(button.dataset.themeChoice));
  });

  dom.refreshButton.addEventListener('click', () => loadState({ announce: true }));

  if (dom.profileForm) {
    const markProfileDirty = () => {
      if (state.profileDirty) return;
      state.profileDirty = true;
      renderProfile(state.snapshot && state.snapshot.profile);
    };
    dom.profileForm.addEventListener('input', markProfileDirty);
    dom.profileForm.addEventListener('change', markProfileDirty);
    dom.profileForm.addEventListener('submit', saveProfileForm);
  }
  if (dom.profileImport) {
    dom.profileImport.addEventListener('click', chooseProfileCv);
  }
  bindResumeDrops();
  document.querySelectorAll('[data-profile-add]').forEach((button) => {
    button.addEventListener('click', () => addProfileRow(button.dataset.profileAdd, {}));
  });

  if (dom.offerpilotRefresh) {
    dom.offerpilotRefresh.addEventListener('click', () => refreshOfferPilot({ announce: true }));
  }
  [dom.offerpilotRisk, dom.offerpilotConfirm].forEach((checkbox) => {
    if (checkbox) checkbox.addEventListener('change', syncOfferPilotStartState);
  });
  if (dom.offerpilotMode) {
    dom.offerpilotMode.addEventListener('change', () => {
      syncCollectModeUI();
      maybeRunOfferPilotPreflight();
    });
  }
  [dom.collectPlatform, dom.collectKeywords, dom.collectCities, dom.collectPages, dom.collectPace, dom.collectAutoScore].forEach((input) => {
    if (!input) return;
    input.addEventListener('input', syncCollectModeUI);
    input.addEventListener('change', syncCollectModeUI);
  });
  if (dom.collectPreflight) {
    dom.collectPreflight.addEventListener('click', () => runOfferPilotPreflight(dom.collectPreflight));
  }
  if (dom.collectResumeUpload && dom.collectResumeFile) {
    dom.collectResumeUpload.addEventListener('click', () => dom.collectResumeFile.click());
    dom.collectResumeFile.addEventListener('change', () => {
      const file = dom.collectResumeFile.files && dom.collectResumeFile.files[0];
      dom.collectResumeFile.value = '';
      uploadOfferPilotResume(file);
    });
  }
  if (dom.collectAutoScore) {
    dom.collectAutoScore.addEventListener('change', () => {
      state.offerpilotAutoScoreTouched = true;
    });
  }
  if (dom.offerpilotImport) {
    dom.offerpilotImport.addEventListener('click', () => importOfferPilotJobs(dom.offerpilotImport));
  }
  if (dom.offerpilotOpenJobs) {
    dom.offerpilotOpenJobs.addEventListener('click', () => showView('jobs'));
  }
  if (dom.offerpilotForm) {
    dom.offerpilotForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      await startOfferPilotTask(dom.offerpilotStart);
    });
  }

  dom.queueSelectAll.addEventListener('change', () => {
    const pending = pendingQueueRows();
    if (dom.queueSelectAll.checked) {
      pending.forEach((row) => state.queueSelection.add(String(row.id)));
    } else {
      state.queueSelection.clear();
    }
    syncQueueCheckboxes();
    updateQueueSelectionUI();
  });

  if (dom.queueApprovedSelectAll) {
    dom.queueApprovedSelectAll.addEventListener('change', () => {
      const approved = approvedQueueRows();
      if (dom.queueApprovedSelectAll.checked) {
        approved.forEach((row) => state.queueApprovedSelection.add(String(row.id)));
      } else {
        state.queueApprovedSelection.clear();
      }
      dom.queueApprovedTable.querySelectorAll('input.queue-check').forEach((box) => {
        box.checked = state.queueApprovedSelection.has(box.dataset.queueId);
      });
      updateQueueApprovedSelectionUI();
    });
  }
  if (dom.queueGenerateGreetings) {
    dom.queueGenerateGreetings.addEventListener('click', () => {
      generateQueueGreetings(dom.queueGenerateGreetings);
    });
  }
  if (dom.queueSendGreetings) {
    dom.queueSendGreetings.addEventListener('click', () => openDeliveryPanel(dom.queueSendGreetings));
  }
  if (dom.queueDeliveryCancel) {
    dom.queueDeliveryCancel.addEventListener('click', closeDeliveryModal);
  }
  if (dom.queueDeliveryRisk) {
    dom.queueDeliveryRisk.addEventListener('change', updateDeliveryStartState);
  }
  if (dom.queueDeliveryStart) {
    dom.queueDeliveryStart.addEventListener('click', () => {
      startQueueDelivery(dom.queueDeliveryStart);
    });
  }

  dom.queueConfirmButton.addEventListener('click', async () => {
    const ids = Array.from(state.queueSelection);
    if (!ids.length) {
      setStatus('请先勾选要确认的岗位。', 'error');
      return;
    }
    const data = await runAction(dom.queueConfirmButton, () => postAction('confirm', { ids }));
    if (!data) return;
    const ok = announceActionResult(data, '已通过。发送前还会让你再核对一次。');
    if (ok) {
      state.queueSelection.clear();
      updateQueueSelectionUI();
    }
    await loadState();
  });

  if (dom.jobsSelectAll) {
    dom.jobsSelectAll.addEventListener('change', () => {
      const jobs = (state.snapshot && Array.isArray(state.snapshot.jobs)) ? state.snapshot.jobs : [];
      if (dom.jobsSelectAll.checked) jobs.forEach((job) => state.jobsSelection.add(String(job.id)));
      else state.jobsSelection.clear();
      renderJobs(state.snapshot || {});
    });
  }
  if (dom.jobsBulkEnqueue) {
    dom.jobsBulkEnqueue.addEventListener('click', () => {
      const jobs = (state.snapshot && Array.isArray(state.snapshot.jobs)) ? state.snapshot.jobs : [];
      const selected = jobs.filter((job) => state.jobsSelection.has(String(job.id)));
      if (!selected.length) return;
      // 与后端一致：没有文档评分、必备条件不满足或已关闭的岗位需要手动加入。
      const manualJobs = selected.filter((job) => jobNeedsManualEnqueue(job));
      const needsManual = manualJobs.length > 0;
      if (needsManual) {
        const reason = dom.jobsOverrideReason ? dom.jobsOverrideReason.value : '所选原因';
        const ok = window.confirm(
          `所选 ${selected.length} 条岗位中，其中 ${manualJobs.length} 条将按手动加入处理，原因：${reason}。`
          + '其余岗位按岗位文档评分自动判断。继续吗？'
        );
        if (!ok) return;
      }
      enqueueJobs(selected, dom.jobsBulkEnqueue, needsManual);
    });
  }
  if (dom.jobsBulkDelete) {
    dom.jobsBulkDelete.addEventListener('click', () => {
      const jobs = (state.snapshot && Array.isArray(state.snapshot.jobs)) ? state.snapshot.jobs : [];
      const selected = jobs.filter((job) => state.jobsSelection.has(String(job.id)));
      if (!selected.length) return;
      jobsDeleteSelected(selected, dom.jobsBulkDelete);
    });
  }
  if (dom.jobsDossierClose) {
    dom.jobsDossierClose.addEventListener('click', closeJobDossier);
  }
  if (dom.queueReviewClose) {
    dom.queueReviewClose.addEventListener('click', closeQueueReview);
  }
  // 抽屉没有遮罩，Esc 关闭；弹窗打开时交给弹窗自己的 Esc 处理。
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (state.hrReplyModalOpen || state.queueDeliveryOpen) return;
    if (dom.jobsDossier && !dom.jobsDossier.hidden) {
      event.preventDefault();
      closeJobDossier();
    } else if (dom.queueReview && !dom.queueReview.hidden) {
      event.preventDefault();
      closeQueueReview();
    }
  });

  dom.jdForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = dom.jdText.value.trim();
    if (!text) {
      setStatus('请先粘贴 JD 文本。', 'error');
      dom.jdText.focus();
      return;
    }
    const payload = {
      text,
      source_channel: dom.jdChannel.value.trim() || 'manual_paste'
    };
    const data = await runAction(dom.jdSubmit, () => postAction('parse-jd', payload));
    if (!data) return;
    const parsedJob = data.job && typeof data.job === 'object' ? data.job : {};
    const warnings = Array.isArray(parsedJob.warnings) ? parsedJob.warnings : [];
    const reasons = parsedJob.hard_filter && Array.isArray(parsedJob.hard_filter.reasons)
      ? parsedJob.hard_filter.reasons
      : [];
    let message = data.message || (data.ok === false
      ? (data.duplicate ? '相同岗位已存在。' : '岗位未录入。')
      : '岗位已录入本地工作区。');
    const warningText = reasonText(warnings);
    const reasonSummary = reasonText(reasons);
    if (warningText) message += ` 提醒：${warningText}`;
    if (reasonSummary) message += ` 被拦下的原因：${reasonSummary}`;
    if (data.ok === false) {
      setStatus(message, data.duplicate ? 'warn' : 'error');
      showInline(dom.jdResult, message, data.duplicate ? 'warn' : 'error');
      return;
    }
    const kind = warnings.length || reasons.length ? 'warn' : 'ok';
    setStatus(message, kind);
    showInline(dom.jdResult, message, kind);
    dom.jdText.value = '';
    await loadState();
  });

  dom.importForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = dom.importJson.value.trim();
    if (!text) {
      setStatus('请先粘贴要导入的 JSON。', 'error');
      return;
    }
    const data = await runAction(document.getElementById('import-submit'), () => postAction('import-jobs', { text }));
    if (!data) return;
    const added = Array.isArray(data.added) ? data.added.length : 0;
    const duplicates = toInt(data.duplicates);
    let message = data.message || `已导入 ${added} 条。`;
    if (duplicates) message += ` 跳过重复 ${duplicates} 条。`;
    setStatus(message, added > 0 ? 'ok' : 'warn');
    showInline(dom.importResult, message, added > 0 ? 'ok' : 'warn');
    await loadState();
  });

  dom.atsForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const file = dom.atsFile.files && dom.atsFile.files[0];
    if (!file) {
      const message = '请先选择一个 PDF 文件。';
      setStatus(message, 'error');
      showInline(dom.atsResult, message, 'error');
      if (dom.atsFile) dom.atsFile.focus();
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      const message = 'PDF 超过 5 MB，没有上传。';
      setStatus(message, 'error');
      showInline(dom.atsResult, message, 'error');
      if (dom.atsFile) dom.atsFile.focus();
      return;
    }
    const keywords = dom.atsKeywords.value.trim();
    const data = await runAction(dom.atsSubmit, async () => {
      const content = await readFileAsBase64(file);
      return postAction('check-pdf', {
        filename: file.name,
        content_base64: content,
        keywords
      });
    });
    if (!data) return;
    setStatus(data.message || '检查完成；提取不到的文字仍需自己核对。', 'ok');
    renderAtsResult(data.result);
  });

  dom.mailForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = {
      subject: dom.mailSubject.value,
      body: dom.mailBody.value,
      from: dom.mailFrom.value,
      date: dom.mailDate.value,
      message_id: dom.mailMessageId.value
    };
    if (!payload.subject.trim() && !payload.body.trim()) {
      setStatus('请至少填写邮件主题或正文。', 'error');
      return;
    }
    const data = await runAction(dom.mailSubmit, () => postAction('parse-mail', payload));
    if (!data) return;
    if (data.ok === false) {
      setStatus(data.message || '邮件未新增。', data.duplicate ? 'warn' : 'error');
    } else {
      setStatus(data.message || '邮件已按离线规则分类。', 'ok');
    }
    if (data.classification) {
      renderClassification(dom.mailResult, data.classification, payload);
    }
    await loadState();
  });

  if (dom.hrRefresh) {
    dom.hrRefresh.addEventListener('click', () => hrRefreshAll());
  }
  if (dom.hrMobileBack) {
    dom.hrMobileBack.addEventListener('click', () => hrSetMobilePane('list'));
  }
  if (dom.hrSearch) {
    dom.hrSearch.addEventListener('input', () => {
      state.hrSearch = dom.hrSearch.value;
      renderHrConversations();
    });
    dom.hrSearch.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && dom.hrSearch.value) {
        event.stopPropagation();
        dom.hrSearch.value = '';
        state.hrSearch = '';
        renderHrConversations();
      }
    });
  }
  if (dom.hrPlatformSelect) {
    dom.hrPlatformSelect.addEventListener('change', () => {
      const platform = String(dom.hrPlatformSelect.value || 'all');
      state.hrPlatform = platform;
      const selected = hrConversationById(state.hrSelectedId);
      if (platform !== 'all' && selected && String(selected.platform || 'boss') !== platform) {
        const first = filteredHrConversations()[0];
        if (first) {
          selectHrConversation(first.id);
          return;
        }
        state.hrSelectedId = '';
        state.hrThread = null;
      }
      renderHrConversations();
    });
  }
  dom.hrFilterButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const filter = String(button.dataset.hrFilter || '');
      if (!filter) return;
      state.hrFilter = filter;
      renderHrConversations();
    });
  });
  if (dom.hrReplyForm) {
    dom.hrReplyForm.addEventListener('submit', (event) => {
      event.preventDefault();
      openHrReplyModal(dom.hrReplySend);
    });
  }
  if (dom.hrReplyInput) {
    dom.hrReplyInput.addEventListener('input', () => {
      const id = String(state.hrSelectedId || '');
      if (!id) return;
      state.hrDrafts[id] = dom.hrReplyInput.value;
      updateHrComposerState();
    });
    // Ctrl/⌘ + Enter 只打开确认框；真正发送仍要点确认。
    dom.hrReplyInput.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' || !(event.ctrlKey || event.metaKey)) return;
      event.preventDefault();
      openHrReplyModal(dom.hrReplySend);
    });
  }
  if (dom.hrReplyModalCancel) {
    dom.hrReplyModalCancel.addEventListener('click', closeHrReplyModal);
  }
  if (dom.hrReplyModalRisk) {
    dom.hrReplyModalRisk.addEventListener('change', updateHrReplyConfirmState);
  }
  if (dom.hrReplyConfirm) {
    dom.hrReplyConfirm.addEventListener('click', submitHrReply);
  }

  dom.worksheetForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const minutes = Number(dom.worksheetMinutes.value);
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 180) {
      const message = '时长必须是 1–180 分钟的整数。';
      setStatus(message, 'error');
      showInline(dom.worksheetResult, message, 'error');
      if (dom.worksheetMinutes) dom.worksheetMinutes.focus();
      return;
    }
    const data = await runAction(dom.worksheetSubmit, () => postAction('worksheet', {
      minutes,
      jd: dom.worksheetJd.value
    }));
    if (!data) return;
    const count = toInt(data.question_count);
    const kind = count > 0 ? 'ok' : 'warn';
    setStatus(data.message || '题单已生成。', kind);
    showTextResult(dom.worksheetResult, {
      message: data.message || '题单已生成。',
      meta: `共 ${count} 题，计划 ${minutes} 分钟；题库为空时不会编造题目`,
      text: data.worksheet || '',
      downloadNames: data.download ? [data.download] : [],
      kind
    });
    if (count === 0) {
      // 0 题时给出下一步入口，不用用户自己返回卡片找题库。
      const next = el('p', { className: 'sg-empty-next' });
      const toLibrary = el('button', {
        className: 'button button-quiet button-small',
        text: '去题库补充题目',
        attrs: { type: 'button' }
      });
      toLibrary.addEventListener('click', () => showInterviewModule('library'));
      next.append(toLibrary);
      dom.worksheetResult.append(next);
    }
    await loadState();
  });

  dom.debriefForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const transcript = dom.debriefTranscript.value.trim();
    if (!transcript) {
      const message = '请先粘贴逐字稿。';
      setStatus(message, 'error');
      showInline(dom.debriefResult, message, 'error');
      if (dom.debriefTranscript) dom.debriefTranscript.focus();
      return;
    }
    const data = await runAction(dom.debriefSubmit, () => postAction('debrief', { transcript }));
    if (!data) return;
    if (data.ok === false) {
      setStatus(data.message || '复盘未新增。', data.duplicate ? 'warn' : 'error');
    } else {
      setStatus(data.message || '复盘卡片已生成。', 'ok');
    }
    if (data.card) {
      clear(dom.debriefResult);
      dom.debriefResult.hidden = false;
      dom.debriefResult.className = 'action-result action-result-ok';
      dom.debriefResult.append(buildDebriefCard(data.card, false));
    }
    await loadState();
  });

  dom.bankForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const question = dom.bankQuestion.value.trim();
    if (!question) {
      setStatus('题目不能为空。', 'error');
      return;
    }
    const data = await runAction(dom.bankSubmit, () => postAction('add-question', {
      question,
      section: dom.bankSection.value
    }));
    if (!data) return;
    if (data.ok === false) {
      setStatus(data.message || '题目未加入。', data.duplicate ? 'warn' : 'error');
      showInline(dom.bankResult, data.message || '题目未加入。', data.duplicate ? 'warn' : 'error');
      return;
    }
    setStatus(data.message || '题目已加入本地题库。', 'ok');
    showInline(dom.bankResult, data.message || '题目已加入本地题库。', 'ok');
    dom.bankQuestion.value = '';
    await loadState();
  });

  dom.variantForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const project = dom.variantProject.value.trim();
    const text = dom.variantText.value.trim();
    if (!project || !text) {
      const message = '项目名和经历原文不能为空。';
      setStatus(message, 'error');
      showInline(dom.variantResult, message, 'error');
      const focusTarget = !project ? dom.variantProject : dom.variantText;
      if (focusTarget) focusTarget.focus();
      return;
    }
    const data = await runAction(dom.variantSubmit, () => postAction('add-variant', { project, text }));
    if (!data) return;
    if (data.ok === false) {
      setStatus(data.message || '经历变体未保存。', data.duplicate ? 'warn' : 'error');
      showInline(dom.variantResult, data.message || '经历变体未保存。', data.duplicate ? 'warn' : 'error');
      appendVariantQualityHints(dom.variantResult, data.quality);
      return;
    }
    setStatus(data.message || '经历原文已保存，主简历没有被改动。', 'ok');
    showInline(dom.variantResult, data.message || '经历原文已保存。', 'ok');
    appendVariantQualityHints(dom.variantResult, data.quality);
    dom.variantProject.value = '';
    dom.variantText.value = '';
    await loadState();
  });

  dom.runTestsButton.addEventListener('click', runTests);
  dom.webReportButton.addEventListener('click', generateWebReport);
  dom.exportButton.addEventListener('click', exportData);
  if (dom.aiSettingsForm) {
    dom.aiSettingsForm.addEventListener('submit', saveAiSettings);
    if (dom.aiSettingsTest) dom.aiSettingsTest.addEventListener('click', testAiSettings);
    if (dom.aiSettingsService) dom.aiSettingsService.addEventListener('change', applyAiProviderDefaults);
    loadAiSettings();
  }
  
  dom.dryRunForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = await runAction(dom.dryRunButton, () => postAction('dry-run', {
      job_id: dom.dryJobId.value,
      company: dom.dryCompany.value,
      title: dom.dryTitle.value,
      status: dom.dryStatus.value,
      source_channel: dom.dryChannel.value
    }));
    if (!data) return;
    setStatus(data.message || '已生成通知预览；没有发出任何请求。', 'ok');
    dom.dryRunResult.hidden = false;
    dom.dryRunResult.textContent = JSON.stringify(data.result || data, null, 2);
    const emptyNote = document.getElementById('sg-dry-empty');
    if (emptyNote) emptyNote.hidden = true;
  });

}

function bindAmbient() {
  const follow = document.getElementById('ambient-follow');
  if (!follow || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  let targetX = 0.42;
  let targetY = 0.28;
  let currentX = targetX;
  let currentY = targetY;
  let frame = 0;

  const draw = () => {
    currentX += (targetX - currentX) * 0.06;
    currentY += (targetY - currentY) * 0.06;
    follow.style.setProperty('--mx', currentX.toFixed(3));
    follow.style.setProperty('--my', currentY.toFixed(3));
    if (Math.abs(targetX - currentX) > 0.001 || Math.abs(targetY - currentY) > 0.001) {
      frame = window.requestAnimationFrame(draw);
    } else {
      frame = 0;
    }
  };

  window.addEventListener('pointermove', (event) => {
    targetX = event.clientX / Math.max(1, window.innerWidth);
    targetY = event.clientY / Math.max(1, window.innerHeight);
    if (!frame) frame = window.requestAnimationFrame(draw);
  }, { passive: true });
}

function init() {
  applyTheme(state.theme);
  dom.mailDate.value = todayIso();
  showView('workbench');
  bindEvents();
  bindAmbient();
  hrStartPolling();
  updateQueueSelectionUI();
  loadState({ announce: true });
}

init();
