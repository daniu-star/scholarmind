import { createElement } from '../utils/dom.js';
import { state, watch } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import {
  iconGraduationCap, iconBook, iconMicroscope,
  iconPen, iconSparkles, iconGear, iconGlobe, iconBrain
} from '../utils/icons.js';

const THEME_CHIPS = [
  { id: 'dark', label: '深色星空', gradient: 'linear-gradient(135deg,#0D1117,#161B22)' },
  { id: 'light', label: '亮色', gradient: 'linear-gradient(135deg,#FFFFFF,#F6F8FA)' },
  { id: 'zen', label: '雅黄麻纸', gradient: 'linear-gradient(135deg,#F1ECE0,#FAC75E)' },
  { id: 'pure', label: '洁白', gradient: 'linear-gradient(135deg,#FFFFFF,#F3F4F6)' },
  { id: 'warm', label: '温暖', gradient: 'linear-gradient(135deg,#FFF8F0,#FFE8D1)' },
  { id: 'eye-care', label: '护眼绿', gradient: 'linear-gradient(135deg,#C7EDCC,#B8E0BE)' },
  { id: 'volcano-academic', label: '火山学术', gradient: 'linear-gradient(135deg,#0A0E1A,#111729)' },
];

function switchLandingTheme(themeId) {
  state.settings = { ...state.settings, theme: themeId };
}

export function LandingPage() {
  const page = createElement('div', { className: 'page landing-page' });

  // ── Global Nav ──
  const nav = createElement('nav', { className: 'global-top-nav', id: 'globalTopNav' },
    createElement('div', { className: 'global-nav-brand' },
      createElement('div', { className: 'global-nav-logo-icon' }, 'S'),
      createElement('span', { className: 'global-nav-brand-text' }, 'ScholarMind'),
    ),
    createElement('button', { className: 'global-nav-cta' }, '产品使用',
      // Inline arrow SVG
      createElement('span', { innerHTML: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>' }),
    ),
  );
  nav.querySelector('.global-nav-brand').addEventListener('click', () => navigateTo('landing'));
  nav.querySelector('.global-nav-cta').addEventListener('click', () => navigateTo('homepage'));
  page.appendChild(nav);

  // ── Hero ──
  const hero = createElement('section', { className: 'landing-hero' },
    createElement('div', { className: 'landing-hero-aura' }),
    createElement('div', { className: 'landing-hero-content' },
      createElement('h1', { className: 'landing-hero-title' }, '让学术研究，回归思考本身'),
      createElement('p', { className: 'landing-hero-subtitle' },
        'ScholarMind 融合 RAG 知识检索、多 Agent 协作与学科化研究流程，陪你从选题到成文，每一步都有据可依。'),
      createElement('div', { className: 'landing-hero-cta' },
        createElement('button', { className: 'landing-btn-primary' }, '开始使用'),
        createElement('button', { className: 'landing-btn-secondary' }, '了解更多'),
      ),
      // Theme chips
      createElement('div', { className: 'landing-theme-switcher' },
        createElement('span', { className: 'landing-theme-switcher-label' }, '主题'),
        ...THEME_CHIPS.map(chip =>
          createElement('button', {
            className: 'landing-theme-chip',
            id: 'themeChip' + chip.id.charAt(0).toUpperCase() + chip.id.slice(1).replace('-', ''),
            title: chip.label,
          },
            createElement('span', { className: 'landing-theme-chip-color', style: 'background:' + chip.gradient }),
          )
        ),
      ),
    ),
    createElement('div', { className: 'landing-hero-scroll-hint' },
      // Down chevron
      createElement('span', { innerHTML: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>' }),
    ),
  );
  // Wire up CTA buttons
  const [btnStart, btnLearn] = hero.querySelectorAll('.landing-hero-cta button');
  btnStart.addEventListener('click', () => navigateTo('homepage'));
  btnLearn.addEventListener('click', () => navigateTo('about'));
  // Wire up theme chips
  hero.querySelectorAll('.landing-theme-chip').forEach((chip, i) => {
    chip.addEventListener('click', () => switchLandingTheme(THEME_CHIPS[i].id));
  });
  page.appendChild(hero);

  // ── Feature Blocks ──
  const features = createElement('section', { className: 'landing-features', id: 'landing-features' },
    // Block 1: RAG
    createElement('div', { className: 'landing-feature-block reveal' },
      createElement('div', { className: 'landing-feature-text' },
        createElement('div', { className: 'landing-feature-tag' }, '知识增强'),
        createElement('h2', { className: 'landing-feature-title' }, 'RAG 知识检索，让每一句话都有据可依'),
        createElement('p', { className: 'landing-feature-desc' },
          '接入 CNKI、WoS、Scopus、PubMed 等学术数据库，基于向量检索为你的研究提供精准文献支撑，杜绝幻觉与空谈。'),
      ),
      createElement('div', { className: 'landing-feature-visual' },
        createElement('div', { className: 'mockup-rag' },
          createElement('div', { className: 'mockup-rag-card', innerHTML: iconBook(18) + '<span style="margin-left:8px">CNKI 网页检索</span>' }),
          createElement('div', { className: 'mockup-rag-card', innerHTML: iconBrain(18) + '<span style="margin-left:8px">WoS 已连接</span>' }),
          createElement('div', { className: 'mockup-rag-card', innerHTML: iconMicroscope(18) + '<span style="margin-left:8px">Scopus 已连接</span>' }),
          createElement('div', { className: 'mockup-rag-card', innerHTML: iconSparkles(18) + '<span style="margin-left:8px">PubMed 已连接</span>' }),
        ),
      ),
    ),
    // Block 2: Multi-Agent
    createElement('div', { className: 'landing-feature-block reveal reverse' },
      createElement('div', { className: 'landing-feature-text' },
        createElement('div', { className: 'landing-feature-tag' }, '智能协作'),
        createElement('h2', { className: 'landing-feature-title' }, '多 Agent 协作，专业分工各司其职'),
        createElement('p', { className: 'landing-feature-desc' },
          '选题、文献综述、研究设计、论文撰写、润色、外审——每个环节由专属 Agent 负责，像一支学术团队为你服务。'),
      ),
      createElement('div', { className: 'landing-feature-visual' },
        createElement('div', { className: 'mockup-agents mockup-agent-flow' },
          ...[
            { icon: iconBrain(20), label: '选题' },
            { icon: iconBook(20), label: '综述' },
            { icon: iconGear(20), label: '设计' },
            { icon: iconPen(20), label: '撰写' },
            { icon: iconSparkles(20), label: '润色' },
            { icon: iconGraduationCap(20), label: '外审' },
          ].map(a => createElement('div', { className: 'mockup-agent-node' },
            createElement('span', { innerHTML: a.icon, style: 'vertical-align:middle;margin-right:4px' }),
            createElement('span', {}, a.label),
          )),
        ),
      ),
    ),
    // Block 3: Review Cycle
    createElement('div', { className: 'landing-feature-block reveal' },
      createElement('div', { className: 'landing-feature-text' },
        createElement('div', { className: 'landing-feature-tag' }, '质量保障'),
        createElement('h2', { className: 'landing-feature-title' }, '循环审稿优化，打磨至顶刊水平'),
        createElement('p', { className: 'landing-feature-desc' },
          '基于 9 维度量化评分驱动，7-13 Agent 多轮循环精炼论文，直至达到 CSSCI 顶刊发表水平。'),
      ),
      createElement('div', { className: 'landing-feature-visual' },
        createElement('div', { className: 'mockup-score' },
          createElement('div', { className: 'mockup-score-ring' },
            createElement('span', { className: 'mockup-score-value' }, '96'),
            createElement('span', { className: 'mockup-score-label' }, '综合评分'),
          ),
        ),
      ),
    ),
  );
  page.appendChild(features);

  // ── Core Capability Cards ──
  const cards = createElement('section', { className: 'landing-cards' },
    createElement('h2', { className: 'landing-section-title reveal' }, '核心能力'),
    createElement('div', { className: 'landing-cards-grid' },
      ...[
        { icon: iconBrain, title: '智能选题', desc: '从现象到角度，6 步引导构建研究问题' },
        { icon: iconBook, title: '文献综述', desc: '自动检索、筛选、整合相关文献' },
        { icon: iconMicroscope, title: '研究设计', desc: '量化、质性、混合方法全覆盖' },
        { icon: iconPen, title: '论文撰写', desc: '13 Agent 协作循环精炼' },
        { icon: iconGraduationCap, title: '外审专家', desc: '9 维度专业评审意见' },
        { icon: iconSparkles, title: '循环润色', desc: '语言、逻辑、格式全方位优化' },
      ].map((c, i) =>
        createElement('div', { className: 'landing-card reveal', style: 'animation-delay:' + (i * 80) + 'ms' },
          createElement('div', { className: 'landing-card-icon' },
            createElement('span', { innerHTML: c.icon(32) }),
          ),
          createElement('h3', {}, c.title),
          createElement('p', {}, c.desc),
        )
      ),
    ),
  );
  page.appendChild(cards);

  // ── Discipline Teaser ──
  const disciplines = createElement('section', { className: 'landing-disciplines reveal' },
    createElement('h2', { className: 'landing-section-title' }, '选择你的学科，开启研究之旅'),
    createElement('div', { className: 'landing-disciplines-grid' },
      ...[
        { id: 'engineering', icon: iconGear, name: '工科', desc: '实验 · 仿真 · 设计' },
        { id: 'science', icon: iconMicroscope, name: '理科', desc: '理论 · 实验 · 计算' },
        { id: 'humanities', icon: iconBook, name: '人文社科', desc: '调查 · 质化 · 量化' },
        { id: 'interdisciplinary', icon: iconGlobe, name: '交叉学科', desc: '跨领域 · 融合研究' },
      ].map(d =>
        createElement('div', { className: 'landing-discipline' },
          createElement('div', { className: 'landing-discipline-icon' },
            createElement('span', { innerHTML: d.icon(36) }),
          ),
          createElement('div', { className: 'landing-discipline-name' }, d.name),
          createElement('div', { className: 'landing-discipline-desc' }, d.desc),
        )
      ),
    ),
  );
  // Wire up discipline clicks
  disciplines.querySelectorAll('.landing-discipline').forEach((el, i) => {
    const ids = ['engineering', 'science', 'humanities', 'interdisciplinary'];
    el.addEventListener('click', () => navigateTo(ids[i]));
  });
  page.appendChild(disciplines);

  // ── Footer ──
  const footer = createElement('footer', { className: 'landing-footer' },
    createElement('div', { className: 'landing-footer-content' },
      createElement('div', { className: 'landing-footer-grid' },
        createElement('div', { className: 'landing-footer-col landing-footer-brand-col' },
          createElement('div', { className: 'landing-footer-brand' },
            createElement('div', { className: 'global-nav-logo-icon', style: 'width:28px;height:28px;font-size:0.8rem' }, 'S'),
            'ScholarMind',
          ),
          createElement('p', { className: 'landing-footer-tagline' },
            '让学术研究，回归思考本身。智能学术研究助手，为科研工作者提供全流程支持。'),
        ),
        createElement('div', { className: 'landing-footer-col' },
          createElement('h4', {}, '产品功能'),
          createElement('ul', {},
            createElement('li', {}, createElement('a', { href: '#' }, 'Agent 对话')),
            createElement('li', {}, createElement('a', { href: '#' }, '论文工作台')),
            createElement('li', {}, createElement('a', { href: '#' }, '计算社会科学')),
            createElement('li', {}, createElement('a', { href: '#' }, 'RAG 知识库')),
          ),
        ),
        createElement('div', { className: 'landing-footer-col' },
          createElement('h4', {}, '帮助文档'),
          createElement('ul', {},
            createElement('li', {}, createElement('a', { href: '#' }, '快速开始')),
            createElement('li', {}, createElement('a', { href: '#' }, '使用指南')),
            createElement('li', {}, createElement('a', { href: '#' }, '常见问题')),
            createElement('li', {}, createElement('a', { href: '#' }, '联系我们')),
          ),
        ),
        createElement('div', { className: 'landing-footer-col' },
          createElement('h4', {}, '关于我们'),
          createElement('ul', {},
            createElement('li', {}, createElement('a', { href: '#' }, '团队介绍')),
            createElement('li', {}, createElement('a', { href: '#' }, '隐私政策')),
            createElement('li', {}, createElement('a', { href: '#' }, '服务条款')),
            createElement('li', {}, createElement('a', { href: '#' }, '备案信息')),
          ),
        ),
      ),
      createElement('div', { className: 'landing-footer-legal' },
        createElement('span', {}, '© 2026 ScholarMind. 保留所有权利。'),
      ),
    ),
  );
  page.appendChild(footer);

  return page;
}
