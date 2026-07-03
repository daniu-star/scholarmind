import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { DISCIPLINES, APP_VERSION } from '../utils/constants.js';
import { DISCIPLINE_ICONS, iconMicroscope, iconLibrary, iconLink, iconPen, iconChart, iconCode, iconGraduationCap, iconClipboardCheck } from '../utils/icons.js';
import { showPaperWorkbenchDialog } from '../components/PaperWorkbenchDialog.js';

export function HomePage() {
  const page = createElement('div', { className: 'page active page-home' });

  const hero = createElement('div', { className: 'hero-section' },
    createElement('div', { className: 'hero-logo' }, 'SM'),
    createElement('h1', { className: 'hero-title hero-title-display' }, 'ScholarMind'),
    createElement('p', { className: 'hero-subtitle' }, '让学术研究更从容'),
    createElement('p', { className: 'hero-hint' }, '选择学科开始'),
    createElement('p', { className: 'hero-motto' }, '"学问之道，无他，求其放心而已" ——《孟子·告子上》'),
  );
  page.appendChild(hero);

  const cards = createElement('div', { className: 'discipline-cards' });
  DISCIPLINES.forEach(d => {
    const iconFn = DISCIPLINE_ICONS[d.id];
    const iconWrap = createElement('div', { className: 'discipline-icon', 'data-discipline': d.id, innerHTML: iconFn ? iconFn(28) : '' });
    const tagsWrap = createElement('div', { className: 'discipline-card-tags' });
    (d.tags || []).forEach(t => {
      tagsWrap.appendChild(createElement('span', { className: 'discipline-tag' }, t));
    });
    const card = createElement('div', { className: 'discipline-card', 'data-discipline': d.id },
      iconWrap,
      createElement('div', { className: 'discipline-card-title' }, d.name),
      createElement('div', { className: 'discipline-card-desc' }, d.desc),
      tagsWrap,
    );
    card.addEventListener('click', () => {
      state.discipline = d.id;
      navigateTo(d.id);
    });
    cards.appendChild(card);
  });
  page.appendChild(cards);

  // ── 计算社会科学入口卡片（独立强调） ──
  const computationalEntry = createElement('div', { className: 'home-computational-entry' });
  const compCard = createElement('div', { className: 'discipline-card discipline-card-computational', 'data-discipline': 'computational' },
    createElement('div', { className: 'discipline-icon', 'data-discipline': 'computational', innerHTML: iconCode(28) }),
    createElement('div', { className: 'discipline-card-title' }, '计算社会科学'),
    createElement('div', { className: 'discipline-card-desc' }, 'Python 爬虫 · 数据分析 · 可视化 · 机器学习一体化'),
    createElement('div', { className: 'discipline-card-tags' },
      createElement('span', { className: 'discipline-tag' }, '爬虫'),
      createElement('span', { className: 'discipline-tag' }, '统计'),
      createElement('span', { className: 'discipline-tag' }, '可视化'),
      createElement('span', { className: 'discipline-tag' }, 'ML'),
    ),
  );
  compCard.addEventListener('click', () => navigateTo('computational'));
  computationalEntry.appendChild(compCard);
  page.appendChild(computationalEntry);

  // ── 功能特性区域 ──
  const features = createElement('div', { className: 'home-features' });
  features.appendChild(createElement('h2', { className: 'home-features-title' }, '学术研究全流程赋能'));

  const featuresGrid = createElement('div', { className: 'home-features-grid' });
    const FEATURES = [
    { iconFn: iconMicroscope, name: '多 Agent 协作', desc: '研究员/审查员/架构师/综述员/润色员五位 Agent 流水线' },
    { iconFn: iconLibrary, name: 'RAG 知识增强', desc: '接入 CSSCI 文献库，回答有据可依' },
    { iconFn: iconLink, name: 'LangGraph 工作流', desc: '可视化研究流程编排与状态机驱动' },
    { iconFn: iconPen, name: '期刊格式化输出', desc: '支持《国际新闻界》《新闻与传播研究》《新闻爱好者》' },
    { iconFn: iconChart, name: '高级可视化', desc: 'Origin 风格图表：小提琴图、冲积图、3D 地形图等' },
    { iconFn: iconCode, name: '计算社会科学', desc: 'Python 爬虫/统计/机器学习一体化工作台' },
  ];
  FEATURES.forEach(f => {
    const card = createElement('div', { className: 'feature-card' },
      createElement('div', { className: 'feature-card-icon', innerHTML: f.iconFn(24) }),
      createElement('div', { className: 'feature-card-name' }, f.name),
      createElement('div', { className: 'feature-card-desc' }, f.desc),
    );
    featuresGrid.appendChild(card);
  });
  features.appendChild(featuresGrid);
  page.appendChild(features);

  // ── 快速开始引导 ──
  const quickStart = createElement('div', { className: 'home-quick-start' });
  quickStart.appendChild(createElement('p', { className: 'home-quick-start-text' },
    '选择上方学科 → 研究类型 → 准备度评估 → 与 Agent 对话，开启学术研究之旅',
  ));
  page.appendChild(quickStart);

  // ── 底部工具栏：外审专家 / 论文修改链条 / 一键生成论文 ──
  const toolbar = createElement('div', { className: 'home-bottom-toolbar' });

  const TOOLBAR_ITEMS = [
    {
      iconFn: iconGraduationCap,
      name: '外审专家',
      desc: '9 维度专业论文外审',
      accent: 'amber',
      action: () => navigateTo('external-reviewer'),
    },
    {
      iconFn: iconClipboardCheck,
      name: '论文工作台',
      desc: '上传审稿 · 一键生成 · Pipeline 驱动',
      accent: 'teal',
      action: () => showPaperWorkbenchDialog(),
    },
  ];

  TOOLBAR_ITEMS.forEach(item => {
    const btn = createElement('div', { className: 'home-toolbar-btn accent-' + item.accent },
      createElement('div', { className: 'home-toolbar-btn-icon', innerHTML: item.iconFn(24) }),
      createElement('div', { className: 'home-toolbar-btn-body' },
        createElement('div', { className: 'home-toolbar-btn-name' }, item.name),
        createElement('div', { className: 'home-toolbar-btn-desc' }, item.desc),
      ),
      createElement('div', { className: 'home-toolbar-btn-arrow' }, '→'),
    );
    btn.addEventListener('click', item.action);
    toolbar.appendChild(btn);
  });

  page.appendChild(toolbar);

  const footer = createElement('div', { className: 'version-footer' }, 'ScholarMind v' + APP_VERSION + ' · 智能学术研究助手');
  page.appendChild(footer);

  return page;
}
