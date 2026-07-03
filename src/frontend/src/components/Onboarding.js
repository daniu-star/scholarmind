/**
 * 新手引导系统（6 步）
 * 首次访问时自动弹出，完成后写入 localStorage `sm_onboarding_done`
 * 通过 initOnboarding() 在 App.js 中调用
 */
import {
  iconGraduationCap, iconBookOpen, iconMicroscope, iconDoc, iconChart, iconLightning,
  iconGear, iconFlask, iconClipboardCheck, iconBuilding, iconLibrary, iconSparkles,
  iconSearch, iconBook, iconNewspaper, iconChat, iconCode, iconPenTool, iconSun,
} from '../utils/icons.js';

const STORAGE_KEY = 'sm_onboarding_done';

const STEPS = [
  {
    icon: iconGraduationCap(32),
    title: '欢迎使用 ScholarMind',
    text: 'ScholarMind 是基于 RAG + LangGraph 的智能学术研究助手，帮助你完成从选题、文献综述、论文架构到润色降重的全流程研究工作。',
    features: null,
  },
  {
    icon: iconBookOpen(32),
    title: '选择你的学科',
    text: '首页提供三个学科入口，选择后进入对应的研究类型与 Agent 流程。每个学科都有定制化的 Agent 角色与建议。',
    features: [
      { icon: iconGear(24), name: '工科', desc: '计算机、电子、机械、土木等' },
      { icon: iconFlask(24), name: '理科', desc: '数学、物理、化学、生物等' },
      { icon: iconBookOpen(24), name: '人文社科', desc: '文学、历史、哲学、社会学等' },
    ],
  },
  {
    icon: iconMicroscope(32),
    title: '认识五位 Agent',
    text: '根据研究准备度，你将与不同的 Agent 对话。每位 Agent 各司其职，协同完成研究流程。',
    features: [
      { icon: iconMicroscope(24), name: '研究员', desc: '学术选题与问题建构' },
      { icon: iconClipboardCheck(24), name: '审查员', desc: '研究思路四维度评估' },
      { icon: iconBuilding(24), name: '架构师', desc: '论文架构与逻辑优化' },
      { icon: iconLibrary(24), name: '综述员', desc: '文献综述撰写' },
      { icon: iconSparkles(24), name: '润色员', desc: '语言润色与 AIGC 降重' },
    ],
  },
  {
    icon: iconDoc(32),
    title: '文献能力与期刊格式化',
    text: 'ScholarMind 接入 CSSCI 文献库，回答有据可依。写作工作台支持 Word 文档输出，并按目标期刊格式化排版。',
    features: [
      { icon: iconSearch(24), name: 'RAG 检索', desc: 'CSSCI 文献库实时检索' },
      { icon: iconDoc(24), name: 'Word 导出', desc: '一键生成 .docx 文档' },
      { icon: iconNewspaper(24), name: '期刊格式', desc: '《国际新闻界》《新闻与传播研究》等' },
    ],
  },
  {
    icon: iconChart(32),
    title: '高级可视化图表',
    text: '告别基础柱状图与饼图。ScholarMind 提供 11 种 Origin 风格的高级图表，满足 CSSCI/SSCI 期刊发表标准。',
    features: [
      { icon: iconChart(24), name: '小提琴图', desc: '分布密度可视化' },
      { icon: iconChart(24), name: '冲积图', desc: '流向与变迁分析' },
      { icon: iconChart(24), name: '3D 地形图', desc: '三维数据探索' },
      { icon: iconChart(24), name: '蜂群图', desc: '散点避免重叠' },
    ],
  },
  {
    icon: iconLightning(32),
    title: '快捷操作',
    text: '顶部导航栏提供主题切换、帮助与设置入口。Agent 对话页支持历史记录、新建对话、Flash/Pro 模式切换。计算社会科学模块提供 Python 代码编辑器与运行环境。',
    features: [
      { icon: iconSun(24), name: '4 种主题', desc: '深色/浅色/洁白/温暖' },
      { icon: iconChat(24), name: '历史对话', desc: '随时回看与继续' },
      { icon: iconCode(24), name: '计算社会科学', desc: 'Python 爬虫/统计/可视化' },
      { icon: iconPenTool(24), name: '写作工作台', desc: '实时检测与点评' },
    ],
  },
];

let currentStep = 0;
let overlayEl = null;

function renderStep(stepIdx) {
  if (!overlayEl) return;
  const step = STEPS[stepIdx];
  const total = STEPS.length;

  const progressFill = overlayEl.querySelector('.onboarding-progress-fill');
  const progressLabel = overlayEl.querySelector('.onboarding-progress-label');
  const titleEl = overlayEl.querySelector('.onboarding-title');
  const bodyEl = overlayEl.querySelector('.onboarding-body');
  const prevBtn = overlayEl.querySelector('.onboarding-btn-prev');
  const nextBtn = overlayEl.querySelector('.onboarding-btn-next');

  progressFill.style.width = ((stepIdx + 1) / total * 100) + '%';
  progressLabel.textContent = `步骤 ${stepIdx + 1} / ${total}`;
  titleEl.textContent = step.title;

  let bodyHTML = `
    <div class="onboarding-step-icon">${step.icon}</div>
    <p class="onboarding-step-text">${step.text}</p>
  `;
  if (step.features && step.features.length) {
    bodyHTML += '<div class="onboarding-feature-grid">';
    step.features.forEach(f => {
      bodyHTML += `
        <div class="onboarding-feature-item">
          <div class="onboarding-feature-icon">${f.icon}</div>
          <div class="onboarding-feature-name">${f.name}</div>
          <div class="onboarding-feature-desc">${f.desc}</div>
        </div>
      `;
    });
    bodyHTML += '</div>';
  }
  bodyEl.innerHTML = bodyHTML;

  prevBtn.disabled = stepIdx === 0;
  nextBtn.textContent = stepIdx === total - 1 ? '完成' : '下一步';
}

function closeOnboarding() {
  if (overlayEl) {
    overlayEl.remove();
    overlayEl = null;
  }
  currentStep = 0;
}

function finishOnboarding() {
  try {
    localStorage.setItem(STORAGE_KEY, '1');
  } catch (e) {
    // localStorage 不可用时静默失败
  }
  closeOnboarding();
}

export function initOnboarding() {
  // 已完成引导则不弹出
  try {
    if (localStorage.getItem(STORAGE_KEY) === '1') return;
  } catch (e) {
    return;
  }

  // 已存在则不重复创建
  if (document.getElementById('onboardingOverlay')) return;

  currentStep = 0;
  overlayEl = document.createElement('div');
  overlayEl.id = 'onboardingOverlay';
  overlayEl.className = 'onboarding-overlay';

  overlayEl.innerHTML = `
    <div class="onboarding-modal" role="dialog" aria-modal="true" aria-labelledby="onboardingTitle">
      <div class="onboarding-header">
        <div class="onboarding-progress-wrap">
          <span class="onboarding-progress-label">步骤 1 / ${STEPS.length}</span>
          <div class="onboarding-progress-bar">
            <div class="onboarding-progress-fill" style="width: ${(100 / STEPS.length)}%;"></div>
          </div>
          <button class="onboarding-skip-btn" type="button">跳过引导</button>
        </div>
        <h3 class="onboarding-title" id="onboardingTitle">${STEPS[0].title}</h3>
      </div>
      <div class="onboarding-body"></div>
      <div class="onboarding-footer">
        <button class="onboarding-btn onboarding-btn-prev" type="button" disabled>上一步</button>
        <button class="onboarding-btn onboarding-btn-primary onboarding-btn-next" type="button">下一步</button>
      </div>
    </div>
  `;

  document.body.appendChild(overlayEl);

  // 绑定事件
  overlayEl.querySelector('.onboarding-skip-btn').addEventListener('click', finishOnboarding);
  overlayEl.querySelector('.onboarding-btn-prev').addEventListener('click', () => {
    if (currentStep > 0) {
      currentStep--;
      renderStep(currentStep);
    }
  });
  overlayEl.querySelector('.onboarding-btn-next').addEventListener('click', () => {
    if (currentStep < STEPS.length - 1) {
      currentStep++;
      renderStep(currentStep);
    } else {
      finishOnboarding();
    }
  });

  // ESC 关闭
  overlayEl.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') finishOnboarding();
  });

  // 渲染首步
  renderStep(0);

  // 点击遮罩不关闭（避免误触），仅通过按钮关闭
}

/**
 * 重置引导状态（供设置页调用）
 */
export function resetOnboarding() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (e) {
    // 静默失败
  }
  initOnboarding();
}
