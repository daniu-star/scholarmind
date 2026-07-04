// ========== ScholarMind 图标库 (浏览器版, 从 src/frontend/src/utils/icons.js 同步) ==========
// ========== SVG 图标库 (Lucide 风格, stroke-width 1.5) ==========
// 所有图标返回 SVG 字符串，可通过 innerHTML 注入

function svg(paths, size = 20, opts = {}) {
  const stroke = opts.stroke || 'currentColor';
  const fill = opts.fill || 'none';
  const sw = opts.strokeWidth || '1.5';
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
}

// ========== Agent 图标 ==========
const iconMicroscope = (s = 20) => svg(`<path d="M6 18h8"/><path d="M3 22h18"/><path d="M14 22a7 7 0 1 0 0-14h-1"/><path d="M9 14h2"/><path d="M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z"/><path d="M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3"/>`, s);

const iconClipboardCheck = (s = 20) => svg(`<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>`, s);

const iconBuilding = (s = 20) => svg(`<rect width="16" height="20" x="4" y="2" rx="2" ry="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/><path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/><path d="M8 14h.01"/>`, s);

const iconLibrary = (s = 20) => svg(`<path d="m16 6 4 14"/><path d="M12 6v14"/><path d="M8 8v12"/><path d="M4 4v16"/>`, s);

const iconSparkles = (s = 20) => svg(`<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .962 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.962 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/>`, s);

// ========== 学科图标 ==========
const iconGear = (s = 20) => svg(`<path d="M14.7 6.3a1 1 0 0 0 .26 1.5l1.27.74a1 1 0 0 1-.5 1.87l-1.47.06a1 1 0 0 0-.95.7l-.45 1.4a1 1 0 0 1-1.9 0l-.45-1.4a1 1 0 0 0-.95-.7l-1.47-.06a1 1 0 0 1-.5-1.87l1.27-.74a1 1 0 0 0 .26-1.5L8.4 5.3a1 1 0 0 1 1.4-1.4l1 1.06a1 1 0 0 0 1.4 0l1-1.06a1 1 0 0 1 1.4 1.4Z"/><circle cx="12" cy="14" r="3"/>`, s);

const iconFlask = (s = 20) => svg(`<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>`, s);

const iconBookOpen = (s = 20) => svg(`<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>`, s);

// ========== 通用操作图标 ==========
const iconSearch = (s = 20) => svg(`<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>`, s);

const iconBook = (s = 20) => svg(`<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>`, s);

const iconEdit = (s = 20) => svg(`<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/>`, s);

const iconChart = (s = 20) => svg(`<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>`, s);

const iconLightbulb = (s = 20) => svg(`<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/>`, s);

const iconLink = (s = 20) => svg(`<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>`, s);

const iconPen = (s = 20) => svg(`<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>`, s);

const iconAbc = (s = 20) => svg(`<path d="M2.5 16a2.5 2.5 0 0 1 2.5-2.5h2a2.5 2.5 0 0 1 0 5h-2A2.5 2.5 0 0 1 2.5 16Zm0 0a2.5 2.5 0 0 0-2.5 0"/><path d="M14 16a2.5 2.5 0 0 1 2.5-2.5h2a2.5 2.5 0 0 1 0 5h-2A2.5 2.5 0 0 1 14 16Zm0 0a2.5 2.5 0 0 0-2.5 0"/><path d="M9 7a2.5 2.5 0 0 1 2.5-2.5h2a2.5 2.5 0 0 1 0 5h-2A2.5 2.5 0 0 1 9 7Zm0 0a2.5 2.5 0 0 0-2.5 0"/>`, s);

const iconRefresh = (s = 20) => svg(`<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>`, s);

const iconChat = (s = 20) => svg(`<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>`, s);

const iconDoc = (s = 20) => svg(`<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>`, s);

// ========== UI 控件图标 ==========
const iconSend = (s = 20) => svg(`<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>`, s);

const iconArrowLeft = (s = 20) => svg(`<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>`, s);

const iconClose = (s = 20) => svg(`<path d="M18 6 6 18"/><path d="m6 6 12 12"/>`, s);

const iconCheck = (s = 20) => svg(`<path d="M20 6 9 17l-5-5"/>`, s);

const iconAlert = (s = 20) => svg(`<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>`, s);

const iconInfo = (s = 20) => svg(`<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>`, s);

const iconCopy = (s = 20) => svg(`<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>`, s);

const iconSettings = (s = 20) => svg(`<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>`, s);

const iconHome = (s = 20) => svg(`<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>`, s);

const iconGraduationCap = (s = 20) => svg(`<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>`, s);

const iconUpload = (s = 20) => svg(`<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>`, s);

// ========== 研究类型图标 ==========
const iconAlgorithm = (s = 20) => svg(`<path d="M3 3h7v7H3z"/><path d="M14 3h7v7h-7z"/><path d="M14 14h7v7h-7z"/><path d="M3 14h7v7H3z"/><path d="M10 6.5h4"/><path d="M10 17.5h4"/><path d="M6.5 10v4"/><path d="M17.5 10v4"/>`, s);

const iconSystem = (s = 20) => svg(`<rect width="8" height="8" x="2" y="2" rx="1"/><rect width="8" height="8" x="14" y="2" rx="1"/><rect width="8" height="8" x="2" y="14" rx="1"/><rect width="8" height="8" x="14" y="14" rx="1"/><path d="M10 6h4"/><path d="M10 18h4"/><path d="M6 10v4"/><path d="M18 10v4"/>`, s);

const iconExperiment = (s = 20) => svg(`<path d="M9 3h6"/><path d="M10 3v6.527a2 2 0 0 1-.211.896L5.72 19.55a1 1 0 0 0 .9 1.45h10.76a1 1 0 0 0 .9-1.45l-4.069-9.127A2 2 0 0 1 14 9.527V3"/><path d="M8 14h8"/>`, s);

const iconApplication = (s = 20) => svg(`<rect width="7" height="7" x="2" y="2" rx="1"/><rect width="7" height="7" x="15" y="2" rx="1"/><rect width="7" height="7" x="2" y="15" rx="1"/><path d="M15 15h7v7h-7z"/><path d="M9 5.5h6"/><path d="M5.5 9v6"/><path d="M18.5 9v6"/><path d="M9 18.5h6"/>`, s);

const iconTheoretical = (s = 20) => svg(`<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>`, s);

const iconSimulation = (s = 20) => svg(`<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="M15 3v18"/><path d="M3 9h18"/><path d="M3 15h18"/>`, s);

const iconObservational = (s = 20) => svg(`<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>`, s);

const iconQualitative = (s = 20) => svg(`<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 10h.01"/><path d="M12 10h.01"/><path d="M16 10h.01"/>`, s);

const iconQuantitative = (s = 20) => svg(`<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>`, s);

const iconHistorical = (s = 20) => svg(`<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="m19 9-5 5-4-4-3 3"/>`, s);

const iconCritical = (s = 20) => svg(`<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/><path d="M12 8v8"/>`, s);

// ========== UI 增强图标 ==========
const iconSun = (s = 20) => svg(`<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>`, s);

const iconMoon = (s = 20) => svg(`<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>`, s);

const iconHelp = (s = 20) => svg(`<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>`, s);

const iconChevronRight = (s = 20) => svg(`<path d="m9 18 6-6-6-6"/>`, s);

const iconExternalLink = (s = 20) => svg(`<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>`, s);

// ========== 认证/用户图标 ==========
const iconUser = (s = 20) => svg(`<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>`, s);

const iconLogIn = (s = 20) => svg(`<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>`, s);

const iconLogOut = (s = 20) => svg(`<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>`, s);

const iconCrown = (s = 20) => svg(`<path d="m2 4 3 12h14l3-12-6 7-4-7-4 7-6-7zm3 16h14"/>`, s);

// ========== ComputationalPage 扩展图标 ==========
const iconDownload = (s = 20) => svg(`<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>`, s);

const iconLightning = (s = 20) => svg(`<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>`, s);

const iconStar = (s = 20) => svg(`<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>`, s);

const iconPlay = (s = 20) => svg(`<polygon points="6 3 20 12 6 21 6 3"/>`, s);

const iconPackage = (s = 20) => svg(`<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>`, s);

const iconTrash = (s = 20) => svg(`<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>`, s);

const iconClock = (s = 20) => svg(`<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>`, s);

const iconCode = (s = 20) => svg(`<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>`, s);

const iconNewspaper = (s = 20) => svg(`<path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/>`, s);

const iconPenTool = (s = 20) => svg(`<path d="m12 19 7-7 3 3-7 7-3-3z"/><path d="m18 13-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"/><path d="m2 2 7.586 7.586"/><circle cx="11" cy="11" r="2"/>`, s);

// ========== 图标映射表 (供 constants.js 使用) ==========
const AGENT_ICONS = {
  researcher: iconMicroscope,
  reviewer: iconClipboardCheck,
  architect: iconBuilding,
  synthesizer: iconLibrary,
  polisher: iconSparkles,
  custom: iconChat,
};

const DISCIPLINE_ICONS = {
  engineering: iconGear,
  science: iconFlask,
  humanities: iconBookOpen,
  interdisciplinary: iconLink,
};

// 研究类型图标映射
const RESEARCH_TYPE_ICONS = {
  algorithm: iconAlgorithm,
  system: iconSystem,
  experiment: iconExperiment,
  application: iconApplication,
  theoretical: iconTheoretical,
  simulation: iconSimulation,
  observational: iconObservational,
  qualitative: iconQualitative,
  quantitative: iconQuantitative,
  historical: iconHistorical,
  critical: iconCritical,
};

// UI 增强图标映射
const UI_EXTRA_ICONS = {
  sun: iconSun,
  moon: iconMoon,
  help: iconHelp,
  'chevron-right': iconChevronRight,
  'external-link': iconExternalLink,
};

// 建议卡片图标映射
const SUGGESTION_ICONS = {
  search: iconSearch,
  book: iconBook,
  edit: iconEdit,
  clipboard: iconClipboardCheck,
  chart: iconChart,
  lightbulb: iconLightbulb,
  building: iconBuilding,
  link: iconLink,
  pen: iconPen,
  library: iconLibrary,
  microscope: iconMicroscope,
  sparkles: iconSparkles,
  abc: iconAbc,
  chat: iconChat,
  doc: iconDoc,
  'graduation-cap': iconGraduationCap,
};

// 通用图标映射 (UI 控件)
const UI_ICONS = {
  send: iconSend,
  'arrow-left': iconArrowLeft,
  close: iconClose,
  check: iconCheck,
  alert: iconAlert,
  info: iconInfo,
  copy: iconCopy,
  settings: iconSettings,
  home: iconHome,
  refresh: iconRefresh,
};

// 按 key 渲染图标的统一入口
function renderIcon(key, size = 20) {
  const fn = SUGGESTION_ICONS[key] || AGENT_ICONS[key] || DISCIPLINE_ICONS[key] || RESEARCH_TYPE_ICONS[key] || UI_EXTRA_ICONS[key] || UI_ICONS[key];
  return fn ? fn(size) : '';
}

// favicon SVG (学士帽)
const FAVICON_SVG = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23B8956A' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'><path d='M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z'/><path d='M22 10v6'/><path d='M6 12.5V16a6 3 0 0 0 12 0v-3.5'/></svg>`;

// ========== 补充图标（emoji 替换专用，Task 6 SubTask 6.2） ==========

// 💊 胶囊（PubMed 医学数据源）
const iconPill = (s = 20) => svg(`<path d="M10.5 20.5a6.5 6.5 0 0 1-7.84-7.84"/><path d="M13.5 3.5a6.5 6.5 0 0 1 7.84 7.84"/><path d="m6.5 17.5 11-11"/>`, s);

// 🎯 靶心（高相关文献分组）
const iconTarget = (s = 20) => svg(`<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>`, s);

// 💎 宝石（Pro 模型）
const iconGem = (s = 20) => svg(`<path d="M6 3h12l4 6-10 13L2 9Z"/><path d="M11 3 8 9l4 13 4-13-3-6"/><path d="M2 9h20"/>`, s);

// 🚀 火箭（启动 Pipeline）
const iconRocket = (s = 20) => svg(`<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>`, s);

// 🎉 派对（Pipeline 全部完成）
const iconPartyPopper = (s = 20) => svg(`<path d="M5.8 11.3 2 22l10.7-3.79"/><path d="M4 3h.01"/><path d="M22 8h.01"/><path d="M15 2h.01"/><path d="M22 20h.01"/><path d="m22 2-2.24.75a2.9 2.9 0 0 0-1.96 3.12c.1.86-.57 1.63-1.45 1.63h-.38c-.86 0-1.6.6-1.76 1.44L14 10"/><path d="m22 13-1.7.3a3 3 0 0 0-2.3 2.3L17.7 17"/><path d="M11 13a5 5 0 0 1-5-5"/><path d="M14 9a5 5 0 0 1 5 5"/>`, s);

// 🧠 大脑（智能研究）
const iconBrain = (s = 20) => svg(`<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/><path d="M17.599 6.5a3 3 0 0 0 .399-1.375"/><path d="M6.003 5.125A3 3 0 0 0 6.401 6.5"/><path d="M3.477 10.896a4 4 0 0 1 .585-.396"/><path d="M19.938 10.5a4 4 0 0 1 .585.396"/><path d="M6 18a4 4 0 0 1-1.967-.516"/><path d="M19.967 17.484A4 4 0 0 1 18 18"/>`, s);

// 🛡️ 盾牌（降低 AIGC 检测率）
const iconShield = (s = 20) => svg(`<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>`, s);

// 📐 直尺（格式规范化）
const iconRuler = (s = 20) => svg(`<path d="M21.3 8.7 8.7 21.3a1 1 0 0 1-1.4 0l-4.6-4.6a1 1 0 0 1 0-1.4L15.3 2.7a1 1 0 0 1 1.4 0l4.6 4.6a1 1 0 0 1 0 1.4Z"/><path d="m7.5 10.5 2 2"/><path d="m10.5 7.5 2 2"/><path d="m13.5 4.5 2 2"/><path d="m4.5 13.5 2 2"/>`, s);

// 📌 图钉（主题对话分类）
const iconPin = (s = 20) => svg(`<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>`, s);

// 🌐 地球（交叉学科/全球）
const iconGlobe = (s = 20) => svg(`<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>`, s);

// ========== 补充图标映射表 ==========

const EXTRA_EMOJI_ICONS = {
  pill: iconPill,
  target: iconTarget,
  gem: iconGem,
  rocket: iconRocket,
  party: iconPartyPopper,
  brain: iconBrain,
  shield: iconShield,
  ruler: iconRuler,
  pin: iconPin,
  globe: iconGlobe,
};

// ========== UMD 全局挂载（供单文件原型 <script src> 引入） ==========
// 当检测到浏览器环境时，将所有图标函数与映射表挂载到 window.IconLib
// 这样内联 onclick 处理器和后续脚本可通过 window.IconLib.renderIcon(key, size) 调用
if (typeof window !== 'undefined') {
  window.IconLib = {
    // 工厂函数
    svg,
    renderIcon,
    // 单个图标函数
    iconMicroscope, iconClipboardCheck, iconBuilding, iconLibrary, iconSparkles, iconChat,
    iconGear, iconFlask, iconBookOpen,
    iconSearch, iconBook, iconEdit, iconChart, iconLightbulb, iconLink, iconPen, iconAbc, iconRefresh, iconDoc,
    iconSend, iconArrowLeft, iconClose, iconCheck, iconAlert, iconInfo, iconCopy, iconSettings, iconHome, iconGraduationCap, iconUpload,
    iconAlgorithm, iconSystem, iconExperiment, iconApplication, iconTheoretical, iconSimulation, iconObservational, iconQualitative, iconQuantitative, iconHistorical, iconCritical,
    iconSun, iconMoon, iconHelp, iconChevronRight, iconExternalLink,
    iconUser, iconLogIn, iconLogOut, iconCrown,
    iconDownload, iconLightning, iconStar, iconPlay, iconPackage, iconTrash, iconClock, iconCode, iconNewspaper, iconPenTool,
    // 补充图标
    iconPill, iconTarget, iconGem, iconRocket, iconPartyPopper, iconBrain, iconShield, iconRuler, iconPin, iconGlobe,
    // 映射表
    AGENT_ICONS, DISCIPLINE_ICONS, RESEARCH_TYPE_ICONS, UI_EXTRA_ICONS, SUGGESTION_ICONS, UI_ICONS, EXTRA_EMOJI_ICONS,
    // 常量
    FAVICON_SVG,
  };

  // 扩展 renderIcon 支持补充图标
  const _origRenderIcon = renderIcon;
  window.IconLib.renderIcon = function(key, size = 20) {
    const fn = EXTRA_EMOJI_ICONS[key] || SUGGESTION_ICONS[key] || AGENT_ICONS[key] || DISCIPLINE_ICONS[key] || RESEARCH_TYPE_ICONS[key] || UI_EXTRA_ICONS[key] || UI_ICONS[key];
    return fn ? fn(size) : '';
  };
}
