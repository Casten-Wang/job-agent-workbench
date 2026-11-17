'use strict';

/* Local-only workbench. All dynamic text is written with textContent or DOM
   attributes; API data is never interpolated into HTML. */

const SVG_NS = 'http://www.w3.org/2000/svg';
const PERIOD_LABELS = {
  all: '全部时间',
  '7d': '近 7 天',
  '30d': '近 30 天',
  '90d': '近 90 天'
};
const CHANNEL_LABELS = {
  all: '全部渠道',
  manual_paste: '手动粘贴',
  offerpilot_manual_export: '岗位自动化导出',
  boss: 'Boss直聘',
  liepin: '猎聘',
  '51job': '前程无忧',
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
  real_asr: '真实 ASR'
};
const BOUNDARY_VALUES = {
  embedded_offerpilot_only: '岗位自动化（仅本机、人工确认投递）',
  not_implemented_offline_build: '未实现（离线版本）',
  dry_run_only: '仅 dry-run',
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
const OFFERPILOT_IMPORTED_TASKS_KEY = 'offerpilot.importedTasks';
const OFFERPILOT_PACE = {
  cautious: { label: '稳健', multiplier: 3.0 },
  standard: { label: '标准', multiplier: 1.5 },
  fast: { label: '快速', multiplier: 1.0 }
};
const OFFERPILOT_MODE_HINTS = {
  collect: '采集岗位并按你的简历评分，不投递、不发消息。',
  monitor: '只检查已有会话中的 HR 回复，不采集新岗位、不发送消息。',
  full: '采集后调用 AI 评分并生成招呼语；发送仍会停在人工确认门。'
};
const OFFERPILOT_JOB_STATUS_LABELS = {
  pending: '待评分',
  scored: '已评分',
  filtered: '已过滤',
  greeted: '已生成招呼语',
  sent: '已发送',
  replied: '已回复',
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
  mode: safeLocalGet('job-workbench-mode') === 'user' ? 'user' : 'demo',
  theme: ['auto', 'light', 'dark'].includes(safeLocalGet('job-workbench-theme'))
    ? safeLocalGet('job-workbench-theme')
    : 'auto',
  period: 'all',
  channel: 'all',
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
  offerpilotSelection: new Set(),
  offerpilotPreflight: null,
  offerpilotPreflightKey: '',
  offerpilotTaskActive: false,
  offerpilotAutoImporting: false,
  offerpilotPrefsMode: null,
  offerpilotPollTimer: null,
  offerpilotResume: null,
  offerpilotAutoScoreTouched: false,
  jobsSelection: new Set(),
  queueApprovedSelection: new Set(),
  queueDeliveryIds: [],
  profileDirty: false,
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
  modeBanner: document.getElementById('mode-banner'),
  generatedAt: document.getElementById('generated-at'),
  loadingNote: document.getElementById('loading-note'),
  refreshButton: document.getElementById('refresh-button'),
  filterBar: document.querySelector('.filter-bar'),
  filterPeriod: document.getElementById('filter-period'),
  filterChannel: document.getElementById('filter-channel'),
  filterState: document.getElementById('filter-state'),
  scopeLine: document.getElementById('scope-line'),
  belt: document.getElementById('belt'),
  beltFocus: document.getElementById('belt-focus'),
  pipeline: document.getElementById('pipeline'),
  pipelineConnection: document.getElementById('pipeline-connection'),
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
  activityOverview: document.getElementById('activity-overview'),
  activityData: document.getElementById('activity-data'),
  jdForm: document.getElementById('jd-form'),
  jdText: document.getElementById('jd-text'),
  jdChannel: document.getElementById('jd-channel'),
  jdScore: document.getElementById('jd-score'),
  jdSubmit: document.getElementById('jd-submit'),
  jdResult: document.getElementById('jd-result'),
  importForm: document.getElementById('import-form'),
  importJson: document.getElementById('import-json'),
  importResult: document.getElementById('import-result'),
  jobsCount: document.getElementById('jobs-count'),
  jobsEmptyHint: document.getElementById('jobs-empty-hint'),
  jobsTable: document.getElementById('jobs-table'),
  jobsActionResult: document.getElementById('jobs-action-result'),
  jobsSelectAll: document.getElementById('jobs-select-all'),
  jobsSelectionCount: document.getElementById('jobs-selection-count'),
  jobsBulkEnqueue: document.getElementById('jobs-bulk-enqueue'),
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
  collectAutoScore: document.getElementById('collect-auto-score'),
  collectResumeFile: document.getElementById('collect-resume-file'),
  collectResumeUpload: document.getElementById('collect-resume-upload'),
  collectResumeStatus: document.getElementById('collect-resume-status'),
  collectSummary: document.getElementById('collect-summary'),
  collectChecks: document.getElementById('collect-checks'),
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
  profileSave: document.getElementById('profile-save'),
  profileResult: document.getElementById('profile-result'),
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
  queueDeliveryPanel: document.getElementById('queue-delivery-panel'),
  queueDeliverySummary: document.getElementById('queue-delivery-summary'),
  queueDeliveryList: document.getElementById('queue-delivery-list'),
  queueDeliveryConfirm: document.getElementById('queue-delivery-confirm'),
  queueDeliveryRisk: document.getElementById('queue-delivery-risk'),
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
  runTestsButton: document.getElementById('run-tests-button'),
  webReportButton: document.getElementById('web-report-button'),
  exportButton: document.getElementById('export-button'),
  resetDemoButton: document.getElementById('reset-demo-button'),
  resetNote: document.getElementById('reset-note'),
  opsResult: document.getElementById('ops-result'),
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
  modeButtons: Array.from(document.querySelectorAll('[data-mode]')),
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

function periodLabel(value) {
  return PERIOD_LABELS[value] || String(value || '全部时间');
}

function channelLabel(value) {
  if (value === undefined || value === null || value === '') return CHANNEL_LABELS.unknown;
  const key = String(value);
  return CHANNEL_LABELS[key] || key;
}

function stateLabel(value) {
  if (!value || value === 'all') return '全部状态';
  return String(value);
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

function setStatus(message, kind = 'ok') {
  const safeKind = ['ok', 'warn', 'error', 'info'].includes(kind) ? kind : 'info';
  dom.status.textContent = String(message || '');
  dom.status.className = `status status-${safeKind}`;
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
    return '无法连接本地服务；请确认 web/server.py 正在运行。';
  }
  if (error && error.message) return error.message;
  return '未知错误。';
}

async function parseResponse(response) {
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error(`服务返回了无法解析的响应（HTTP ${response.status}）。`);
  }
  if (!response.ok) {
    const message = data && data.error ? data.error : `请求失败（HTTP ${response.status}）。`;
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
      period: state.period,
      channel: state.channel,
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
      const modeText = data.mode === 'demo' ? '演示数据' : '用户数据';
      setStatus(`已载入${modeText}；生成时间 ${formatDateTime(data.generated_at)}。`, 'ok');
    }
  } catch (error) {
    if (seq !== state.fetchSeq) return;
    setStatus(`载入失败：${friendlyError(error)}`, 'error');
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
    setStatus(`操作失败：${friendlyError(error)}`, 'error');
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

function syncModeButtons() {
  dom.modeButtons.forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.mode === state.mode));
  });
}

function showView(name) {
  const hub = HUB_FOR_VIEW[name] || name;
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
  // 时间/渠道/状态筛选只作用于工作台快照，其他入口显示会变成无关噪音。
  if (dom.filterBar) dom.filterBar.hidden = name !== 'workbench';
  window.scrollTo({ top: 0, behavior: 'auto' });
  if (name === 'interview') showInterviewModule(null);
  if (name === 'collect') {
    if (state.offerpilotConnected && !state.offerpilotJobsLoaded) loadOfferPilotJobs();
    if (state.offerpilotConnected) maybeRunOfferPilotPreflight();
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
        'aria-label': `${card.title}，${card.count} ${card.unit}，${statusLabel}；打开${card.title}`
      }
    }, [
      el('span', { className: 'pipeline-top' }, [
        el('span', { className: 'pipeline-index', text: String(index + 1).padStart(2, '0') }),
        el('span', { className: 'pipeline-owner', text: card.owner })
      ]),
      el('span', { className: 'pipeline-name', text: card.title }),
      el('span', { className: 'pipeline-desc', text: card.description }),
      el('span', { className: 'pipeline-count' }, [
        el('strong', { text: String(card.count) }),
        el('span', { text: card.unit })
      ]),
      el('span', { className: 'pipeline-status', text: statusLabel })
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
    dom.profileResult,
    dom.opsResult
  ].forEach(resetContainer);
  dom.dryRunResult.hidden = true;
  dom.dryRunResult.textContent = '';
  dom.atsFile.value = '';
  state.queueSelection.clear();
}

function switchMode(mode) {
  if (mode !== 'demo' && mode !== 'user') return;
  if (mode === state.mode) return;
  state.mode = mode;
  safeLocalSet('job-workbench-mode', mode);
  state.period = 'all';
  state.channel = 'all';
  state.jobState = 'all';
  state.profileDirty = false;
  dom.filterPeriod.value = 'all';
  clearTransientResults();
  syncModeButtons();
  resetInterviewChat();
  loadChatLibrary();
  loadState({ announce: true });
}

function handleFilterChange() {
  state.period = dom.filterPeriod.value;
  state.channel = dom.filterChannel.value;
  state.jobState = dom.filterState.value;
  loadState();
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
    const cell = el('td', {
      className: 'empty-cell',
      text: options.emptyText || '暂无数据。'
    });
    cell.setAttribute('colspan', String(options.columns.length));
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
      const labelText = `${category} · ${series.label}：${value}`;
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
  syncModeButtons();
  const demo = snapshot.mode === 'demo';
  dom.modeBanner.className = `mode-banner ${demo ? 'is-demo' : 'is-user'}`;
  dom.modeBanner.textContent = demo
    ? '演示模式：全部为虚构测试数据，仅用于验证工作台。'
    : '用户数据模式：只读写本机 web/data/user。';
  dom.generatedAt.textContent = `生成于 ${formatDateTime(snapshot.generated_at)} · ${demo ? '演示数据' : '用户数据'}`;

  const filter = snapshot.filter || {};
  const scope = snapshot.scope || {};
  dom.scopeLine.textContent = [
    `筛选范围：${periodLabel(filter.period)} / ${channelLabel(filter.channel)} / ${stateLabel(filter.state)}`,
    `显示 ${toInt(scope.jobs)} / 共 ${toInt(scope.all_jobs)} 个岗位`,
    `邮件 ${toInt(scope.mails)} 封`,
    `复盘 ${toInt(scope.debriefs)} 份`
  ].join(' · ');

  dom.resetDemoButton.disabled = !demo;
  dom.resetNote.textContent = demo
    ? '只重置 demo 数据，不触碰 user 数据。'
    : 'user 模式不能重置；请切换到 demo 后操作。';
}

function renderFilterOptions(snapshot) {
  const channels = Array.isArray(snapshot.channels) ? snapshot.channels : [];
  clear(dom.filterChannel);
  dom.filterChannel.append(new Option('全部渠道', 'all'));
  channels.forEach((channel) => {
    dom.filterChannel.append(new Option(channelLabel(channel), String(channel)));
  });
  const hasChannel = state.channel === 'all' || channels.map(String).includes(String(state.channel));
  if (!hasChannel) {
    dom.filterChannel.append(new Option(channelLabel(state.channel), state.channel));
  }
  dom.filterChannel.value = state.channel;

  const states = Array.isArray(snapshot.states) ? snapshot.states : [];
  clear(dom.filterState);
  dom.filterState.append(new Option('全部状态', 'all'));
  states.forEach((item) => {
    dom.filterState.append(new Option(String(item), String(item)));
  });
  if (state.jobState !== 'all' && !states.map(String).includes(String(state.jobState))) {
    state.jobState = 'all';
  }
  dom.filterState.value = state.jobState;
  dom.filterPeriod.value = state.period;
}

const PIPELINE_STATUS_LABELS = {
  ready: '本地可用',
  local: '本地可用',
  connected: '已接入回报',
  waiting: '待接入'
};

const PIPELINE_STAGE_LABELS = { send: '发送', monitor: '监控' };
const PIPELINE_ENTRY_LABELS = { jobs: '岗位池', queue: '审批队列', mail: 'HR 回复', workbench: '工作台' };
const PIPELINE_EVENT_LABELS = {
  started: '开始',
  succeeded: '成功',
  failed: '失败',
  skipped: '跳过'
};

function renderPipeline(pipeline) {
  if (!dom.pipeline) return;
  clear(dom.pipeline);
  const stages = pipeline && Array.isArray(pipeline.stages) ? pipeline.stages : [];
  stages.forEach((stage, index) => {
    const status = String(stage.status || 'ready');
    const statusLabel = PIPELINE_STATUS_LABELS[status] || status;
    const count = toInt(stage.count);
    const node = el('button', {
      className: `pipeline-node owner-${stage.owner || 'local'} status-${status}`,
      attrs: {
        type: 'button',
        'aria-label': `${stage.title}，${count} ${stage.unit || ''}，${statusLabel}；打开${PIPELINE_ENTRY_LABELS[stage.entry] || stage.entry}面板`
      }
    }, [
      el('span', { className: 'pipeline-top' }, [
        el('span', { className: 'pipeline-index', text: String(index + 1).padStart(2, '0') }),
        el('span', { className: 'pipeline-owner', text: stage.owner_label || '' })
      ]),
      el('span', { className: 'pipeline-name', text: stage.title || '' }),
      el('span', { className: 'pipeline-desc', text: stage.description || '' }),
      el('span', { className: 'pipeline-count' }, [
        el('strong', { text: String(count) }),
        el('span', { text: stage.unit || '' })
      ]),
      el('span', { className: `pipeline-status${stage.external ? ' is-external' : ''}`, text: statusLabel })
    ]);
    node.addEventListener('click', () => {
      showView(stage.entry || 'workbench');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    dom.pipeline.append(node);
  });

  if (dom.pipelineConnection) {
    const connected = Boolean(pipeline && pipeline.external_connected);
    dom.pipelineConnection.className = `badge badge-${connected ? 'good' : 'neutral'}`;
    dom.pipelineConnection.textContent = connected ? '外部 Agent 已回报' : '外部 Agent 待接入';
  }

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
          el('span', { className: `badge badge-${row.status === 'failed' ? 'bad' : 'neutral'}`, text: `${stage} · ${status}` }),
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
        'aria-label': `${stateName}，${count} 个岗位；可流转至 ${outgoing.length ? outgoing.join('、') : '无，终态'}`
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
      dom.filterState.value = state.jobState;
      loadState();
    });
    dom.belt.append(node);
  });

  if (state.jobState === 'all') {
    const scope = snapshot.scope || {};
    dom.beltFocus.textContent = `当前焦点：全部状态 · 显示 ${toInt(scope.jobs)} / 共 ${toInt(scope.all_jobs)} 个岗位`;
  } else {
    const count = toInt(counts[state.jobState]);
    const outgoing = Array.isArray(transitions[state.jobState]) ? transitions[state.jobState] : [];
    dom.beltFocus.textContent = `当前焦点：${state.jobState} · ${count} 个岗位 · 可流转至：${outgoing.length ? outgoing.join('、') : '终态，无后续流转'}`;
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

function hardFilterNode(job) {
  const raw = job.hard_filter;
  const status = raw && typeof raw === 'object' ? String(raw.status || 'unknown') : String(raw || 'unknown');
  let node;
  if (status === 'pass') node = badge('通过', 'good', '✓');
  else if (status === 'reject') node = badge('拒绝', 'bad', '×');
  else node = badge('未知', 'neutral', '?');
  const reasons = raw && typeof raw === 'object' && Array.isArray(raw.reasons) ? raw.reasons : [];
  if (reasons.length) node.setAttribute('title', `原因：${reasons.join('；')}`);
  return node;
}

function approvalNode(value) {
  if (value === 'approved') return badge('已确认可人工投递', 'good', '✓');
  if (value === 'pending') return badge('待确认', 'warn', '!');
  if (value) return badge(String(value), 'neutral', '·');
  return el('span', { className: 'muted', text: '未入队' });
}

function renderJobs(snapshot) {
  const jobs = Array.isArray(snapshot.jobs) ? snapshot.jobs : [];
  const transitions = snapshot.transitions || {};
  dom.jobsCount.textContent = `显示 ${jobs.length} 条`;
  if (dom.jobsEmptyHint) dom.jobsEmptyHint.hidden = jobs.length > 0;

  const visibleIds = new Set(jobs.map((job) => String(job.id)));
  state.jobsSelection.forEach((id) => {
    if (!visibleIds.has(id)) state.jobsSelection.delete(id);
  });

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
    if (warnings.length) warningCell.setAttribute('title', warnings.join('；'));
    const riskNode = riskBadgeNode(job.risk);

    const actions = el('div', { className: 'row-actions' });
    const scoreValue = typeof job.score === 'number' ? job.score : null;
    const queued = job.approval !== null && job.approval !== undefined;
    const lowScore = scoreValue === null || scoreValue < 4.0;
    const enqueueButton = el('button', {
      className: 'button button-small button-quiet',
      text: queued ? '已在审批队列' : lowScore ? '手动加入审批队列' : '加入审批队列',
      attrs: { type: 'button' }
    });
    enqueueButton.disabled = queued;
    if (queued) {
      enqueueButton.title = '该岗位已在审批队列中';
      enqueueButton.setAttribute('aria-label', '已在审批队列（不可重复加入）');
    } else if (lowScore) {
      enqueueButton.title = '低于 4.0 评分门或未评分；点击后手动加入待确认队列';
      enqueueButton.setAttribute('aria-label', '手动加入审批队列（评分不足，需你自行判断）');
    } else {
      enqueueButton.title = '只加入待确认队列，不投递';
      enqueueButton.setAttribute('aria-label', '加入审批队列（只加入待确认队列，不投递）');
    }
    enqueueButton.addEventListener('click', () => {
      enqueueJob(job, enqueueButton, lowScore);
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
        transitionJob(job, target, select);
      });
      actions.append(select);
    } else {
      actions.append(el('span', { className: 'terminal-note', text: '终态，无后续流转' }));
    }

    return [
      checkbox,
      el('span', { text: String(job.company || '未填写公司') }),
      el('span', { text: String(job.title || '未填写岗位') }),
      String(job.city || '—'),
      String(job.salary_label || '未填写'),
      channelLabel(job.source_channel),
      formatScore(job.score),
      hardFilterNode(job),
      riskNode,
      String(job.state || '未知'),
      approvalNode(job.approval),
      warningCell,
      actions
    ];
  });

  renderTable(dom.jobsTable, {
    caption: '表：岗位清单与允许的下一步',
    columns: ['选择', '公司', '岗位', '城市', '薪资', '渠道', '评分', '硬过滤', '风险', '状态', '审批状态', '警告数', '动作'],
    rows,
    emptyText: '当前筛选下没有岗位。可以调整筛选，或在下方粘贴 JD / 导入静态 JSON。',
    className: 'jobs-table'
  });
  syncJobsSelection(jobs);
}

function syncJobsSelection(jobs) {
  const total = jobs.length;
  const selected = jobs.filter((job) => state.jobsSelection.has(String(job.id))).length;
  if (dom.jobsSelectionCount) dom.jobsSelectionCount.textContent = `已选 ${selected} 条`;
  if (dom.jobsSelectAll) {
    dom.jobsSelectAll.checked = total > 0 && selected === total;
    dom.jobsSelectAll.indeterminate = selected > 0 && selected < total;
    dom.jobsSelectAll.disabled = total === 0;
  }
  if (dom.jobsBulkEnqueue) {
    dom.jobsBulkEnqueue.disabled = selected === 0;
    dom.jobsBulkEnqueue.textContent = selected > 1 ? `加入审批队列（${selected}）` : '加入审批队列';
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

function renderProfileMeter(completeness) {
  if (!dom.profileMeter) return;
  const data = completeness && typeof completeness === 'object' ? completeness : {};
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
  const bar = el('div', { className: 'profile-meter-bar', attrs: { role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(percent) } });
  const fill = el('span');
  fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  bar.append(fill);
  dom.profileMeter.append(bar);
  const missing = Array.isArray(data.missing) ? data.missing : [];
  dom.profileMeter.append(el('p', {
    className: 'profile-meter-text',
    text: state.profileDirty
      ? `当前显示已保存资料的完整度 ${percent}%；页面有未保存修改，保存后更新。`
      : missing.length
        ? `完整度 ${percent}% · 还缺：${missing.join('、')}`
        : `完整度 ${percent}% · 资料齐全，可用于生成草稿。`
  }));
  if (sections.length) {
    const chips = el('div', { className: 'chip-row' });
    sections.forEach((section) => {
      chips.append(el('span', {
        className: `chip profile-chip${section.done ? ' is-done' : ''}`,
        text: `${section.done ? '✓' : '○'} ${section.label}`
      }));
    });
    dom.profileMeter.append(chips);
  }
}

function renderProfile(profile) {
  if (!dom.profileForm || !profile || typeof profile !== 'object') return;
  if (!state.profileDirty) populateProfileForm(profile);
  const completeness = profile.completeness || {};
  renderProfileMeter(completeness);
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
    dom.profileImport.disabled = state.mode !== 'user';
    dom.profileImport.title = state.mode === 'user' ? '读取本机 workspace/resume.md 并填入可识别字段' : '演示模式不读取真实简历；请切换到「我的 user」';
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
  populateProfileForm(data.profile);
  renderProfileMeter(data.profile.completeness);
  showInline(dom.profileResult, data.message || '个人资料已保存到本机。', 'ok');
  setStatus(data.message || '个人资料已保存到本机。', 'ok');
  await loadState();
}

async function importProfileFromCv() {
  if (state.mode !== 'user') {
    setStatus('演示模式不读取真实简历；请切换到「我的 user」。', 'warn');
    return;
  }
  if (state.profileDirty && !window.confirm('导入会覆盖当前未保存的修改，继续吗？')) return;
  const data = await runAction(dom.profileImport, () => postAction('import-profile-cv'));
  if (!data) return;
  populateProfileForm(data.profile);
  state.profileDirty = true;
  renderProfile(data.profile);
  showInline(dom.profileResult, data.message || '已填入建议字段，请核对后保存。', 'ok');
  setStatus(data.message || '已填入建议字段，请核对后保存。', 'ok');
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
    container.append(el('p', { className: 'hint', text: '尚无任务回报。岗位自动化就绪后可在此启动受控任务。' }));
    return;
  }
  if (!current && previous) {
    container.append(el('p', { className: 'hint', text: '当前没有运行中的任务；以下为最近一次回报。' }));
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
      text: row.stop_requested ? '停止请求已发送' : '请求停止任务',
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

function collectFormKey() {
  const mode = collectMode();
  if (!collectNeedsSearch(mode)) return mode;
  return [
    mode,
    dom.collectKeywords ? dom.collectKeywords.value.trim() : '',
    dom.collectCities ? dom.collectCities.value.trim() : '',
    dom.collectPages ? dom.collectPages.value.trim() : '',
    dom.collectPace ? dom.collectPace.value : 'cautious',
    dom.collectAutoScore && dom.collectAutoScore.checked ? '1' : '0'
  ].join('|');
}

function buildOfferPilotOptions(silent = false) {
  const keywords = splitTextList(dom.collectKeywords && dom.collectKeywords.value);
  const cities = splitTextList(dom.collectCities && dom.collectCities.value);
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
    platform: 'boss',
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
      text += ` 将在 BOSS 直聘搜索「${options.keywords.join('、')}」，城市「${options.cities.join('、')}」，每个关键词最多 ${options.max_pages} 页。`;
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
      text: state.mode === 'demo'
        ? '演示模式只读，不会启动真实采集；切换到「我的 user」后可检查本机环境。'
        : '修改条件后需要重新检查。'
    }));
    return;
  }
  const checks = Array.isArray(preflight.checks) ? preflight.checks : [];
  const mode = collectMode();
  const summary = el('p', {
    className: `notice ${preflight.ok ? '' : 'notice-accent'}`.trim(),
    text: preflight.ok ? '检查通过，可以启动。' : '检查未通过；请先处理下面的阻塞项。'
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
  const mode = collectMode();
  const needsSearch = collectNeedsSearch(mode);
  document.querySelectorAll('[data-collect-search]').forEach((node) => {
    node.hidden = !needsSearch;
  });
  if (dom.offerpilotStart) {
    dom.offerpilotStart.textContent = mode === 'monitor' ? '开始监控' : mode === 'full' ? '开始完整流程' : '开始采集';
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
  if (state.mode !== 'user' || !data.preferences || typeof data.preferences !== 'object') return;
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
  state.offerpilotCanStart = connected && data.mode !== 'demo'
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
    dom.offerpilotConnection.textContent = connected
      ? (state.offerpilotCanStart ? '已就绪' : '演示只读')
      : '未就绪';
    dom.offerpilotConnection.className = `badge ${connected ? 'badge-good' : 'badge-warn'}`;
  }
  if (dom.offerpilotState) {
    clear(dom.offerpilotState);
    dom.offerpilotState.append(offerpilotMetaRow('地址', el('span', { className: 'cell-mono', text: String(data.base_url || '—') })));
    dom.offerpilotState.append(offerpilotMetaRow('连接', state.offerpilotCanStart ? '内嵌后端可用' : connected ? '演示模式，不启动真实采集' : '依赖或数据未就绪'));
    if (connected && data.ai) {
      dom.offerpilotState.append(offerpilotMetaRow('AI 配置', data.ai.configured ? '已配置（状态不回传密钥）' : '未配置（仍可无 AI 采集/监控）'));
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
      if (preferences.score_threshold !== undefined && preferences.score_threshold !== null) parts.push(`评分门：${compactValue(preferences.score_threshold)}`);
      dom.offerpilotState.append(offerpilotMetaRow('偏好快照', parts.length ? parts.join('；') : '已连接，暂无偏好字段'));
    }
  }
  if (dom.offerpilotError) {
    const error = connected ? '' : String(data.error || '岗位自动化组件依赖或数据未就绪；工作台仍可正常使用。');
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
  syncCollectModeUI();
  renderOfferPilotTask(data.task, data.last_task);
  syncOfferPilotStartState();
  if (!data.task) maybeAutoImportCollected(data.last_task);
  if (!connected) {
    state.offerpilotJobsLoaded = false;
    if (dom.offerpilotJobsCount) dom.offerpilotJobsCount.textContent = '未连接';
    if (dom.offerpilotJobsTable) {
      clear(dom.offerpilotJobsTable);
      dom.offerpilotJobsTable.append(el('p', { className: 'hint', text: '岗位自动化就绪后，可在此读取采集结果。' }));
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

function syncOfferPilotStartState() {
  if (!dom.offerpilotStart) return;
  const preflightReady = Boolean(state.offerpilotPreflight && state.offerpilotPreflight.ok === true);
  const resumeMissing = collectResumeMissing();
  dom.offerpilotStart.disabled = resumeMissing
    || !state.offerpilotCanStart
    || state.offerpilotTaskActive
    || !dom.offerpilotRisk.checked
    || !dom.offerpilotConfirm.checked
    || !preflightReady;
  dom.offerpilotStart.title = state.offerpilotTaskActive
    ? '已有任务正在运行；请先停止或等待结束'
    : resumeMissing ? '请先上传评分简历'
    : preflightReady ? '' : '先点击「检查环境」并处理阻塞项';
}

function renderOfferPilotJobs() {
  if (!dom.offerpilotJobsTable) return;
  const jobs = state.offerpilotJobs;
  renderTable(dom.offerpilotJobsTable, {
    caption: '表：本机采集结果（只读快照）',
    columns: ['岗位', '公司', '城市', '薪资', '评分', '状态'],
    rows: jobs.map((job) => [
      String(job.title || '—'),
      String(job.company || '—'),
      String(job.city || '—'),
      String(job.salary || '—'),
      job.score === undefined || job.score === null || Number(job.score) <= 0 ? '—' : String(job.score),
      OFFERPILOT_JOB_STATUS_LABELS[String(job.status || '')] || String(job.status || '—')
    ]),
    emptyText: state.offerpilotConnected ? '当前没有采集结果。启动一次采集后，这里会显示岗位。' : '岗位自动化未就绪。'
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
    state.offerpilotJobs = jobs;
    state.offerpilotJobsLoaded = true;
    const validIds = new Set(jobs.map((job) => String(job.id || '')).filter(Boolean));
    state.offerpilotSelection.forEach((id) => {
      if (!validIds.has(id)) state.offerpilotSelection.delete(id);
    });
    if (dom.offerpilotJobsCount) {
      dom.offerpilotJobsCount.textContent = `只读 ${jobs.length} 条`;
    }
    renderOfferPilotJobs();
    if (options.announce) setStatus(`已读取 ${jobs.length} 条采集结果；导入前不会写入岗位池。`, 'ok');
  } catch (error) {
    state.offerpilotJobsLoaded = false;
    state.offerpilotJobs = [];
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
    setStatus('当前是演示模式或内嵌后端未就绪；切换到用户数据后再检查真实采集环境。', 'error');
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
    if (data.ok) setStatus('环境检查通过，可以启动。', 'ok');
    else setStatus(`环境检查未通过：${(data.messages && data.messages[0]) || '请查看检查项'}`, 'warn');
  } catch (error) {
    const failure = { ok: false, checks: [], messages: [friendlyError(error)] };
    state.offerpilotPreflight = failure;
    state.offerpilotPreflightKey = key;
    renderCollectChecks(failure);
    setStatus(`环境检查失败：${friendlyError(error)}`, 'error');
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
          ? (state.offerpilotCanStart ? '岗位自动化已就绪。' : '演示模式只读；切换到用户数据后可启动真实任务。')
          : `岗位自动化不可用：${(data.state && data.state.error) || '依赖或数据未就绪'}`,
        data.state && data.state.ok ? 'ok' : 'warn'
      );
    }
    if (state.offerpilotConnected) await loadOfferPilotJobs(options);
    if (state.snapshot) await loadState();
    maybeRunOfferPilotPreflight();
  } catch (error) {
    renderOfferPilot({ connected: false, error: friendlyError(error) });
    if (options.announce) setStatus(`检测岗位自动化失败：${friendlyError(error)}`, 'error');
  } finally {
    if (dom.offerpilotRefresh) dom.offerpilotRefresh.disabled = false;
  }
}

async function startOfferPilotTask(button) {
  const mode = collectMode();
  if (!['collect', 'monitor', 'full'].includes(mode)) {
    setStatus('岗位自动化任务模式无效。', 'error');
    return;
  }
  if (!state.offerpilotCanStart) {
    setStatus('当前是演示模式或内嵌后端未就绪；切换到用户数据后再启动真实任务。', 'error');
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
    setStatus('启动前必须同时勾选风险确认与启动确认。', 'error');
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
  setStatus(data.message || '岗位自动化任务已受控提交。', 'ok');
  showInline(dom.offerpilotResult, data.message || '岗位自动化任务已受控提交。', 'ok');
  dom.offerpilotRisk.checked = false;
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

async function maybeAutoImportCollected(task) {
  if (!task || state.mode !== 'user' || !state.offerpilotCanStart) return;
  if (state.offerpilotTaskActive || state.offerpilotAutoImporting) return;
  if (!['completed', 'stopped'].includes(String(task.status || ''))) return;
  const ids = task.progress && Array.isArray(task.progress.collected_job_ids)
    ? task.progress.collected_job_ids.map(String).filter(Boolean)
    : [];
  if (!ids.length || importedTaskIds().has(String(task.id))) return;
  state.offerpilotAutoImporting = true;
  markTaskImported(task.id, true);
  try {
    const data = await postAction('offerpilot-import', { ids, data_mode: state.mode });
    if (data && data.ok) {
      const message = `采集完成，${data.message || '已自动导入岗位池'}`;
      const collectView = document.getElementById('view-collect');
      const onCollect = collectView && !collectView.hidden;
      showInline(dom.offerpilotResult, message, 'ok');
      await loadState();
      renderOfferPilotJobs();
      if (onCollect) {
        // 采集 → 自动导入 → 挑选岗位 是同一条主线，完成后直接落到岗位表。
        showView('jobs');
        setStatus(`${message} 已跳到岗位池，挑好后加入审批队列。`, 'ok');
      } else {
        setStatus(message, 'ok');
      }
    }
  } catch (error) {
    // Let the next refresh retry if the import failed.
    markTaskImported(task.id, false);
    showInline(dom.offerpilotResult, `自动导入失败：${friendlyError(error)}。可在下方点击「导入全部到岗位池」重试。`, 'error');
  } finally {
    state.offerpilotAutoImporting = false;
  }
}

async function uploadOfferPilotResume(file) {
  if (!file) return;
  const name = String(file.name || '');
  if (!/\.(md|docx|pdf)$/i.test(name)) {
    setStatus('简历只支持 .md、.docx 或 .pdf 格式。', 'error');
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
    setStatus('读取简历文件失败。', 'error');
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
  setStatus('已向 OfferPilot 发送停止请求。', 'ok');
  showInline(dom.offerpilotResult, '已向 OfferPilot 发送停止请求；以其任务状态回报为准。', 'ok');
  await refreshOfferPilot();
}

async function enqueueJob(job, button, manual = false) {
  return enqueueJobs([job], button, manual);
}

async function enqueueJobs(jobs, button, manual = false) {
  const ids = jobs.map((job) => String(job.id)).filter(Boolean);
  if (!ids.length) return;
  const payload = { ids };
  if (manual) payload.allow_low_score = true;
  const data = await runAction(button, () => postAction('enqueue', payload));
  if (!data) return;
  ids.forEach((id) => state.jobsSelection.delete(id));
  let message = data.message || '已加入待确认队列。';
  if (Array.isArray(data.dropped) && data.dropped.length) {
    message += ` 未入队 ${data.dropped.length} 条（评分不足或缺失）。`;
  }
  if (Array.isArray(data.duplicate) && data.duplicate.length) {
    message += ` 重复 ${data.duplicate.length} 条。`;
  }
  const accepted = (Array.isArray(data.accepted) && data.accepted.length > 0)
    || (Array.isArray(data.manual) && data.manual.length > 0);
  setStatus(message, accepted ? 'ok' : 'warn');
  showInline(dom.jobsActionResult, message, accepted ? 'ok' : 'warn');
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
    return [
      checkbox,
      String(row.company || '—'),
      String(row.title || '—'),
      formatScore(row.score),
      channelLabel(row.Source_Channel),
      formatDateTime(row.created_at),
      row.high_confidence ? badge('高置信', 'good', '✓') : el('span', { className: 'muted', text: '普通' })
    ];
  });
  renderTable(dom.queuePendingTable, {
    caption: '表：待确认队列',
    columns: ['选择', '公司', '岗位', '评分', '渠道', '创建时间', '置信'],
    rows: pendingRows,
    emptyText: '待确认队列为空。可以在「岗位」表把评分达到 4.0 的岗位加入队列。',
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
    return [
      checkbox,
      String(row.company || '—'),
      String(row.title || '—'),
      formatScore(row.score),
      channelLabel(row.Source_Channel),
      greetingStatusBadge(row.greeting),
      deliveryStatusBadge(row.delivery),
      planBadge(row.plan),
      badge('approved · 可人工投递', 'good', '✓')
    ];
  });
  renderTable(dom.queueApprovedTable, {
    caption: '表：已确认可人工投递',
    columns: ['选择', '公司', '岗位', '评分', '渠道', '招呼语', '投递', '今日安排', '状态'],
    rows: approvedRows,
    emptyText: '还没有已确认的岗位。approved 只表示可人工投递，不代表已投递。',
    className: 'data-table-wide'
  });
  renderQueueGreetings(approved);
  renderDeliveryResults(snapshot);

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
    if (greeting.selection) meta.push(`来源：${greeting.selection}`);
    if (Array.isArray(greeting.style_issues) && greeting.style_issues.length) {
      meta.push(`风格提示：${greeting.style_issues.join('；')}`);
    }
    if (meta.length) card.append(el('p', { className: 'queue-greeting-meta', text: meta.join(' · ') }));
    const evidence = greeting.evidence_check;
    if (evidence && Array.isArray(evidence.unsupported_claims) && evidence.unsupported_claims.length) {
      const list = el('ul', { className: 'queue-greeting-evidence' });
      evidence.unsupported_claims.forEach((claim) => {
        list.append(el('li', { text: `「${claim.context}」中的数字 ${claim.value} 在个人资料中找不到依据，请核对后再发送` }));
      });
      card.append(el('p', { className: 'queue-greeting-meta', text: '无证据数字（仅提示，不会自动改写）：' }));
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
      ? '已有岗位自动化任务正在运行；请先停止或等待结束'
      : selected > 10
        ? '一次最多 10 条'
        : '只生成招呼语，不发送';
  }
  if (dom.queueSendGreetings) {
    const selectedRows = approved.filter((row) => state.queueApprovedSelection.has(String(row.id)));
    const greetingReady = selectedRows.length > 0
      && selectedRows.every((row) => row.greeting && row.greeting.ready);
    dom.queueSendGreetings.disabled = !greetingReady
      || selected > 10
      || Boolean(state.offerpilotTaskActive);
    dom.queueSendGreetings.title = state.offerpilotTaskActive
      ? '已有岗位自动化任务正在运行；请先停止或等待结束'
      : !greetingReady
        ? '请先为所选岗位生成招呼语'
        : '核对招呼语后发送';
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
  state.queueApprovedSelection.clear();
  setStatus(data.message || '已开始生成招呼语；只生成，不发送。', 'ok');
  await refreshOfferPilot();
}

const DELIVERY_STATUS_META = {
  starting: ['准备中', 'warn', '…'],
  sending: ['发送中', 'warn', '…'],
  sent: ['已发送', 'good', '✓'],
  failed: ['失败', 'bad', '!'],
  deferred: ['延后', 'warn', '…'],
  blocked: ['已阻止', 'bad', '!']
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

function openDeliveryPanel() {
  const rows = selectedApprovedRows();
  if (!rows.length) {
    setStatus('请先勾选已确认岗位。', 'warn');
    return;
  }
  if (!rows.every((row) => row.greeting && row.greeting.ready)) {
    setStatus('所选岗位需要先生成招呼语。', 'warn');
    return;
  }
  state.queueDeliveryIds = rows.map((row) => String(row.id));
  const count = rows.length;
  dom.queueDeliverySummary.textContent = count > 1
    ? `本批 ${count} 条；预计 ${count - 1} 次间隔，约 ${count - 1}–${(count - 1) * 3} 分钟。发送前请核对下方文本。`
    : '本批 1 条；确认后立即开始。发送前请核对下方文本。';
  clear(dom.queueDeliveryList);
  rows.forEach((row) => {
    const item = el('li', { className: 'queue-delivery-item' });
    item.append(el('strong', { text: `${row.company || '—'}｜${row.title || '—'}` }));
    item.append(el('p', { text: String((row.greeting || {}).greeting || '') }));
    dom.queueDeliveryList.append(item);
  });
  dom.queueDeliveryConfirm.value = '';
  dom.queueDeliveryConfirm.placeholder = deliveryConfirmPhrase(count);
  dom.queueDeliveryRisk.checked = false;
  dom.queueDeliveryPanel.hidden = false;
  updateDeliveryStartState();
  dom.queueDeliveryConfirm.focus();
}

function updateDeliveryStartState() {
  if (!dom.queueDeliveryStart) return;
  const count = state.queueDeliveryIds.length;
  const phraseOk = dom.queueDeliveryConfirm.value === deliveryConfirmPhrase(count);
  dom.queueDeliveryStart.disabled = !(
    count > 0
    && phraseOk
    && dom.queueDeliveryRisk.checked
    && !state.offerpilotTaskActive
  );
}

async function startQueueDelivery(button) {
  const ids = [...state.queueDeliveryIds];
  if (!ids.length) return;
  const data = await runAction(button, () => postAction('offerpilot-deliver', {
    ids,
    confirm: deliveryConfirmPhrase(ids.length),
    risk_acknowledged: true
  }));
  if (!data) return;
  dom.queueDeliveryPanel.hidden = true;
  state.queueDeliveryIds = [];
  state.queueApprovedSelection.clear();
  setStatus(data.message || '已提交发送；受窗口与日限约束。', 'ok');
  await refreshOfferPilot();
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
    partial: '部分完成',
    failed: '发送未完成'
  };
  head.append(el('strong', { text: `${titles[status] || status} · 批次 ${batch.batch_id || ''}` }));
  head.append(badge(`${batch.sent || 0} 成功`, 'good', '✓'));
  if (batch.failed) head.append(badge(`${batch.failed} 失败`, 'bad', '!'));
  if (batch.deferred) head.append(badge(`${batch.deferred} 延后`, 'warn', '…'));
  if (batch.blocked) head.append(badge(`${batch.blocked} 已阻止`, 'bad', '!'));
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
    ['置信度', formatPercent(info.confidence)],
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
    container.append(el('p', { className: 'card-subtitle', text: '输入异常（作为数据引用，不执行）' }));
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
const CHAT_WEB_SEED = {
  id: 'lib-web-seed',
  kind: 'jingyan',
  title: '示例联网面经',
  body: '联网示例公司的虚构场景：先做注册再做支付，面经只用来估计可能问什么。',
  company: '联网示例公司',
  role: '示例联网岗位',
  source: 'web',
  source_label: '来自联网',
  jingyan_is_not_official: true,
  source_urls: ['https://example.invalid/interview-note'],
  created_at: '2026-11-17T00:00:00.000Z',
  updated_at: '2026-11-17T00:00:00.000Z'
};
const CHAT_PEER_SEED = {
  id: 'lib-peer-seed',
  kind: 'jingyan',
  title: '同业产品面经',
  body: '其他公司产品岗位常问需求取舍和范围控制。这条只用来理解能力，不是目标公司的业务，也不是候选人做过的事。',
  company: '同业示例公司',
  role: '产品经理',
  source: 'user',
  source_label: '',
  match_tier: 'peer_same_role',
  jingyan_is_not_official: true,
  created_at: '2026-11-17T00:00:00.000Z',
  updated_at: '2026-11-17T00:00:00.000Z'
};
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
    state.interviewChat.materials = state.mode === 'demo'
      ? [normalizeChatLibraryItem(CHAT_WEB_SEED, 0), normalizeChatLibraryItem(CHAT_PEER_SEED, 1)]
      : [];
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
  if (state.mode === 'demo') {
    const ids = new Set(state.interviewChat.materials.map((item) => item.id));
    let seeded = false;
    if (!ids.has(CHAT_WEB_SEED.id)) {
      state.interviewChat.materials.unshift(normalizeChatLibraryItem(CHAT_WEB_SEED, 0));
      seeded = true;
    }
    if (!ids.has(CHAT_PEER_SEED.id)) {
      state.interviewChat.materials.push(normalizeChatLibraryItem(CHAT_PEER_SEED, 1));
      seeded = true;
    }
    if (seeded) persistChatLibrary();
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
      dom.chatRoleLine.textContent = [company, title].filter(Boolean).join(' · ');
    } else {
      dom.chatRoleLine.hidden = true;
      dom.chatRoleLine.textContent = '';
    }
  }
}

function updateChatProgress() {
  if (!dom.chatProgress) return;
  const minutes = remainingMinutesFromSession(state.interviewChat.session);
  dom.chatProgress.textContent = `剩余 ${minutes} 分钟`;
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
    dom.chatAnswer.disabled = lockInput;
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
    const label = [job.company, job.title].filter(Boolean).join(' · ') || String(job.id || '岗位');
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
    setStatus('这一问没有说完：外部 AI 中断或超时。已出现的半句仍保留，标明未完成，不计入本轮进度。可以重试。你已提交的回答还在。', 'warn');
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
  setStatus('本场已结束。准备度复盘在「面试复盘」。输入已不可再发送。', 'ok');
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
      text: `${formatDateTime(card.created_at)} · ${String(card.source || '网页输入')}`
    }));
  } else {
    node.append(el('p', { className: 'result-title', text: '复盘卡片' }));
    node.append(el('p', {
      className: 'card-meta',
      text: `${formatDateTime(card.created_at)} · ${String(card.source || '网页输入')}`
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
      text: '输入异常（作为数据引用，不执行）'
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

  const variants = Array.isArray(snapshot.variants) ? snapshot.variants : [];
  renderTable(dom.variantList, {
    caption: '表：已保存的经历变体',
    columns: ['项目', '保存时间', '经历原文', 'SHA-256'],
    rows: variants.map((variant) => [
      String(variant.project || '—'),
      formatDateTime(variant.created_at),
      el('div', { className: 'cell-text', text: String(variant.text || '') }),
      el('span', {
        className: 'cell-mono',
        text: String(variant.sha256 || '').slice(0, 16) || '—'
      })
    ]),
    emptyText: '还没有保存经历变体。',
    className: 'data-table-wide'
  });
}

/* Render: data and reports */

function renderActivity(container, activity) {
  if (!container) return;
  clear(container);
  const rows = Array.isArray(activity) ? activity : [];
  if (!rows.length) {
    container.append(el('p', { className: 'empty-state', text: '暂无操作记录。' }));
    return;
  }
  const list = el('ul', { className: 'activity-list' });
  rows.forEach((row) => {
    const item = el('li', { className: 'activity-item' });
    item.append(el('span', { className: 'activity-time', text: formatDateTime(row.at) }));
    item.append(el('span', {
      className: 'activity-title',
      text: String(row.title || row.action || '操作')
    }));
    const statusBadge = row.ok === false
      ? badge('拒绝', 'bad', '×')
      : badge('完成', 'good', '✓');
    statusBadge.classList.add('activity-state');
    item.append(statusBadge);
    if (row.detail) {
      item.append(el('span', { className: 'activity-detail', text: String(row.detail) }));
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
    emptyText: '未返回 boundaries。',
    className: 'data-table-wide'
  });
}

function renderConfig(snapshot) {
  const config = snapshot.config && typeof snapshot.config === 'object' ? snapshot.config : {};
  const score = config.score && typeof config.score === 'object' ? config.score : {};
  const listText = (value) => (Array.isArray(value) && value.length ? value.join('、') : '—');
  const rows = [
    ['目标城市', listText(config.target_cities)],
    ['排除词', listText(config.excluded_terms)],
    ['岗位关键词', listText(config.title_keywords)],
    ['薪资下限', config.salary_min_threshold === undefined || config.salary_min_threshold === null
      ? '—'
      : `${toInt(config.salary_min_threshold)} 元`],
    ['审批阈值', score.approval_min === undefined
      ? '—'
      : `≥ ${String(score.approval_min)} 入队；≥ ${String(score.high_threshold)} 高置信`],
    ['弱点标签', listText(config.weakness_tags)],
    ['简历技能命中', listText(snapshot.cv_skills)]
  ];
  renderDefinitionList(dom.configSummary, rows);
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
    emptyText: '暂无下载文件。生成准备清单、ICS、题单或报告后会出现在这里。',
    className: 'data-table-wide'
  });
  renderBoundaries(snapshot);
  renderConfig(snapshot);
  const demo = snapshot.mode === 'demo';
  dom.resetDemoButton.disabled = !demo;
  dom.resetNote.textContent = demo
    ? '只重置 demo 数据，不触碰 user 数据。'
    : 'user 模式不能重置；请切换到 demo 后操作。';
}

/* Top-level render */

function renderAll(snapshot) {
  renderMeta(snapshot);
  renderFilterOptions(snapshot);
  renderPipeline(snapshot.pipeline);
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
  renderActivity(dom.activityOverview, snapshot.activity);
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
    ['提取字符数', String(toInt(info.extracted_text_chars))],
    ['关键词全部命中', info.all_keywords_found === true
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
    container.append(el('p', { className: 'card-meta', text: '未提供关键词，未验证命中。' }));
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
      text: 'needs_manual_check 不是通过；请人工核查文字层、分栏、表格与 OCR 场景。'
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

async function resetDemo() {
  if (state.mode !== 'demo') {
    setStatus('只有 demo 模式可以重置演示数据。', 'error');
    return;
  }
  if (!window.confirm('确定恢复 demo 演示数据吗？user 数据不会改变。')) return;
  const data = await runAction(dom.resetDemoButton, () => postJson('/api/reset-demo', { mode: 'demo' }));
  if (!data) return;
  setStatus(data.message || '演示数据已恢复；用户数据未改变。', data.ok ? 'ok' : 'warn');
  showOpsResult({
    title: '重置演示数据',
    summary: data.message || '',
    kind: data.ok ? 'ok' : 'warn'
  });
  state.queueSelection.clear();
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

  dom.modeButtons.forEach((button) => {
    button.addEventListener('click', () => switchMode(button.dataset.mode));
  });

  dom.themeButtons.forEach((button) => {
    button.addEventListener('click', () => applyTheme(button.dataset.themeChoice));
  });

  dom.filterPeriod.addEventListener('change', handleFilterChange);
  dom.filterChannel.addEventListener('change', handleFilterChange);
  dom.filterState.addEventListener('change', handleFilterChange);
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
    dom.profileImport.addEventListener('click', importProfileFromCv);
  }
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
  [dom.collectKeywords, dom.collectCities, dom.collectPages, dom.collectPace, dom.collectAutoScore].forEach((input) => {
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
    dom.queueSendGreetings.addEventListener('click', openDeliveryPanel);
  }
  if (dom.queueDeliveryCancel) {
    dom.queueDeliveryCancel.addEventListener('click', () => {
      dom.queueDeliveryPanel.hidden = true;
      state.queueDeliveryIds = [];
    });
  }
  if (dom.queueDeliveryConfirm) {
    dom.queueDeliveryConfirm.addEventListener('input', updateDeliveryStartState);
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
      setStatus('请先勾选至少一条待确认岗位。', 'error');
      return;
    }
    const data = await runAction(dom.queueConfirmButton, () => postAction('confirm', { ids }));
    if (!data) return;
    const ok = announceActionResult(data, '已通过；发送前还会再让你复核一次。');
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
      const low = selected.some((job) => typeof job.score !== 'number' || job.score < 4.0);
      enqueueJobs(selected, dom.jobsBulkEnqueue, low);
    });
  }

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
    if (dom.jdScore.value.trim() !== '') {
      const score = Number(dom.jdScore.value);
      if (!Number.isFinite(score) || score < 0 || score > 5) {
        setStatus('评分必须是 0–5 之间的数字。', 'error');
        return;
      }
      payload.score = score;
    }
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
    if (warnings.length) message += ` 警告：${warnings.join('；')}`;
    if (reasons.length) message += ` 硬过滤原因：${reasons.join('；')}`;
    if (data.ok === false) {
      setStatus(message, data.duplicate ? 'warn' : 'error');
      showInline(dom.jdResult, message, data.duplicate ? 'warn' : 'error');
      return;
    }
    const kind = warnings.length || reasons.length ? 'warn' : 'ok';
    setStatus(message, kind);
    showInline(dom.jdResult, message, kind);
    dom.jdText.value = '';
    dom.jdScore.value = '';
    await loadState();
  });

  dom.importForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = dom.importJson.value.trim();
    if (!text) {
      setStatus('请先粘贴静态 JSON。', 'error');
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
      setStatus('请先选择一个 PDF 文件。', 'error');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setStatus('PDF 超过 5 MB 上限，未发送。', 'error');
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
    setStatus(data.message || '检查完成；无法解析的文字层仍需人工核查。', 'ok');
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

  dom.worksheetForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const minutes = Number(dom.worksheetMinutes.value);
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 180) {
      setStatus('时长必须是 1–180 分钟的整数。', 'error');
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
      meta: `题目数：${count} · 计划时长：${minutes} 分钟 · 空题库不会编造题目`,
      text: data.worksheet || '',
      downloadNames: data.download ? [data.download] : [],
      kind
    });
    await loadState();
  });

  dom.debriefForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const transcript = dom.debriefTranscript.value.trim();
    if (!transcript) {
      setStatus('请先粘贴逐字稿。', 'error');
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
      setStatus('项目名和经历原文不能为空。', 'error');
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
    setStatus(data.message || '经历原文已保存；未修改 Master Resume。', 'ok');
    showInline(dom.variantResult, data.message || '经历原文已保存。', 'ok');
    appendVariantQualityHints(dom.variantResult, data.quality);
    dom.variantProject.value = '';
    dom.variantText.value = '';
    await loadState();
  });

  dom.runTestsButton.addEventListener('click', runTests);
  dom.webReportButton.addEventListener('click', generateWebReport);
  dom.exportButton.addEventListener('click', exportData);
  dom.resetDemoButton.addEventListener('click', resetDemo);

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
    setStatus(data.message || '只显示 dry-run payload；没有发出 HTTP 请求。', 'ok');
    dom.dryRunResult.hidden = false;
    dom.dryRunResult.textContent = JSON.stringify(data.result || data, null, 2);
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
  syncModeButtons();
  dom.filterPeriod.value = state.period;
  dom.mailDate.value = todayIso();
  showView('workbench');
  bindEvents();
  bindAmbient();
  updateQueueSelectionUI();
  loadState({ announce: true });
}

init();
