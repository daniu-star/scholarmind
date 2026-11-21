// R1-T18 · 研究工作区单页：上传 → 确认范围 → 全文诊断 → 问题与依据 → 选择目标 → 采纳修改 → 导出
// 只使用原生 DOM（utils/dom.js 的 createElement）与既有按钮/颜色变量，不引入第三方依赖。
import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { showToast, showConfirmDialog } from '../components/ConfirmDialog.js';
import { iconArrowLeft, iconRefresh, iconDownload } from '../utils/icons.js';
import {
  getCapabilities,
  listProjects,
  createProject,
  getProject,
  uploadDocument,
  createTask,
  getTask,
  getFindings,
  streamTaskEvents,
  cancelTask,
  resumeTask,
  retryTask,
  getArtifact,
  getArtifactText,
  applyProposal,
  exportArtifact,
  downloadArtifact,
  createChart,
  fetchArtifactBlob,
  getDocumentBlocks,
  newIdempotencyKey,
} from '../services/researchApi.js';
import {
  button,
  capabilityIndex,
  dimensionLabel,
  formatBytes,
  isTerminal,
  notice,
  pill,
  shortId,
} from '../components/research/shared.js';
import {
  CapabilityPanel,
  ErrorState,
  LoadingState,
  UnauthorizedState,
  capabilityLabel,
} from '../components/research/WorkspaceStates.js';
import { ProjectList } from '../components/research/ProjectList.js';
import { DocumentUpload } from '../components/research/DocumentUpload.js';
import { TaskStream } from '../components/research/TaskStream.js';
import { DiagnosisReport } from '../components/research/DiagnosisReport.js';
import { FindingCard } from '../components/research/FindingCard.js';
import { RevisionDiff } from '../components/research/RevisionDiff.js';
import { ChartPanel } from '../components/research/ChartPanel.js';

const DIMENSIONS = ['argument', 'method', 'evidence', 'expression', 'format'];
const PRESERVE = ['numbers', 'dates', 'names', 'direct_quotes', 'citations'];
const LEGACY_KEY = 'sm_writing_content';
const STATE_PREFIX = 'sm_research_state_';
const MAX_RECONNECTS = 40;

// ── 页面级状态（非响应式；所有变更通过 sync/render* 主动刷新） ──────────
const s = {
  status: 'loading', // loading | unauthorized | error | ready
  error: null,
  capabilities: [],
  capLoading: true,
  capError: null,
  capIndex: new Map(),
  projects: [],
  projectsLoading: true,
  projectsError: null,
  creating: false,
  project: null,
  projectLoadingId: null,
  documents: [],
  selectedDocumentId: null,
  documentLoadingId: null,
  uploading: false,
  uploadError: null,
  objective: '',
  dimensions: new Set(DIMENSIONS),
  mode: 'flash',
  review: { taskId: null, task: null, findings: [], loading: false, error: null },
  revision: {
    taskId: null,
    task: null,
    artifact: null,
    validation: null,
    markdown: '',
    loading: false,
    error: null,
    applyState: 'idle',
    applyError: null,
    conflict: false,
    applyResult: null,
  },
  activeTaskId: null,
  streamSeq: null,
  streamAbort: null,
  reconnectTimer: null,
  selectedFindingIds: new Set(),
  exporting: false,
  exportError: null,
  exportResult: null,
  chart: {
    values: { chartType: 'gradient_area', xColumn: '', yColumns: '', title: '', tableIndex: 0 },
    columns: [],
    tableCount: 0,
    tableVersionId: null,
    tableOptions: [],
    tableLoading: false,
    tableError: null,
    loading: false,
    error: null,
    result: null,
    blobUrl: null,
  },
  importingLegacy: false,
};

let taskStream = null;
let els = {};
let chartSignature = '';
let styleInjected = false;

// ── 样式（仅本页作用域；rw- 前缀） ──────────────────────────────────
function injectStyles() {
  if (styleInjected || document.getElementById('rw-styles')) {
    styleInjected = true;
    return;
  }
  const style = document.createElement('style');
  style.id = 'rw-styles';
  style.textContent = `
.page-research-workspace { height: calc(100vh - 53px); overflow-y: auto; padding: 18px 20px 56px; background: var(--bg-base); }
.rw-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.rw-header-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.rw-title-wrap { min-width: 0; }
.rw-title { font-size: var(--text-lg); font-weight: 600; color: var(--text-primary); margin: 0; }
.rw-subtitle-text { margin: 3px 0 0; font-size: var(--text-sm); color: var(--text-secondary); }
.rw-header-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.rw-layout { display: grid; grid-template-columns: 322px minmax(0, 1fr); gap: 16px; align-items: start; }
.rw-main[hidden], .rw-workspace[hidden], .rw-state-layer[hidden], .rw-side[hidden] { display: none !important; }
.rw-side { display: flex; flex-direction: column; gap: 14px; position: sticky; top: 0; }
.rw-main { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
@media (max-width: 1080px) { .rw-layout { grid-template-columns: minmax(0, 1fr); } .rw-side { position: static; } }

.rw-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md, 10px); overflow: hidden; }
.rw-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 14px 16px 10px; border-bottom: 1px solid var(--border-subtle, var(--border)); }
.rw-card-title { margin: 0; font-size: var(--text-base); font-weight: 600; color: var(--text-primary); }
.rw-card-sub { margin: 4px 0 0; font-size: var(--text-xs); color: var(--text-secondary); line-height: 1.5; }
.rw-card-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.rw-card-body { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 10px; }
.rw-subtitle { margin: 6px 0 0; font-size: var(--text-sm); font-weight: 600; color: var(--text-primary); }

.rw-pill { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: 999px; font-size: var(--text-xs); line-height: 1.7; border: 1px solid transparent; white-space: nowrap; }
.rw-tone-green { color: var(--accent-green); background: rgba(63,185,80,0.10); border-color: rgba(63,185,80,0.28); }
.rw-tone-amber { color: var(--accent-brand); background: rgba(245,158,11,0.10); border-color: rgba(245,158,11,0.28); }
.rw-tone-red { color: var(--accent-red); background: rgba(208,90,82,0.10); border-color: rgba(208,90,82,0.30); }
.rw-tone-blue { color: var(--accent-blue); background: rgba(74,138,212,0.10); border-color: rgba(74,138,212,0.28); }
.rw-tone-gray { color: var(--text-secondary); background: rgba(142,152,162,0.10); border-color: var(--border); }
.rw-tone-purple { color: var(--accent-purple); background: rgba(155,133,200,0.10); border-color: rgba(155,133,200,0.28); }

.rw-banner { border: 1px solid var(--border); border-left-width: 3px; border-radius: 8px; padding: 9px 12px; display: flex; flex-direction: column; gap: 4px; }
.rw-banner-title { font-size: var(--text-sm); font-weight: 600; }
.rw-banner-text { font-size: var(--text-xs); color: var(--text-secondary); line-height: 1.6; }
.rw-banner-actions { display: flex; gap: 8px; margin-top: 4px; flex-wrap: wrap; }
.rw-banner.rw-tone-red { border-left-color: var(--accent-red); }
.rw-banner.rw-tone-amber { border-left-color: var(--accent-brand); }
.rw-banner.rw-tone-green { border-left-color: var(--accent-green); }
.rw-banner.rw-tone-blue { border-left-color: var(--accent-blue); }
.rw-banner.rw-tone-gray { border-left-color: var(--text-tertiary); }
.rw-banner.rw-tone-purple { border-left-color: var(--accent-purple); }

.rw-btn { display: inline-flex; align-items: center; gap: 6px; }
.rw-btn-danger { color: var(--accent-red); border-color: rgba(208,90,82,0.45); }
.rw-btn-danger:hover { background: rgba(208,90,82,0.12); }
.rw-icon { display: inline-flex; align-items: center; justify-content: center; }
.rw-input { width: 100%; background: var(--bg-input); border: 1px solid var(--border); color: var(--text-primary); border-radius: 7px; padding: 7px 10px; font-size: var(--text-sm); font-family: inherit; }
.rw-input:focus { outline: none; border-color: var(--accent-brand); }
.rw-input:disabled { opacity: 0.55; cursor: not-allowed; }
.rw-field { display: flex; flex-direction: column; gap: 5px; }
.rw-label { font-size: var(--text-xs); color: var(--text-secondary); font-weight: 600; letter-spacing: 0.02em; }
.rw-hint { font-size: var(--text-xs); color: var(--text-secondary); line-height: 1.55; }
.rw-field-error { margin: 4px 0 0; font-size: var(--text-xs); color: var(--accent-red); }
.rw-small { font-size: var(--text-xs); }
.rw-muted { color: var(--text-secondary); }
.rw-mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.rw-mono-list li { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: var(--text-xs); }
.rw-disabled { opacity: 0.55; pointer-events: none; }
.rw-check { accent-color: var(--accent-brand); width: 15px; height: 15px; margin-top: 2px; }
.rw-spinner { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--border); border-top-color: var(--accent-brand); animation: rw-spin 0.8s linear infinite; display: inline-block; }
.rw-spinner-sm { width: 13px; height: 13px; border-width: 2px; }
@keyframes rw-spin { to { transform: rotate(360deg); } }
.rw-inline-busy { display: flex; align-items: center; gap: 8px; font-size: var(--text-xs); color: var(--text-secondary); }

.rw-create-form { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.rw-create-form .rw-input { flex: 1 1 150px; }
.rw-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.rw-list-item { width: 100%; text-align: left; display: flex; flex-direction: column; gap: 4px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; cursor: pointer; color: var(--text-primary); font-family: inherit; }
.rw-list-item:hover { border-color: var(--border-hover); }
.rw-list-item-active { border-color: var(--accent-brand); background: var(--accent-brand-dim); }
.rw-list-item-loading { opacity: 0.7; cursor: progress; }
.rw-list-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.rw-list-title { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-sm); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-list-check { font-size: 10px; color: var(--accent-brand); border: 1px solid rgba(245,158,11,0.4); border-radius: 999px; padding: 0 6px; }
.rw-list-meta { font-size: var(--text-xs); color: var(--text-secondary); }
.rw-list-warn { font-size: var(--text-xs); color: var(--accent-brand); line-height: 1.5; }
.rw-list-err { font-size: var(--text-xs); color: var(--accent-red); line-height: 1.5; }
.rw-upload-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.rw-file-input { position: absolute; width: 1px; height: 1px; opacity: 0; overflow: hidden; }
.rw-legacy { display: flex; flex-direction: column; gap: 6px; }

.rw-state { display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center; padding: 48px 20px; color: var(--text-secondary); }
.rw-state-icon { color: var(--accent-brand); margin-bottom: 4px; }
.rw-state-title { margin: 0; font-size: var(--text-md); color: var(--text-primary); font-weight: 600; }
.rw-state-text { margin: 0; font-size: var(--text-sm); max-width: 520px; line-height: 1.6; }
.rw-state-meta { margin: 0; font-size: var(--text-xs); font-family: ui-monospace, Menlo, Consolas, monospace; color: var(--text-tertiary); }
.rw-state-actions { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; justify-content: center; }
.rw-loading { padding-top: 72px; }
.rw-unauthorized { padding-top: 56px; }

.rw-stepper { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 10px 14px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; }
.rw-step { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-xs); color: var(--text-secondary); padding: 3px 9px; border-radius: 999px; border: 1px solid transparent; }
.rw-step-index { width: 17px; height: 17px; border-radius: 50%; border: 1px solid var(--border); display: inline-flex; align-items: center; justify-content: center; font-size: 10px; }
.rw-step-done { color: var(--accent-green); border-color: rgba(63,185,80,0.3); }
.rw-step-current { color: var(--accent-brand); border-color: rgba(245,158,11,0.4); background: var(--accent-brand-dim); }
.rw-step-sep { color: var(--text-tertiary); font-size: 11px; }

.rw-scope-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
.rw-scope-dims { display: flex; flex-wrap: wrap; gap: 6px 14px; }
.rw-dim { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-sm); color: var(--text-primary); }
.rw-scope-note { display: flex; flex-direction: column; gap: 6px; }
.rw-textarea { width: 100%; min-height: 74px; resize: vertical; background: var(--bg-input); border: 1px solid var(--border); color: var(--text-primary); border-radius: 7px; padding: 8px 10px; font-size: var(--text-sm); font-family: inherit; line-height: 1.6; }
.rw-textarea:focus { outline: none; border-color: var(--accent-brand); }
.rw-select { background: var(--bg-input); border: 1px solid var(--border); color: var(--text-primary); border-radius: 7px; padding: 6px 9px; font-size: var(--text-sm); font-family: inherit; }
.rw-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rw-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-top: 4px; }

.rw-kv { display: flex; flex-direction: column; gap: 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.rw-kv-row { display: grid; grid-template-columns: 148px minmax(0, 1fr); gap: 10px; padding: 6px 10px; border-bottom: 1px solid var(--border-subtle, var(--border)); font-size: var(--text-xs); }
.rw-kv-row:last-child { border-bottom: none; }
.rw-kv-key { color: var(--text-secondary); }
.rw-kv-val { color: var(--text-primary); word-break: break-word; }

.rw-lamp-wrap { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-xs); color: var(--text-secondary); }
.rw-lamp { width: 9px; height: 9px; border-radius: 50%; background: var(--text-tertiary); display: inline-block; }
.rw-lamp-green { background: var(--accent-green); box-shadow: 0 0 6px var(--accent-green-glow); }
.rw-lamp-amber { background: var(--accent-brand); box-shadow: 0 0 6px var(--accent-brand-glow); }
.rw-lamp-red { background: var(--accent-red); box-shadow: 0 0 6px var(--accent-red-glow); }
.rw-lamp-gray { background: var(--text-tertiary); }
.rw-stream-status { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rw-stream-message { margin: 0; font-size: var(--text-xs); color: var(--text-secondary); min-height: 16px; }
.rw-stream-error { display: flex; flex-direction: column; gap: 8px; }
.rw-stream-error:empty { display: none; }
.rw-stream-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rw-resume-input { flex: 1 1 220px; }
.rw-log-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.rw-log { list-style: none; margin: 0; padding: 0; max-height: 220px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-input); }
.rw-log-row { display: grid; grid-template-columns: 60px 132px minmax(0, 1fr) 62px; gap: 8px; padding: 3px 9px; font-size: 11px; border-bottom: 1px solid var(--border-subtle, var(--border)); }
.rw-log-row:last-child { border-bottom: none; }
.rw-log-seq { color: var(--text-tertiary); font-family: ui-monospace, Menlo, Consolas, monospace; }
.rw-log-type { color: var(--accent-blue); font-family: ui-monospace, Menlo, Consolas, monospace; overflow: hidden; text-overflow: ellipsis; }
.rw-log-summary { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-log-time { color: var(--text-tertiary); text-align: right; font-family: ui-monospace, Menlo, Consolas, monospace; }

.rw-verdict { display: flex; flex-direction: column; gap: 8px; }
.rw-verdict-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rw-verdict-text { font-size: var(--text-sm); color: var(--text-primary); line-height: 1.6; }
.rw-plain-list { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 3px; font-size: var(--text-xs); color: var(--text-secondary); line-height: 1.55; }
.rw-warn-list li { color: var(--accent-brand); }
.rw-report-block { display: flex; flex-direction: column; gap: 4px; }

.rw-findings { display: flex; flex-direction: column; gap: 10px; }
.rw-findings-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; padding: 8px 10px; border: 1px dashed var(--border-hover); border-radius: 8px; background: var(--bg-elevated); }
.rw-finding { background: var(--bg-elevated); border: 1px solid var(--border); border-left: 3px solid var(--border-hover); border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
.rw-finding-critical { border-left-color: var(--accent-red); }
.rw-finding-major { border-left-color: var(--accent-brand); }
.rw-finding-minor { border-left-color: var(--accent-blue); }
.rw-finding-selected { box-shadow: 0 0 0 1px var(--accent-brand) inset; }
.rw-finding-head { display: flex; align-items: flex-start; gap: 9px; }
.rw-finding-label { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; cursor: pointer; }
.rw-finding-body { display: flex; flex-direction: column; gap: 8px; }
.rw-finding-section { display: flex; flex-direction: column; gap: 3px; }
.rw-finding-title { margin: 0; font-size: var(--text-xs); font-weight: 600; color: var(--text-secondary); letter-spacing: 0.02em; }
.rw-finding-text { margin: 0; font-size: var(--text-sm); color: var(--text-primary); line-height: 1.65; white-space: pre-wrap; }
.rw-quote { margin: 0; padding: 6px 10px; border-left: 2px solid var(--border-hover); background: var(--bg-input); color: var(--text-secondary); font-size: var(--text-xs); line-height: 1.6; white-space: pre-wrap; border-radius: 0 6px 6px 0; max-height: 180px; overflow: auto; }
.rw-locator { display: flex; flex-direction: column; gap: 2px; }
.rw-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.rw-finding-footer { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; border-top: 1px solid var(--border-subtle, var(--border)); padding-top: 8px; }
.rw-finding-footer .rw-hint { flex: 1 1 200px; text-align: left; }

.rw-revision .rw-card-body { gap: 12px; }
.rw-chart-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px 14px; }
.rw-chart-result { display: flex; flex-direction: column; gap: 12px; }
.rw-chart-image { width: 100%; max-width: 760px; border: 1px solid var(--border); border-radius: 10px; background: #fff; }
.rw-diff-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.rw-diff { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; background: var(--bg-input); display: flex; flex-direction: column; gap: 6px; }
.rw-diff-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rw-diff-index { font-size: var(--text-xs); font-weight: 700; color: var(--accent-brand); }
.rw-diff-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
@media (max-width: 820px) { .rw-diff-grid { grid-template-columns: 1fr; } }
.rw-diff-block { border-radius: 6px; padding: 7px 9px; border: 1px solid var(--border); min-width: 0; }
.rw-diff-original { background: rgba(208,90,82,0.06); border-color: rgba(208,90,82,0.22); }
.rw-diff-suggestion { background: rgba(63,185,80,0.06); border-color: rgba(63,185,80,0.22); }
.rw-diff-label { font-size: 10px; color: var(--text-secondary); letter-spacing: 0.06em; margin-bottom: 3px; }
.rw-diff-text { margin: 0; font-size: var(--text-xs); line-height: 1.65; color: var(--text-primary); white-space: pre-wrap; word-break: break-word; font-family: inherit; max-height: 200px; overflow: auto; }
.rw-diff-reason { margin: 0; font-size: var(--text-xs); color: var(--text-secondary); line-height: 1.6; }
.rw-apply-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; border-top: 1px solid var(--border-subtle, var(--border)); padding-top: 10px; }
.rw-apply-bar .rw-hint { flex: 1 1 240px; }
.rw-pre { margin: 0; padding: 10px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 8px; font-size: var(--text-xs); line-height: 1.6; color: var(--text-secondary); white-space: pre-wrap; max-height: 360px; overflow: auto; }

.rw-export-result { display: flex; flex-direction: column; gap: 6px; }
.rw-cap-body { gap: 6px; }
.rw-cap-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
.rw-cap-row { display: flex; flex-direction: column; gap: 2px; }
.rw-cap-line { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: var(--text-xs); color: var(--text-primary); }
.rw-cap-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-cap-reason { margin: 0; font-size: 11px; color: var(--text-secondary); line-height: 1.5; }
`;
  document.head.appendChild(style);
  styleInjected = true;
}

// ── 小工具 ────────────────────────────────────────────────────
function storageKey() {
  const userId = state.auth?.user?.id ?? state.auth?.user?.username ?? 'anon';
  return `${STATE_PREFIX}${userId}`;
}

function loadSaved() {
  try {
    const raw = localStorage.getItem(storageKey());
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveState() {
  try {
    localStorage.setItem(storageKey(), JSON.stringify({
      projectId: s.project?.id || null,
      documentId: s.selectedDocumentId,
      reviewTaskId: s.review.taskId,
      revisionTaskId: s.revision.taskId,
      objective: s.objective,
      dimensions: [...s.dimensions],
      mode: s.mode,
      selectedFindingIds: [...s.selectedFindingIds],
    }));
  } catch {
    /* 存储不可用时不影响主流程 */
  }
}

function selectedDoc() {
  return s.documents.find((doc) => doc.id === s.selectedDocumentId) || null;
}

function currentVersionId() {
  if (s.revision.applyResult?.new_version_id) return s.revision.applyResult.new_version_id;
  return selectedDoc()?.current_version_id || null;
}

function capabilityOf(name) {
  return s.capIndex.get(name) || null;
}

function gate(names) {
  const blocked = [];
  const missing = [];
  names.filter(Boolean).forEach((name) => {
    const cap = s.capIndex.get(name);
    if (!cap) {
      missing.push(name);
      return;
    }
    if (cap.status !== 'ready' && cap.status !== 'degraded') blocked.push(cap);
  });
  return { ok: blocked.length === 0, blocked, missing };
}

function gateText(result) {
  return result.blocked
    .map((cap) => `${capabilityLabel(cap.name)}：${cap.reason || '当前不可用'}`)
    .join('；');
}

function parseExt(filename) {
  const index = String(filename || '').lastIndexOf('.');
  return index === -1 ? '' : String(filename).slice(index).toLowerCase();
}

function parserGateFor(filename) {
  const ext = parseExt(filename);
  const names = ['document.parser.text'];
  if (ext === '.pdf') names.push('document.parser.pdf');
  if (ext === '.docx') names.push('document.parser.docx');
  const result = gate(names);
  if (result.ok) return { ok: true };
  return { ok: false, reason: `无法上传：${gateText(result)}。请先启用对应解析能力或改用 .txt / .md 文件。` };
}

function isUnauthorizedError(err) {
  return err?.status === 401 || err?.status === 403;
}

function legacyCandidate() {
  try {
    const raw = localStorage.getItem(LEGACY_KEY);
    if (!raw) return null;
    const text = typeof raw === 'string' ? raw : '';
    const chars = text.replace(/\s/g, '').length;
    return chars > 0 ? { chars, text } : null;
  } catch {
    return null;
  }
}

function setStream(partial) {
  taskStream?.setStream(partial);
}

function stopStream({ silent = false } = {}) {
  if (s.reconnectTimer) {
    clearTimeout(s.reconnectTimer);
    s.reconnectTimer = null;
  }
  if (s.streamAbort) {
    s.streamAbort.abort();
    s.streamAbort = null;
  }
  if (!silent) setStream({ state: 'aborted', message: '已断开本地事件流；服务端任务继续执行，可随时重新连接。' });
}

// ── 任务快照与流 ───────────────────────────────────────────────
function applySnapshot(task, taskId) {
  const snapshot = { ...(task || {}), id: task?.id || taskId };
  if (taskId === s.review.taskId) s.review.task = snapshot;
  if (taskId === s.revision.taskId) s.revision.task = snapshot;
  taskStream?.setTask(snapshot);
  sync();
  return snapshot;
}

async function refreshSnapshot(taskId) {
  try {
    const snapshot = await getTask(taskId);
    applySnapshot(snapshot, taskId);
    if (isTerminal(snapshot.status)) {
      setStream({ state: 'closed', message: '任务已结束，事件流已关闭。' });
      await afterTerminal(taskId, snapshot);
    }
    return snapshot;
  } catch (err) {
    setStream({ state: 'error', message: `读取任务快照失败：${err?.message || err}` });
    return null;
  }
}

async function afterTerminal(taskId, snapshot) {
  if (taskId === s.review.taskId) {
    await loadFindings();
  } else if (taskId === s.revision.taskId) {
    await loadProposal();
  }
  sync();
  saveState();
}

async function runStream(taskId) {
  stopStream({ silent: true });
  const controller = new AbortController();
  s.streamAbort = controller;
  let attempt = 0;

  while (!controller.signal.aborted && attempt <= MAX_RECONNECTS) {
    setStream({
      state: attempt === 0 ? 'connecting' : 'reconnecting',
      lastSequence: s.streamSeq,
      message: attempt === 0 ? '正在连接事件流…' : `第 ${attempt} 次重连，从序号 ${s.streamSeq ?? '起点'} 续订…`,
    });
    let aborted = false;
    try {
      const result = await streamTaskEvents(taskId, {
        signal: controller.signal,
        afterSequence: s.streamSeq ?? undefined,
        onOpen: () => setStream({ state: 'open', lastSequence: s.streamSeq, message: '已连接；事件按序号追加。' }),
        onEvent: (frame) => {
          taskStream?.pushEvent(frame);
          if (frame.id !== null && frame.id !== undefined) {
            s.streamSeq = frame.id;
            setStream({ state: 'open', lastSequence: s.streamSeq, message: `收到事件 #${frame.id}` });
          }
          const type = frame.data?.type || frame.event;
          if (type && /^task\.(completed|partial|failed|cancelled|needs_input|recoverable)$/.test(type)) {
            refreshSnapshot(taskId);
          }
        },
      });
      aborted = result.aborted;
      if (!aborted) {
        // 服务端主动关闭（60s 无新事件或任务结束）：先核对快照再决定是否续订。
        s.streamSeq = result.lastSequence ?? s.streamSeq;
      }
    } catch (err) {
      if (err?.name === 'AbortError' || controller.signal.aborted) {
        aborted = true;
      } else if (isUnauthorizedError(err)) {
        setStream({ state: 'error', message: '登录状态失效，事件流已停止。' });
        s.status = 'unauthorized';
        sync();
        return;
      } else {
        setStream({ state: 'error', message: `事件流异常：${err?.message || err}` });
      }
    }

    if (controller.signal.aborted || aborted) {
      setStream({ state: 'aborted', message: '已断开本地事件流；服务端任务继续执行，可随时重新连接。' });
      return;
    }

    const snapshot = await refreshSnapshot(taskId);
    if (snapshot && isTerminal(snapshot.status)) {
      setStream({ state: 'closed', message: '任务已结束，事件流已关闭。' });
      return;
    }

    attempt += 1;
    const delay = Math.min(1000 * 2 ** Math.min(attempt, 4), 15000);
    setStream({ state: 'reconnecting', lastSequence: s.streamSeq, message: `${delay / 1000}s 后自动续订（后台任务未取消）。` });
    await new Promise((resolve) => {
      s.reconnectTimer = setTimeout(resolve, delay);
    });
    s.reconnectTimer = null;
    if (controller.signal.aborted) return;
  }
  setStream({ state: 'error', message: '重连次数已达上限；可点击「重新连接事件流」继续，服务端任务未取消。' });
}

// ── 数据加载 ─────────────────────────────────────────────────
async function loadCapabilities() {
  s.capLoading = true;
  renderCapabilities();
  try {
    const data = await getCapabilities();
    s.capabilities = Array.isArray(data?.capabilities) ? data.capabilities : [];
    s.capIndex = capabilityIndex(s.capabilities);
    s.capError = null;
  } catch (err) {
    s.capError = err;
    s.capabilities = [];
    s.capIndex = new Map();
    if (isUnauthorizedError(err)) {
      s.status = 'unauthorized';
    } else {
      // 能力清单是页面判断「能不能做」的唯一依据，读不到就不假装 ready。
      s.status = 'error';
      s.error = err;
    }
  } finally {
    s.capLoading = false;
    renderCapabilities();
    sync();
  }
}

async function loadProjects() {
  s.projectsLoading = true;
  s.projectsError = null;
  renderProjects();
  try {
    const data = await listProjects({ limit: 50 });
    s.projects = Array.isArray(data?.items) ? data.items : [];
    if (data?.next_cursor) {
      showToast('项目较多，这里只显示最近 50 个；可用刷新按钮重新读取。', 'info', 4000);
    }
  } catch (err) {
    s.projectsError = err;
    s.projects = [];
    if (isUnauthorizedError(err)) {
      s.status = 'unauthorized';
    } else {
      s.status = 'error';
      s.error = err;
    }
  } finally {
    s.projectsLoading = false;
    s.creating = false;
    renderProjects();
    sync();
  }
}

async function selectProject(projectId) {
  s.projectLoadingId = projectId;
  s.uploadError = null;
  renderProjects();
  try {
    const project = await getProject(projectId);
    s.project = project;
    s.documents = Array.isArray(project?.documents) ? project.documents : [];
    if (!s.documents.some((doc) => doc.id === s.selectedDocumentId)) {
      s.selectedDocumentId = null;
    }
    s.projects = s.projects.map((item) => (item.id === project.id
      ? { ...item, document_count: project.document_count ?? item.document_count, updated_at: project.updated_at || item.updated_at }
      : item));
  } catch (err) {
    if (isUnauthorizedError(err)) {
      s.status = 'unauthorized';
    } else {
      showToast(`读取项目失败：${err?.message || err}`, 'error', 4000);
    }
  } finally {
    s.projectLoadingId = null;
    renderProjects();
    renderDocs();
    sync();
    saveState();
  }
}

async function refreshProject(silent = false) {
  if (!s.project?.id) return;
  try {
    const project = await getProject(s.project.id);
    s.project = project;
    s.documents = Array.isArray(project?.documents) ? project.documents : [];
    if (!s.documents.some((doc) => doc.id === s.selectedDocumentId)) s.selectedDocumentId = null;
    s.projects = s.projects.map((item) => (item.id === project.id
      ? { ...item, document_count: project.document_count ?? item.document_count, updated_at: project.updated_at || item.updated_at }
      : item));
    renderProjects();
    renderDocs();
    sync();
  } catch (err) {
    if (!silent) showToast(`刷新项目失败：${err?.message || err}`, 'error', 4000);
  }
}

async function handleUpload(file) {
  s.uploading = true;
  s.uploadError = null;
  renderDocs();
  try {
    const result = await uploadDocument(s.project.id, file);
    const doc = result?.document || null;
    const version = result?.version || null;
    if (doc && !version) {
      // 上传成功但版本缺失：仍然刷新项目，避免页面伪造解析状态。
      await refreshProject(true);
      showToast('上传成功，但响应中缺少版本信息；已刷新文档列表。', 'info', 4000);
      return;
    }
    await refreshProject(true);
    if (doc) {
      s.selectedDocumentId = doc.id;
      if (result?.reused) showToast('相同内容已存在，服务端复用了已有文档版本。', 'success');
      else showToast('上传并解析完成。', 'success');
    }
    if (version?.parse_status === 'partial') {
      showToast('文档仅部分解析：诊断只覆盖已解析内容。', 'info', 5000);
    } else if (version?.parse_status === 'unsupported' || version?.parse_status === 'failed') {
      showToast('文档解析失败或格式不受支持，不能作为诊断输入。', 'error', 5000);
    }
  } catch (err) {
    if (isUnauthorizedError(err)) {
      s.status = 'unauthorized';
    } else {
      s.uploadError = err;
    }
  } finally {
    s.uploading = false;
    renderDocs();
    sync();
    saveState();
  }
}

async function importLegacy() {
  const candidate = legacyCandidate();
  if (!candidate) return;
  const ok = await showConfirmDialog({
    title: '导入旧版本地写作内容',
    message: `将把浏览器里约 ${candidate.chars} 字的内容作为 .md 文件上传到当前项目，并替换当前诊断文档。原 localStorage 内容不会被删除。`,
    confirmText: '导入上传',
    variant: 'info',
  });
  if (!ok) return;
  s.importingLegacy = true;
  const file = new File([candidate.text], 'legacy-writing.md', { type: 'text/markdown' });
  await handleUpload(file);
  s.importingLegacy = false;
  renderDocs();
}

async function loadFindings() {
  if (!s.review.taskId) return;
  s.review.loading = true;
  s.review.error = null;
  renderFindings();
  try {
    const all = [];
    let cursor = null;
    for (let page = 0; page < 10; page += 1) {
      const data = await getFindings(s.review.taskId, { limit: 100, cursor: cursor || undefined });
      const items = Array.isArray(data?.items) ? data.items : [];
      all.push(...items);
      cursor = data?.next_cursor || null;
      if (!cursor) break;
    }
    s.review.findings = all;
    const validIds = new Set(all.map((item) => item.id));
    s.selectedFindingIds = new Set([...s.selectedFindingIds].filter((id) => validIds.has(id)));
  } catch (err) {
    if (isUnauthorizedError(err)) s.status = 'unauthorized';
    else s.review.error = err;
  } finally {
    s.review.loading = false;
    renderFindings();
    sync();
    saveState();
  }
}

async function loadProposal() {
  const taskId = s.revision.taskId;
  if (!taskId) return;
  const snapshot = s.revision.task;
  const artifactIds = Array.isArray(snapshot?.artifact_ids) ? snapshot.artifact_ids : [];
  if (!artifactIds.length) {
    renderProposal();
    return;
  }
  s.revision.loading = true;
  s.revision.error = null;
  renderProposal();
  try {
    let proposals = [];
    for (const id of artifactIds) {
      try {
        const artifact = await getArtifact(id);
        if (artifact?.kind === 'revision_proposal') proposals.push(artifact);
      } catch {
        /* 单个成果读取失败不影响其它成果 */
      }
    }
    if (!proposals.length) {
      s.revision.artifact = null;
      s.revision.validation = null;
      s.revision.markdown = '';
      s.revision.error = new Error('任务未产出 revision_proposal 成果；可查看事件日志或重试任务。');
      return;
    }
    const artifact = proposals[proposals.length - 1];
    s.revision.artifact = artifact;
    s.revision.validation = artifact.validation || {};
    s.revision.markdown = await getArtifactText(artifact.id);
  } catch (err) {
    if (isUnauthorizedError(err)) s.status = 'unauthorized';
    else s.revision.error = err;
  } finally {
    s.revision.loading = false;
    renderProposal();
    sync();
    saveState();
  }
}

// ── 任务创建 ─────────────────────────────────────────────────
function baseTaskPayload(kind) {
  const versionId = currentVersionId();
  return {
    schema_version: '1.0',
    project_id: s.project?.id,
    kind,
    objective: s.objective.trim(),
    input: { document_version_id: versionId, source_ids: [] },
    scope: {
      section_ids: [],
      dimensions: [...s.dimensions],
      finding_ids: [],
    },
    constraints: {
      protected_block_ids: [],
      preserve: PRESERVE,
      journal_style: 'generic',
      no_new_empirical_claims: true,
    },
    mode: s.mode || null,
    skill_ids: [],
  };
}

async function startReview() {
  const versionId = currentVersionId();
  if (!s.project?.id || !versionId) {
    showToast('请先选择项目与文档。', 'error');
    return;
  }
  if (!s.objective.trim()) {
    showToast('请填写诊断目标（1–4000 字）。', 'error');
    return;
  }
  if (!s.dimensions.size) {
    showToast('至少选择一个诊断维度。', 'error');
    return;
  }
  const gateResult = gate(['task.engine', 'task.review', 'model.llm']);
  if (!gateResult.ok) {
    showToast(`无法启动诊断：${gateText(gateResult)}`, 'error', 5000);
    return;
  }
  s.review = { taskId: null, task: null, findings: [], loading: false, error: null };
  s.revision = {
    taskId: null, task: null, artifact: null, validation: null, markdown: '',
    loading: false, error: null, applyState: 'idle', applyError: null, conflict: false, applyResult: null,
  };
  s.selectedFindingIds = new Set();
  s.streamSeq = null;
  taskStream?.reset();
  renderFindings();
  renderProposal();
  sync();

  try {
    const accepted = await createTask(baseTaskPayload('review'), newIdempotencyKey());
    s.review.taskId = accepted.task_id;
    s.activeTaskId = accepted.task_id;
    saveState();
    setStream({ state: 'connecting', message: '诊断任务已受理，正在连接事件流…' });
    taskStream?.setTask({ id: accepted.task_id, status: accepted.status || 'queued', kind: 'review', state_revision: accepted.state_revision, attempt_no: 1 });
    runStream(accepted.task_id);
    await refreshSnapshot(accepted.task_id);
    sync();
  } catch (err) {
    if (isUnauthorizedError(err)) {
      s.status = 'unauthorized';
      sync();
      return;
    }
    s.review.error = err;
    taskStream?.setStream({ state: 'error', message: `诊断任务创建失败：${err?.message || err}` });
    sync();
  }
}

async function startRevision(findingIds, note = '') {
  const versionId = currentVersionId();
  if (!s.project?.id || !versionId) {
    showToast('请先选择项目与文档。', 'error');
    return;
  }
  if (!findingIds.length) {
    showToast('请至少选择一个诊断项。', 'error');
    return;
  }
  const gateResult = gate(['task.engine', 'task.revision', 'model.llm']);
  if (!gateResult.ok) {
    showToast(`无法生成修改建议：${gateText(gateResult)}`, 'error', 5000);
    return;
  }
  const picked = s.review.findings.filter((item) => findingIds.includes(item.id));
  const problems = picked.map((item) => `- ${item.problem}`).join('\n');
  const objective = [
    note || '按诊断项修改文档，保持原有论证结构与实证主张。',
    '需要处理的诊断项：',
    problems,
  ].join('\n').slice(0, 4000);

  const payload = { ...baseTaskPayload('revision'), objective };
  payload.scope = { section_ids: [], dimensions: [...s.dimensions], finding_ids: [...findingIds] };

  s.revision.taskId = null;
  s.revision.task = null;
  s.revision.artifact = null;
  s.revision.validation = null;
  s.revision.markdown = '';
  s.revision.error = null;
  s.revision.applyState = 'idle';
  s.revision.applyError = null;
  s.revision.conflict = false;
  s.revision.applyResult = null;
  s.streamSeq = null;
  taskStream?.reset();
  renderProposal();
  sync();

  try {
    const accepted = await createTask(payload, newIdempotencyKey());
    s.revision.taskId = accepted.task_id;
    s.activeTaskId = accepted.task_id;
    saveState();
    setStream({ state: 'connecting', message: '修改建议任务已受理，正在连接事件流…' });
    taskStream?.setTask({ id: accepted.task_id, status: accepted.status || 'queued', kind: 'revision', state_revision: accepted.state_revision, attempt_no: 1 });
    runStream(accepted.task_id);
    await refreshSnapshot(accepted.task_id);
    sync();
  } catch (err) {
    if (isUnauthorizedError(err)) {
      s.status = 'unauthorized';
      sync();
      return;
    }
    s.revision.error = err;
    taskStream?.setStream({ state: 'error', message: `修改建议任务创建失败：${err?.message || err}` });
    sync();
  }
}

async function handleApply() {
  const proposalId = s.revision.validation?.proposal_id;
  const baseVersion = s.revision.validation?.base_version_id;
  if (!proposalId || !baseVersion) {
    showToast('缺少提案 ID 或基准版本，无法应用。', 'error');
    return;
  }
  const ok = await showConfirmDialog({
    title: '采纳整份修改提案',
    message: '将调用 POST /revision-proposals/{id}/apply，以 hunk_ids: [] 应用整份提案并生成新的文档版本。原文档不会被直接覆盖；若基准版本已变化，服务端会返回 409 并拒绝。',
    confirmText: '应用整份提案',
    variant: 'info',
  });
  if (!ok) return;
  s.revision.applyState = 'applying';
  s.revision.applyError = null;
  s.revision.conflict = false;
  renderProposal();
  try {
    const result = await applyProposal(proposalId, { expected_version_id: baseVersion, hunk_ids: [] });
    s.revision.applyState = 'applied';
    s.revision.applyResult = result;
    showToast('提案已应用，已生成新文档版本。', 'success', 4000);
    await refreshProject(true);
    if (result?.new_version_id) {
      const doc = selectedDoc();
      if (doc) s.selectedDocumentId = doc.id;
    }
  } catch (err) {
    s.revision.applyState = 'failed';
    s.revision.applyError = err;
    s.revision.conflict = err?.status === 409 || err?.data?.error?.code === 'VERSION_CONFLICT';
    if (s.revision.conflict) showToast('版本冲突：文档已变化，请重新诊断。', 'error', 5000);
    else showToast(`应用失败：${err?.message || err}`, 'error', 5000);
  } finally {
    renderProposal();
    sync();
  }
}

async function handleExport() {
  const versionId = currentVersionId();
  if (!s.project?.id || !versionId) {
    showToast('请先选择项目与文档。', 'error');
    return;
  }
  const format = els.exportFormat?.value || 'md';
  const gateResult = gate([format === 'docx' ? 'export.docx' : 'export.md']);
  if (!gateResult.ok) {
    s.exportError = new Error(`无法导出：${gateText(gateResult)}`);
    sync();
    return;
  }
  s.exporting = true;
  s.exportError = null;
  s.exportResult = null;
  sync();
  try {
    const artifact = await exportArtifact({
      project_id: s.project.id,
      document_version_id: versionId,
      format,
      journal_style: 'generic',
      include_report: Boolean(els.exportIncludeReport?.checked),
      include_change_log: Boolean(els.exportIncludeChangeLog?.checked),
    });
    s.exportResult = artifact;
    showToast('导出成功，可点击下载。', 'success');
  } catch (err) {
    if (isUnauthorizedError(err)) s.status = 'unauthorized';
    else s.exportError = err;
  } finally {
    s.exporting = false;
    sync();
  }
}

async function downloadResult(artifactId) {
  try {
    await downloadArtifact(artifactId);
    showToast('已开始下载。', 'success');
  } catch (err) {
    showToast(`下载失败：${err?.message || err}`, 'error', 5000);
  }
}

async function handleCancel() {
  const task = s.review.task?.status && s.review.taskId === s.activeTaskId ? s.review.task : s.revision.task;
  if (!task?.id) return;
  const ok = await showConfirmDialog({
    title: '取消任务',
    message: '取消会终止服务端任务，且无法继续该任务的产出。若只是想停止页面刷新，请改用「断开本地流」。',
    confirmText: '取消任务',
  });
  if (!ok) return;
  try {
    const snapshot = await cancelTask(task.id);
    applySnapshot(snapshot, task.id);
    showToast('任务已取消。', 'info');
  } catch (err) {
    showToast(`取消失败：${err?.message || err}`, 'error', 5000);
  }
}

async function handleRetry() {
  const task = s.review.taskId === s.activeTaskId ? s.review.task : s.revision.task;
  if (!task?.id || !task.state_revision) return;
  try {
    const accepted = await retryTask(task.id, task.state_revision);
    s.streamSeq = null;
    taskStream?.reset();
    if (task.kind === 'revision' || task.id === s.revision.taskId) {
      s.revision.taskId = accepted.task_id;
      s.activeTaskId = accepted.task_id;
      s.revision.task = null;
      s.revision.artifact = null;
      s.revision.markdown = '';
    } else {
      s.review.taskId = accepted.task_id;
      s.activeTaskId = accepted.task_id;
      s.review.task = null;
      s.review.findings = [];
    }
    saveState();
    sync();
    runStream(accepted.task_id);
    await refreshSnapshot(accepted.task_id);
    showToast(`已重试，新尝试编号 ${accepted.attempt_no ?? ''}`.trim(), 'info');
  } catch (err) {
    const code = err?.data?.error?.code;
    if (code === 'STATE_REVISION_MISMATCH') {
      showToast('任务状态已变化（STATE_REVISION_MISMATCH），请先刷新任务快照再重试。', 'error', 5000);
      await refreshSnapshot(task.id);
    } else {
      showToast(`重试失败：${err?.message || err}`, 'error', 5000);
    }
  }
}

async function handleResume(answer) {
  const task = s.review.taskId === s.activeTaskId ? s.review.task : s.revision.task;
  if (!task?.id) return;
  try {
    const snapshot = await resumeTask(task.id, {
      expected_state_revision: task.state_revision,
      answers: answer ? { user_note: answer } : {},
      supplemental_source_ids: [],
    });
    applySnapshot(snapshot, task.id);
    setStream({ state: 'connecting', message: '已提交补充输入，继续订阅事件流…' });
    runStream(task.id);
    showToast('已提交补充输入。', 'success');
  } catch (err) {
    showToast(`恢复失败：${err?.message || err}`, 'error', 5000);
  }
}

// ── 渲染 ─────────────────────────────────────────────────────
function currentStep() {
  if (!s.project) return 0;
  if (!s.documents.length) return 1;
  if (!s.review.taskId) return 2;
  if (!isTerminal(s.review.task?.status)) return 3;
  if (!s.review.findings.length) return 4;
  if (!s.selectedFindingIds.size && !s.revision.taskId) return 5;
  if (!s.revision.applyResult) return 6;
  return 7;
}

function renderStepper() {
  const steps = ['项目', '上传', '确认范围', '全文诊断', '问题与依据', '选择目标', '采纳修改', '导出'];
  const active = currentStep();
  els.stepper.replaceChildren();
  steps.forEach((label, index) => {
    const cls = index < active ? 'rw-step rw-step-done' : index === active ? 'rw-step rw-step-current' : 'rw-step';
    const step = createElement('span', { className: cls });
    step.appendChild(createElement('span', { className: 'rw-step-index' }, index < active ? '✓' : String(index + 1)));
    step.appendChild(createElement('span', {}, label));
    els.stepper.appendChild(step);
    if (index < steps.length - 1) {
      els.stepper.appendChild(createElement('span', { className: 'rw-step-sep' }, '→'));
    }
  });
}

function renderHeader() {
  els.headerPills.replaceChildren();
  const caps = s.capabilities;
  if (s.capLoading) {
    els.headerPills.appendChild(pill('读取能力状态…', 'gray'));
  } else if (s.capError) {
    els.headerPills.appendChild(pill('能力状态未知', 'red'));
  } else if (!caps.length) {
    els.headerPills.appendChild(pill('能力清单未上报', 'gray'));
  } else {
    const bad = caps.filter((cap) => cap.status !== 'ready' && cap.status !== 'degraded');
    els.headerPills.appendChild(bad.length
      ? pill(`${bad.length} 项能力不可用`, 'amber')
      : pill('能力就绪', 'green'));
    const degraded = caps.filter((cap) => cap.status === 'degraded').length;
    if (degraded) els.headerPills.appendChild(pill(`${degraded} 项降级`, 'amber'));
  }
  if (s.project) {
    els.headerPills.appendChild(pill(`项目：${shortId(s.project.title, 20)}`, 'blue'));
  }
}

function renderProjects() {
  if (!els.projects) return;
  els.projects.replaceChildren(ProjectList({
    projects: s.projects,
    activeId: s.project?.id || null,
    loadingId: s.projectLoadingId,
    creating: s.creating,
    error: s.projectsError,
    onRefresh: () => loadProjects(),
    onCreate: async (title) => {
      s.creating = true;
      renderProjects();
      try {
        const project = await createProject({ title });
        s.creating = false;
        s.project = project;
        s.documents = Array.isArray(project?.documents) ? project.documents : [];
        s.selectedDocumentId = null;
        await loadProjects();
        await selectProject(project.id);
        showToast('项目已创建。', 'success');
      } catch (err) {
        s.creating = false;
        renderProjects();
        throw err;
      }
    },
    onSelect: (id) => selectProject(id),
  }));
}

function renderCapabilities() {
  if (!els.capabilities) return;
  els.capabilities.replaceChildren(CapabilityPanel({
    capabilities: s.capabilities,
    loading: s.capLoading,
    error: s.capError,
  }));
}

function renderDocs() {
  if (!els.docs) return;
  els.docs.replaceChildren(DocumentUpload({
    project: s.project,
    documents: s.documents,
    selectedDocumentId: s.selectedDocumentId,
    loadingDocumentId: s.documentLoadingId,
    uploading: s.uploading,
    uploadError: s.uploadError,
    parserGateFor,
    legacyCandidate: legacyCandidate(),
    onImportLegacy: importLegacy,
    onUpload: handleUpload,
    onSelectDocument: (id) => {
      s.selectedDocumentId = id;
      s.review = { taskId: null, task: null, findings: [], loading: false, error: null };
      s.revision = {
        taskId: null, task: null, artifact: null, validation: null, markdown: '',
        loading: false, error: null, applyState: 'idle', applyError: null, conflict: false, applyResult: null,
      };
      s.selectedFindingIds = new Set();
      s.streamSeq = null;
      stopStream({ silent: true });
      taskStream?.reset();
      setStream({ state: 'idle' });
      renderDocs();
      renderFindings();
      renderProposal();
      sync();
      saveState();
    },
  }));
}

function renderDiagnosis() {
  if (!els.diagnosis) return;
  els.diagnosis.replaceChildren(DiagnosisReport({
    task: s.review.task,
    findings: s.review.findings,
    loading: s.review.loading,
    error: s.review.error,
    onRetryLoad: () => loadFindings(),
    onRetryTask: () => handleRetry(),
  }));
}

function renderScope() {
  const versionId = currentVersionId();
  const doc = selectedDoc();
  const reviewGate = gate(['task.engine', 'task.review', 'model.llm']);
  const ready = Boolean(s.project && versionId && doc);
  const canStart = ready && reviewGate.ok && s.objective.trim().length > 0 && s.dimensions.size > 0;

  els.startReviewBtn.disabled = !canStart;
  els.startReviewBtn.title = !ready
    ? '需要先选择项目与文档'
    : !reviewGate.ok
      ? gateText(reviewGate)
      : !s.objective.trim()
        ? '请填写诊断目标'
        : !s.dimensions.size ? '至少选择一个维度' : '创建 review 任务并订阅事件流';

  els.scopeGate.replaceChildren();
  if (!ready) {
    els.scopeGate.appendChild(notice({
      tone: 'gray',
      title: '尚不能开始诊断',
      text: s.project ? '请先在「文档」卡片上传或选择一个已解析文档。' : '请先在左侧选择或新建一个研究项目。',
    }));
  } else if (!reviewGate.ok) {
    els.scopeGate.appendChild(notice({
      tone: 'red',
      title: '全文诊断能力当前不可用',
      text: `${gateText(reviewGate)}。该按钮已禁用，不会假装成功；可在左侧能力状态查看逐项原因。`,
    }));
  } else if (doc && (doc.parse_status === 'unsupported' || doc.parse_status === 'failed')) {
    els.scopeGate.appendChild(notice({
      tone: 'red',
      title: '当前文档不能作为诊断输入',
      text: '该文档解析失败或格式不受支持。请更换文件或重新上传。',
    }));
  } else if (doc && doc.parse_status === 'partial') {
    els.scopeGate.appendChild(notice({
      tone: 'amber',
      title: '当前文档仅部分解析',
      text: '诊断只覆盖已解析内容；未解析部分不会进入结论。',
    }));
  } else if (reviewGate.blocked.length === 0 && reviewGate.missing.length) {
    els.scopeGate.appendChild(notice({
      tone: 'gray',
      title: '部分能力未上报',
      text: `后端未上报：${reviewGate.missing.map(capabilityLabel).join('、')}。启动后仍以服务端校验为准。`,
    }));
  }
  els.scopeMeta.replaceChildren();
  if (doc) {
    els.scopeMeta.appendChild(pill(`文档：${shortId(doc.filename, 24)}`, 'blue'));
    els.scopeMeta.appendChild(pill(`版本：${shortId(versionId, 14)}`, 'gray'));
  }
  els.scopeMeta.appendChild(pill(`维度：${[...s.dimensions].map(dimensionLabel).join(' / ') || '未选择'}`, s.dimensions.size ? 'green' : 'red'));
  els.scopeMeta.appendChild(pill(`模式：${s.mode === 'pro' ? 'pro（更充分）' : 'flash（更快）'}`, 'gray'));
}

function renderFindings() {
  if (!els.findings) return;
  const findings = s.review.findings;
  const selected = s.selectedFindingIds;
  const revisionGate = gate(['task.engine', 'task.revision', 'model.llm']);
  const terminal = isTerminal(s.review.task?.status);

  els.findings.replaceChildren();

  const bar = createElement('div', { className: 'rw-findings-bar' });
  bar.appendChild(createElement(
    'span',
    { className: 'rw-small' },
    findings.length
      ? `已选 ${selected.size} / ${findings.length} 项；逐项勾选后可一次生成整份修改建议。`
      : '尚未读取到诊断项。'
  ));
  const barActions = createElement('div', { className: 'rw-row' });
  if (selected.size) {
    barActions.appendChild(button('清除选择', {
      onClick: () => {
        selected.clear();
        renderFindings();
        sync();
      },
    }));
  }
  const adoptBtn = button(`为所选 ${selected.size} 项生成修改建议`, {
    tone: 'primary',
    disabled: !selected.size || !terminal || !revisionGate.ok,
    onClick: () => startRevision([...selected]),
    title: !terminal
      ? '诊断任务尚未结束'
      : !revisionGate.ok ? gateText(revisionGate) : '创建 revision 任务（finding_ids = 已选项）',
  });
  barActions.appendChild(adoptBtn);
  bar.appendChild(barActions);
  els.findings.appendChild(bar);

  if (!terminal && s.review.taskId) {
    els.findings.appendChild(notice({
      tone: 'blue',
      title: '诊断进行中',
      text: '诊断项会在任务结束后一次性返回（GET /tasks/{id}/findings）。当前列表为空不等于没有问题。',
    }));
    return;
  }
  if (terminal && !findings.length && !s.review.loading && !s.review.error) {
    els.findings.appendChild(notice({
      tone: 'gray',
      title: '没有诊断项',
      text: '后端未返回 finding。该结果只覆盖已分析内容，不代表论文无需修改。',
    }));
    return;
  }

  const list = createElement('div', { className: 'rw-findings' });
  findings.forEach((finding, index) => {
    list.appendChild(FindingCard({
      finding,
      index,
      selected: selected.has(finding.id),
      onToggle: (id, checked) => {
        if (checked) selected.add(id);
        else selected.delete(id);
        renderFindings();
        sync();
        saveState();
      },
      onAdopt: (item) => startRevision([item.id], `只修改该诊断项：${item.problem}`),
      adoptDisabled: !terminal || !revisionGate.ok,
      adoptDisabledReason: !terminal
        ? '诊断任务未结束，暂不能生成修改建议。'
        : !revisionGate.ok ? `修改建议能力不可用：${gateText(revisionGate)}` : '',
    }));
  });
  els.findings.appendChild(list);
}

function renderProposal() {
  if (!els.proposal) return;
  const r = s.revision;
  els.proposal.replaceChildren();
  if (!r.taskId && !r.error) {
    els.proposal.appendChild(notice({
      tone: 'gray',
      title: '还没有修改建议',
      text: '在上方勾选诊断项后点击「为所选 N 项生成修改建议」。每份提案覆盖它自己的那些诊断项；需要只采纳一条时请用该卡片上的单条按钮。',
    }));
    return;
  }
  if (r.error && !r.artifact) {
    els.proposal.appendChild(notice({
      tone: 'red',
      title: '修改建议读取失败',
      text: r.error.message || String(r.error),
      actions: [button('重试读取', { onClick: () => loadProposal() })],
    }));
    return;
  }
  if (!r.artifact) {
    els.proposal.appendChild(notice({
      tone: 'blue',
      title: '修改建议任务进行中',
      text: '任务结束后会展示逐条 diff；提案不会自动改写文档。',
    }));
    return;
  }
  els.proposal.appendChild(RevisionDiff({
    artifact: r.artifact,
    validation: r.validation,
    markdown: r.markdown,
    applyState: r.applyState,
    applyError: r.applyError,
    conflict: r.conflict,
    applyResult: r.applyResult,
    onApply: handleApply,
    onRediagnose: () => { startReview(); },
    onDownload: (artifact) => downloadResult(artifact.id),
  }));
}

function syncExport() {
  if (!els.exportBox) return;
  els.exportBox.replaceChildren();
  const versionId = currentVersionId();
  const doc = selectedDoc();
  const format = els.exportFormat?.value || 'md';
  const exportGate = gate([format === 'docx' ? 'export.docx' : 'export.md']);
  const can = Boolean(s.project && versionId) && exportGate.ok;

  els.exportBtn.disabled = !can || s.exporting;
  els.exportBtn.textContent = s.exporting ? '导出中…' : '生成导出成果';
  els.exportBtn.title = !versionId
    ? '需要先选择文档'
    : !exportGate.ok ? gateText(exportGate) : 'POST /exports（md/docx，generic）';

  if (!versionId) {
    els.exportBox.appendChild(notice({
      tone: 'gray',
      title: '尚无可导出的文档版本',
      text: '请先选择文档；应用修改提案后可使用新版本导出。',
    }));
  } else if (!exportGate.ok) {
    els.exportBox.appendChild(notice({
      tone: 'red',
      title: `${format === 'docx' ? 'Word' : 'Markdown'} 导出当前不可用`,
      text: `${gateText(exportGate)}。按钮已禁用，不会静默降级成其它格式。`,
    }));
  } else {
    els.exportBox.appendChild(notice({
      tone: 'gray',
      title: '导出来源',
      text: `项目 ${shortId(s.project.id, 12)} · 文档 ${shortId(doc?.filename || '', 20)} · 版本 ${shortId(versionId, 14)}。仅支持 md / docx 与通用学术格式（generic），其它期刊格式后端返回 422。`,
    }));
  }

  if (s.exportError) {
    els.exportBox.appendChild(notice({
      tone: 'red',
      title: '导出失败',
      text: s.exportError.message || String(s.exportError),
    }));
  }
  if (s.exportResult) {
    const result = createElement('div', { className: 'rw-export-result' });
    result.appendChild(createElement('h3', { className: 'rw-subtitle' }, '导出成果'));
    result.appendChild(createElement(
      'p',
      { className: 'rw-small' },
      `${s.exportResult.filename || 'artifact'} · ${formatBytes(s.exportResult.size_bytes)} · ${s.exportResult.mime || ''} · 校验 ${s.exportResult.validation?.valid === false ? '未通过' : '通过'}`
    ));
    const row = createElement('div', { className: 'rw-row' });
    const dl = button('下载文件', {
      tone: 'primary',
      onClick: () => downloadResult(s.exportResult.id),
    });
    dl.insertBefore(createElement('span', { className: 'rw-icon', innerHTML: iconDownload(14) }), dl.firstChild);
    row.appendChild(dl);
    row.appendChild(createElement('span', { className: 'rw-hint' }, `下载地址：${s.exportResult.download_url || `/api/v1/research/artifacts/${s.exportResult.id}/download`}（请求会带 Bearer Token）`));
    result.appendChild(row);
    els.exportBox.appendChild(result);
  }
}

function sync() {
  if (!els.root) return;
  renderHeader();
  renderStepper();
  renderScope();
  renderDiagnosis();
  syncExport();
  syncChart();
  // 顶层状态：未登录 / 加载 / 错误 覆盖整个工作区
  const showMain = s.status === 'ready';
  els.workspace.hidden = !showMain;
  els.stateLayer.replaceChildren();
  els.stateLayer.hidden = showMain;
  if (s.status === 'loading') {
    els.stateLayer.appendChild(LoadingState());
  } else if (s.status === 'unauthorized') {
    els.stateLayer.appendChild(UnauthorizedState({ onLogin: () => navigateTo('auth') }));
  } else if (s.status === 'error') {
    els.stateLayer.appendChild(ErrorState({
      error: s.error,
      onRetry: () => bootstrap(),
    }));
  }
  if (showMain && !s.project) {
    els.emptyHint.hidden = false;
    els.mainCards.hidden = true;
  } else if (showMain) {
    els.emptyHint.hidden = true;
    els.mainCards.hidden = false;
  }
}

// ── 图表（T22）：只读当前版本里的第一张数值表，列名由用户确认 ──────────
function _tableCells(line) {
  return line
    .replace(/^\s*\|/, '')
    .replace(/\|\s*$/, '')
    .split('|')
    .map((cell) => cell.trim().replace(/\\\|/g, '|'));
}

function _isSeparatorRow(line) {
  return /^\|(\s*:?-{2,}:?\s*\|)+$/.test(line.trim());
}

// 文档里可能有多张表（含分类表/文字表），逐表解析并标记"是否全数值"，
// 默认选第一张全数值表：分类表交给后端只会 422 CHART_NON_NUMERIC。
function _parseTables(blocks) {
  const tables = [];
  let current = null;
  (blocks || []).forEach((block) => {
    String(block?.text || '').split('\n').forEach((raw) => {
      const line = raw.trim();
      if (!line.startsWith('|')) {
        current = null;
        return;
      }
      if (_isSeparatorRow(line)) return;
      const cells = _tableCells(line);
      if (cells.length < 2) {
        current = null;
        return;
      }
      if (!current) {
        current = { header: cells, rows: [] };
        tables.push(current);
        return;
      }
      current.rows.push(cells);
    });
  });
  return tables.map((table, index) => {
    const numeric =
      table.rows.length > 0 &&
      table.rows.every((row) =>
        row.every((cell) => cell === '' || Number.isFinite(Number(cell)))
      );
    return { index, columns: table.header, numeric, rows: table.rows.length };
  });
}

function _tableStats(blocks) {
  const options = _parseTables(blocks);
  return { columns: [], tables: options.length, options };
}

// 切换表格时同步列名与默认列映射（保留用户已选的具体列则不动）。
function applyChartTable(table) {
  if (!table) return;
  s.chart.tableIndex = table.index;
  s.chart.values.tableIndex = table.index;
  s.chart.columns = table.columns;
  const columns = table.columns || [];
  if (columns.length) {
    const x = columns[0];
    const y = columns.slice(1, 3).join(',');
    s.chart.values.xColumn = x;
    s.chart.values.yColumns = y;
  }
}

async function ensureChartTable(force = false) {
  const versionId = currentVersionId();
  const doc = selectedDoc();
  if (!doc || !versionId) {
    s.chart.columns = [];
    s.chart.tableCount = 0;
    s.chart.tableVersionId = null;
    return;
  }
  if (!force && s.chart.tableVersionId === versionId) return;
  s.chart.tableVersionId = versionId;
  s.chart.tableLoading = true;
  s.chart.tableError = null;
  try {
    // 端点 limit 上限 100（_MAX_LIMIT）；表格可能在较后位置，最多翻 3 页找表。
    let items = [];
    let cursor = null;
    for (let page = 0; page < 3; page += 1) {
      const res = await getDocumentBlocks(doc.id, { version_id: versionId, limit: 100, cursor });
      items = items.concat(res?.items || []);
      if (_tableStats(items).tables > 0) break;
      cursor = res?.next_cursor || null;
      if (!cursor) break;
    }
    const { tables, options } = _tableStats(items);
    s.chart.tableOptions = options;
    s.chart.tableCount = tables;
    const preferred = options.find((item) => item.numeric) || options[0] || null;
    if (preferred) {
      applyChartTable(preferred);
    } else {
      s.chart.columns = [];
      s.chart.values.tableIndex = 0;
      s.chart.values.xColumn = '';
      s.chart.values.yColumns = '';
    }
  } catch (err) {
    s.chart.tableError = err?.message || '读取文档块失败';
  } finally {
    s.chart.tableLoading = false;
    syncChart();
  }
}

function renderChartImpl() {
  if (!els.chart) return;
  if (s.project && currentVersionId()) {
    ensureChartTable();
  }
  const gateResult = gate(['chart_generation']);
  let disabledReason = '';
  if (!gateResult.ok) {
    disabledReason = gateText(gateResult) || '图表能力当前不可用。';
  } else if (!s.project) {
    disabledReason = '先打开一个项目。';
  } else if (!currentVersionId()) {
    disabledReason = '先上传并选定一个文档版本。';
  } else if (s.chart.tableLoading) {
    disabledReason = '正在读取文档中的表格…';
  } else if (s.chart.tableError) {
    disabledReason = s.chart.tableError;
  }
  // 任务事件会频繁触发 sync()；签名未变时不重建面板，避免输入焦点被抢走。
  const signature = [
    s.project?.id || '',
    currentVersionId() || '',
    disabledReason,
    s.chart.columns.join(','),
    s.chart.tableCount,
    s.chart.loading ? '1' : '0',
    s.chart.error || '',
    s.chart.result?.artifactId || '',
    s.chart.values.tableIndex,
    s.chart.values.chartType,
    s.chart.values.xColumn,
    s.chart.values.yColumns,
    s.chart.values.title,
  ].join('|');
  if (signature === chartSignature && els.chart.childElementCount) return;
  chartSignature = signature;
  els.chart.replaceChildren(
    ChartPanel({
      columns: s.chart.columns,
      tables: s.chart.tableOptions,
      tableCount: s.chart.tableCount,
      disabledReason,
      values: s.chart.values,
      result: s.chart.result,
      error: s.chart.error || '',
      loading: s.chart.loading,
      onChange: (patch) => {
        if (patch.tableIndex !== undefined) {
          const table = (s.chart.tableOptions || []).find(
            (item) => item.index === Number(patch.tableIndex)
          );
          if (table) applyChartTable(table);
          s.chart.result = null;
          syncChart();
          return;
        }
        s.chart.values = { ...s.chart.values, ...patch };
        if (patch.chartType) s.chart.result = null;
      },
      onGenerate: () => handleChart(),
    })
  );
}

function syncChart() {
  try {
    renderChartImpl();
  } catch (err) {
    // 图表面板渲染失败不得拖垮整个工作区（其余步骤照常可用）
    console.error('chart panel render failed', err);
  }
}

async function handleChart() {
  const versionId = currentVersionId();
  if (!s.project || !versionId) return;
  const values = s.chart.values;
  const yColumns = String(values.yColumns || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 8);
  if (!values.xColumn || !yColumns.length) {
    s.chart.error = '请先填写横轴与至少一个纵轴列名。';
    syncChart();
    return;
  }
  s.chart.loading = true;
  s.chart.error = null;
  syncChart();
  try {
    const artifact = await createChart({
      project_id: s.project.id,
      document_version_id: versionId,
      chart_type: values.chartType,
      x_column: values.xColumn,
      y_columns: yColumns,
      title: values.title ? values.title : null,
      table_index: Number(values.tableIndex || 0),
    });
    const { blob, filename } = await fetchArtifactBlob(artifact.id);
    if (s.chart.blobUrl) URL.revokeObjectURL(s.chart.blobUrl);
    const blobUrl = URL.createObjectURL(blob);
    s.chart.blobUrl = blobUrl;
    s.chart.result = {
      artifactId: artifact.id,
      validation: artifact.validation || {},
      filename,
      bytes: blob.size,
      blobUrl,
    };
  } catch (err) {
    s.chart.error = err?.message || '图表生成失败';
    s.chart.result = null;
  } finally {
    s.chart.loading = false;
    syncChart();
  }
}


// ── 启动与恢复 ───────────────────────────────────────────────
async function restore(saved) {
  if (!saved) return;
  if (Array.isArray(saved.dimensions) && saved.dimensions.length) {
    s.dimensions = new Set(saved.dimensions.filter((item) => DIMENSIONS.includes(item)));
  }
  if (saved.mode === 'pro' || saved.mode === 'flash') s.mode = saved.mode;
  if (typeof saved.objective === 'string') {
    s.objective = saved.objective;
    if (els.objective) els.objective.value = saved.objective;
  }
  if (saved.projectId) {
    await selectProject(saved.projectId);
    if (saved.documentId && s.documents.some((doc) => doc.id === saved.documentId)) {
      s.selectedDocumentId = saved.documentId;
      renderDocs();
    }
  }
  if (saved.reviewTaskId) {
    s.review.taskId = saved.reviewTaskId;
    s.streamSeq = null;
    try {
      const snapshot = await getTask(saved.reviewTaskId);
      s.review.task = snapshot;
      if (isTerminal(snapshot.status)) {
        await loadFindings();
        if (Array.isArray(saved.selectedFindingIds)) {
          s.selectedFindingIds = new Set(saved.selectedFindingIds);
        }
      } else {
        s.activeTaskId = saved.reviewTaskId;
        taskStream?.setTask(snapshot);
        runStream(saved.reviewTaskId);
      }
    } catch (err) {
      s.review.error = err;
    }
  }
  if (saved.revisionTaskId) {
    s.revision.taskId = saved.revisionTaskId;
    try {
      const snapshot = await getTask(saved.revisionTaskId);
      s.revision.task = snapshot;
      if (isTerminal(snapshot.status)) await loadProposal();
      else if (!s.activeTaskId) {
        s.activeTaskId = saved.revisionTaskId;
        s.streamSeq = null;
        taskStream?.setTask(snapshot);
        runStream(saved.revisionTaskId);
      }
    } catch (err) {
      s.revision.error = err;
    }
  }
  renderFindings();
  renderProposal();
  renderDocs();
  sync();
}

async function bootstrap() {
  if (!state.auth?.isAuthenticated && !localStorage.getItem('sm_token')) {
    s.status = 'unauthorized';
    sync();
    return;
  }
  s.status = 'loading';
  s.error = null;
  sync();
  await loadCapabilities();
  if (s.status !== 'loading' && s.status !== 'ready') return;
  await loadProjects();
  if (s.status === 'unauthorized' || s.status === 'error') return;
  s.status = 'ready';
  sync();
  await restore(loadSaved());
}

export function ResearchWorkspace() {
  injectStyles();
  styleInjected = true;

  Object.assign(s, {
    status: 'loading',
    error: null,
    capabilities: [],
    capLoading: true,
    capError: null,
    capIndex: new Map(),
    projects: [],
    projectsLoading: true,
    projectsError: null,
    creating: false,
    project: null,
    documents: [],
    selectedDocumentId: null,
    uploading: false,
    uploadError: null,
    review: { taskId: null, task: null, findings: [], loading: false, error: null },
    revision: {
      taskId: null, task: null, artifact: null, validation: null, markdown: '',
      loading: false, error: null, applyState: 'idle', applyError: null, conflict: false, applyResult: null,
    },
    activeTaskId: null,
    streamSeq: null,
    selectedFindingIds: new Set(),
    exporting: false,
    exportError: null,
    exportResult: null,
  });

  const page = createElement('div', { className: 'page active page-research-workspace' });

  // 顶部
  const header = createElement('div', { className: 'rw-header' });
  const headerLeft = createElement('div', { className: 'rw-header-left' });
  const backBtn = createElement('button', {
    className: 'btn btn-ghost btn-sm rw-btn',
    'aria-label': '返回上一页',
  });
  backBtn.innerHTML = iconArrowLeft(16) + '<span>返回</span>';
  backBtn.addEventListener('click', () => {
    if (state.readiness) navigateTo('readiness');
    else if (state.discipline) navigateTo(state.discipline);
    else navigateTo('homepage');
  });
  headerLeft.appendChild(backBtn);
  const titleWrap = createElement('div', { className: 'rw-title-wrap' });
  titleWrap.appendChild(createElement('h1', { className: 'rw-title' }, '研究工作区'));
  titleWrap.appendChild(createElement(
    'p',
    { className: 'rw-subtitle-text' },
    '上传 → 确认范围 → 全文诊断 → 问题与依据 → 选择目标 → 采纳修改 → 导出。任务在服务端执行，页面异常不会取消任务。'
  ));
  headerLeft.appendChild(titleWrap);
  header.appendChild(headerLeft);

  const headerRight = createElement('div', { className: 'rw-header-right' });
  const pills = createElement('div', { className: 'rw-row' });
  headerRight.appendChild(pills);
  const refreshAll = button('刷新', { onClick: () => bootstrap() });
  refreshAll.insertBefore(createElement('span', { className: 'rw-icon', innerHTML: iconRefresh(14) }), refreshAll.firstChild);
  headerRight.appendChild(refreshAll);
  headerRight.appendChild(button('新建项目', {
    onClick: () => {
      const input = page.querySelector('.rw-create-form .rw-input');
      if (input) input.focus();
    },
    title: '聚焦左侧新建项目输入框',
  }));
  header.appendChild(headerRight);
  page.appendChild(header);

  // 状态层
  const stateLayer = createElement('div', { className: 'rw-state-layer' });
  page.appendChild(stateLayer);

  // 工作区
  const workspace = createElement('div', { className: 'rw-workspace' });
  const layout = createElement('div', { className: 'rw-layout' });

  const side = createElement('aside', { className: 'rw-side' });
  const projectsWrap = createElement('div');
  const capabilitiesWrap = createElement('div');
  side.appendChild(projectsWrap);
  side.appendChild(capabilitiesWrap);

  const main = createElement('div', { className: 'rw-main' });
  const stepper = createElement('div', { className: 'rw-stepper', 'aria-label': '流程进度' });
  main.appendChild(stepper);

  const emptyHint = createElement('div', { className: 'rw-card' });
  emptyHint.appendChild(createElement('div', { className: 'rw-card-body' }));
  emptyHint.firstChild.appendChild(notice({
    tone: 'blue',
    title: '先选择一个研究项目',
    text: '左侧没有项目时先新建。项目用于隔离文档、诊断任务与导出成果；页面不会在看空列表时伪造示例数据。',
  }));
  main.appendChild(emptyHint);

  const mainCards = createElement('div', { className: 'rw-main' });

  // 文档卡
  const docsWrap = createElement('div');
  mainCards.appendChild(docsWrap);

  // 范围卡
  const scopeCard = createElement('section', { className: 'rw-card' });
  const scopeHead = createElement('div', { className: 'rw-card-head' });
  const scopeHeadLeft = createElement('div');
  scopeHeadLeft.appendChild(createElement('h2', { className: 'rw-card-title' }, '确认诊断范围'));
  scopeHeadLeft.appendChild(createElement('p', { className: 'rw-card-sub' }, '诊断只在你确认的维度与目标内进行；不选择内部角色，任务由服务端编排。'));
  scopeHead.appendChild(scopeHeadLeft);
  scopeCard.appendChild(scopeHead);
  const scopeBody = createElement('div', { className: 'rw-card-body' });

  const objectiveLabel = createElement('label', { className: 'rw-field' });
  objectiveLabel.appendChild(createElement('span', { className: 'rw-label' }, '诊断目标（1–4000 字，必填）'));
  const objective = createElement('textarea', {
    className: 'rw-textarea',
    maxlength: '4000',
    placeholder: '例如：检查第二章的论证链条与证据引用是否支撑结论，重点看方法与数据口径。',
    'aria-label': '诊断目标',
  });
  objective.value = s.objective;
  objective.addEventListener('input', () => {
    s.objective = objective.value;
    saveState();
    renderScope();
  });
  objectiveLabel.appendChild(objective);
  objectiveLabel.appendChild(createElement('span', { className: 'rw-hint' }, '目标会作为任务的 objective 字段提交；过短的目标会降低诊断质量。'));
  scopeBody.appendChild(objectiveLabel);

  scopeBody.appendChild(createElement('span', { className: 'rw-label' }, '诊断维度（至少一项）'));
  const dims = createElement('div', { className: 'rw-scope-dims' });
  DIMENSIONS.forEach((key) => {
    const label = createElement('label', { className: 'rw-dim' });
    const input = createElement('input', { type: 'checkbox', className: 'rw-check' });
    input.checked = s.dimensions.has(key);
    input.addEventListener('change', () => {
      if (input.checked) s.dimensions.add(key);
      else s.dimensions.delete(key);
      saveState();
      renderScope();
    });
    label.appendChild(input);
    label.appendChild(createElement('span', {}, dimensionLabel(key)));
    dims.appendChild(label);
  });
  scopeBody.appendChild(dims);

  const modeField = createElement('label', { className: 'rw-field' });
  modeField.appendChild(createElement('span', { className: 'rw-label' }, '执行模式'));
  const modeSelect = createElement('select', { className: 'rw-select', 'aria-label': '执行模式' });
  const modeFlash = createElement('option', { value: 'flash' }, 'flash（更快，覆盖更浅）');
  const modePro = createElement('option', { value: 'pro' }, 'pro（更充分，耗时更长）');
  modeSelect.appendChild(modeFlash);
  modeSelect.appendChild(modePro);
  modeSelect.value = s.mode;
  modeSelect.addEventListener('change', () => {
    s.mode = modeSelect.value;
    saveState();
    renderScope();
  });
  modeField.appendChild(modeSelect);
  modeField.appendChild(createElement('span', { className: 'rw-hint' }, '模式只影响服务端编排深度；费用与耗时由服务端决定。'));
  scopeBody.appendChild(modeField);

  const scopeMeta = createElement('div', { className: 'rw-row' });
  scopeBody.appendChild(scopeMeta);

  const scopeGate = createElement('div', { className: 'rw-scope-note' });
  scopeBody.appendChild(scopeGate);

  const scopeActions = createElement('div', { className: 'rw-actions' });
  const startReviewBtn = button('开始全文诊断', { tone: 'primary', onClick: () => startReview() });
  scopeActions.appendChild(startReviewBtn);
  scopeActions.appendChild(createElement(
    'span',
    { className: 'rw-hint' },
    '创建 review 任务后立即订阅 SSE；点击「断开本地流」不会取消任务。'
  ));
  scopeBody.appendChild(scopeActions);
  scopeCard.appendChild(scopeBody);
  mainCards.appendChild(scopeCard);

  // 任务流卡（工厂实例）
  const stream = TaskStream({
    onReconnect: () => {
      const taskId = s.review.taskId && !isTerminal(s.review.task?.status) ? s.review.taskId : s.activeTaskId;
      if (!taskId) return;
      runStream(taskId);
    },
    onCancel: () => handleCancel(),
    onRetry: () => handleRetry(),
    onResume: (_task, note) => handleResume(note),
    onDisconnect: () => stopStream(),
  });
  taskStream = stream;
  mainCards.appendChild(stream.el);

  // 诊断结论卡
  const diagnosisWrap = createElement('div');
  mainCards.appendChild(diagnosisWrap);

  // 问题与依据
  const findingsCard = createElement('section', { className: 'rw-card' });
  const findingsHead = createElement('div', { className: 'rw-card-head' });
  const findingsHeadLeft = createElement('div');
  findingsHeadLeft.appendChild(createElement('h2', { className: 'rw-card-title' }, '问题与依据'));
  findingsHeadLeft.appendChild(createElement('p', { className: 'rw-card-sub' }, '每个诊断项包含严重度、定位、理由、建议与依据引用；勾选后可作为修改目标。'));
  findingsHead.appendChild(findingsHeadLeft);
  findingsCard.appendChild(findingsHead);
  const findingsBody = createElement('div', { className: 'rw-card-body' });
  findingsCard.appendChild(findingsBody);
  mainCards.appendChild(findingsCard);

  // 修改建议
  const proposalWrap = createElement('div');
  mainCards.appendChild(proposalWrap);

  // 导出
  const exportCard = createElement('section', { className: 'rw-card' });
  const exportHead = createElement('div', { className: 'rw-card-head' });
  const exportHeadLeft = createElement('div');
  exportHeadLeft.appendChild(createElement('h2', { className: 'rw-card-title' }, '导出'));
  exportHeadLeft.appendChild(createElement('p', { className: 'rw-card-sub' }, 'POST /exports 生成成果，再带鉴权下载；未支持的格式会如实报错。'));
  exportHead.appendChild(exportHeadLeft);
  exportCard.appendChild(exportHead);
  const exportBody = createElement('div', { className: 'rw-card-body' });
  const exportControls = createElement('div', { className: 'rw-scope-grid' });

  const fmtField = createElement('label', { className: 'rw-field' });
  fmtField.appendChild(createElement('span', { className: 'rw-label' }, '格式'));
  const exportFormat = createElement('select', { className: 'rw-select', 'aria-label': '导出格式' });
  exportFormat.appendChild(createElement('option', { value: 'md' }, 'Markdown（.md）'));
  exportFormat.appendChild(createElement('option', { value: 'docx' }, 'Word（.docx）'));
  exportFormat.addEventListener('change', () => syncExport());
  fmtField.appendChild(exportFormat);
  exportControls.appendChild(fmtField);

  const styleField = createElement('label', { className: 'rw-field' });
  styleField.appendChild(createElement('span', { className: 'rw-label' }, '期刊格式'));
  const styleSelect = createElement('select', { className: 'rw-select', disabled: 'disabled', 'aria-label': '期刊格式' });
  styleSelect.appendChild(createElement('option', { value: 'generic' }, '通用学术格式（generic）'));
  styleField.appendChild(styleSelect);
  styleField.appendChild(createElement('span', { className: 'rw-hint' }, '当前只支持 generic；其它格式后端会返回 422 UNSUPPORTED_JOURNAL_STYLE。'));
  exportControls.appendChild(styleField);

  exportBody.appendChild(exportControls);

  const includeReportLabel = createElement('label', { className: 'rw-dim' });
  const exportIncludeReport = createElement('input', { type: 'checkbox', className: 'rw-check' });
  exportIncludeReport.checked = true;
  includeReportLabel.appendChild(exportIncludeReport);
  includeReportLabel.appendChild(createElement('span', {}, '附带诊断报告'));
  exportBody.appendChild(includeReportLabel);

  const includeChangeLogLabel = createElement('label', { className: 'rw-dim' });
  const exportIncludeChangeLog = createElement('input', { type: 'checkbox', className: 'rw-check' });
  includeChangeLogLabel.appendChild(exportIncludeChangeLog);
  includeChangeLogLabel.appendChild(createElement('span', {}, '附带变更记录（如有）'));
  exportBody.appendChild(includeChangeLogLabel);

  const exportActions = createElement('div', { className: 'rw-actions' });
  const exportBtn = button('生成导出成果', { tone: 'primary', onClick: () => handleExport() });
  exportActions.appendChild(exportBtn);
  exportActions.appendChild(createElement('span', { className: 'rw-hint' }, '导出不会修改文档；重复导出会带新的 Idempotency-Key。'));
  exportBody.appendChild(exportActions);

  const exportBox = createElement('div');
  exportBody.appendChild(exportBox);
  exportCard.appendChild(exportBody);
  mainCards.appendChild(exportCard);


  // 图表（T22）：只对当前版本的数值表出图；能力关闭时只解释原因，不出占位图
  const chartWrap = createElement('div');
  mainCards.appendChild(chartWrap);
  main.appendChild(mainCards);
  layout.appendChild(side);
  layout.appendChild(main);
  workspace.appendChild(layout);
  page.appendChild(workspace);

  els = {
    root: page,
    headerPills: pills,
    stateLayer,
    workspace,
    stepper,
    emptyHint,
    mainCards,
    projects: projectsWrap,
    capabilities: capabilitiesWrap,
    docs: docsWrap,
    diagnosis: diagnosisWrap,
    scopeGate,
    scopeMeta,
    startReviewBtn,
    findings: findingsBody,
    proposal: proposalWrap,
    chart: chartWrap,
    exportBox,
    exportBtn,
    exportFormat,
    exportIncludeReport,
    exportIncludeChangeLog,
    objective,
  };

  renderProjects();
  renderCapabilities();
  renderDocs();
  renderFindings();
  renderProposal();
  renderStepper();
  renderScope();
  syncExport();
  syncChart();
  sync();

  // 首次渲染后再拉数据（构建期不发生任何网络请求）
  Promise.resolve().then(() => bootstrap());

  page._cleanup = () => {
    stopStream({ silent: true });    if (s.chart.blobUrl) URL.revokeObjectURL(s.chart.blobUrl);
    s.chart.blobUrl = null;

    if (s.reconnectTimer) clearTimeout(s.reconnectTimer);
    s.reconnectTimer = null;
    taskStream = null;
    els = {};
  };

  return page;
}
