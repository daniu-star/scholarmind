import { createElement } from '../utils/dom.js';
import { navigateTo } from '../app/router.js';

export function AboutPage() {
  const page = createElement('div', { className: 'page active about-page' });

  // ── Hero ──
  const hero = createElement('section', { className: 'about-hero' },
    createElement('div', { className: 'about-hero-aura' }),
    createElement('button', {
      className: 'about-back-btn',
      'aria-label': '返回首页',
      title: '返回首页',
      innerHTML: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>',
    }),
    createElement('div', { className: 'about-hero-content' },
      createElement('h1', { className: 'about-hero-title' }, 'ScholarMind 智能学术研究平台'),
      createElement('p', { className: 'about-hero-subtitle' },
        '让学术研究，回归思考本身。融合 RAG 知识检索、多 Agent 协作与学科化研究流程，从选题到成文的全程智能伙伴。'),
      createElement('div', { className: 'about-hero-cta' },
        createElement('button', { className: 'about-hero-btn-primary' }, '立即体验'),
        createElement('button', { className: 'about-hero-btn-secondary' }, '了解产品功能'),
      ),
    ),
  );
  hero.querySelector('.about-back-btn').addEventListener('click', () => navigateTo('landing'));
  hero.querySelector('.about-hero-btn-primary').addEventListener('click', () => navigateTo('homepage'));
  hero.querySelector('.about-hero-btn-secondary').addEventListener('click', () => navigateTo('landing'));
  page.appendChild(hero);

  // ── Core Capabilities ──
  const caps = createElement('section', { className: 'about-section' },
    createElement('h2', { className: 'about-section-title' }, '核心能力'),
    createElement('p', { className: 'about-section-subtitle' }, '四大引擎驱动学术研究的全流程智能化'),
    createElement('div', { className: 'about-cards-grid' },
      ...[
        { title: '多 Agent 协作', desc: '五大 Agent 各司其职，从选题、检索、写作到审稿，智能分工、协同推进。' },
        { title: 'RAG 知识增强', desc: '对接 CNKI 学术资源与向量检索，每一处论证都有真实文献可溯。' },
        { title: '学科化流程', desc: '五大学科专属研究范式，依据学科特性定制研究路径与写作规范。' },
        { title: '循环审稿', desc: '生成、外审、修改多轮迭代打磨，每一稿都有专家级反馈。' },
      ].map(c =>
        createElement('div', { className: 'about-card' },
          createElement('div', { className: 'about-card-icon' },
            createElement('span', { className: 'about-card-icon-placeholder' }),
          ),
          createElement('h3', { className: 'about-card-title' }, c.title),
          createElement('p', { className: 'about-card-desc' }, c.desc),
        )
      ),
    ),
  );
  page.appendChild(caps);

  // ── Pricing ──
  const pricing = createElement('section', { className: 'about-section' },
    createElement('h2', { className: 'about-section-title' }, '灵活计费'),
    createElement('p', { className: 'about-section-subtitle' }, '按需选择，从个人到企业，总有一档适合你'),
    createElement('div', { className: 'about-pricing-table' },
      ...[
        { name: '免费版', price: '¥0', features: ['基础对话能力', '有限文献检索', 'Flash 快速模型', '单学科研究入口', '社区支持'], featured: false },
        { name: 'Pro 个人版', price: '¥39/月', features: ['无限对话次数', '全量文献检索', 'Pro 深度推理模型', '循环审稿打磨', '五大学科入口', '私有知识库'], featured: true },
        { name: '企业版', price: '定制', features: ['团队协作空间', '私有化部署', '定制化 Agent', '专属客户支持', 'API 接口开放', 'SLA 服务保障'], featured: false },
      ].map(p =>
        createElement('div', { className: 'about-pricing-card' + (p.featured ? ' about-pricing-card--featured' : '') },
          p.featured ? createElement('span', { className: 'about-pricing-badge' }, '推荐') : null,
          createElement('h3', { className: 'about-pricing-name' }, p.name),
          createElement('div', { className: 'about-pricing-price' }, p.price),
          createElement('ul', { className: 'about-pricing-features' },
            ...p.features.map(f => createElement('li', {}, f)),
          ),
        )
      ),
    ),
    createElement('p', { className: 'about-pricing-note' },
      '支持按月 / 按年订阅（年付享 8 折优惠），亦可按量计费。'),
  );
  page.appendChild(pricing);

  // ── Special Features ──
  const features = createElement('section', { className: 'about-section' },
    createElement('h2', { className: 'about-section-title' }, '特殊功能'),
    createElement('p', { className: 'about-section-subtitle' }, '为学术研究深度定制的差异化能力'),
    ...[
      { title: 'Flash / Pro 双模型', desc: 'Flash 模型快速应答，秒级响应研究提问；Pro 模型深度推理，逐层剖析复杂论证。一快一深，按需切换。' },
      { title: '学科化定制', desc: '五大学科专属研究范式，依据学科特性定制研究路径、方法选择与写作规范，让方法与内容深度契合。' },
      { title: '论文美学排版', desc: '内置 CSSCI/SCI 等主流期刊模板，自动格式化参考文献与图表，一键导出符合投稿要求的 Word 文档。' },
    ].map(f =>
      createElement('div', { className: 'about-feature-block' },
        createElement('div', { className: 'about-feature-content' },
          createElement('h3', {}, f.title),
          createElement('p', {}, f.desc),
        ),
      )
    ),
  );
  page.appendChild(features);

  // ── Footer ──
  const footer = createElement('footer', { className: 'landing-footer' },
    createElement('div', { className: 'landing-footer-content' },
      createElement('div', { className: 'landing-footer-legal' },
        createElement('span', {}, '© 2026 ScholarMind. 保留所有权利。'),
      ),
    ),
  );
  page.appendChild(footer);

  return page;
}
