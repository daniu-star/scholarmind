(function () {
  window.addEventListener('error', (event) => {
    document.documentElement.dataset.prototypeError = event.message || 'Unknown prototype error';
  });
  const icons = {
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    play: '<path d="M8 5v14l11-7z"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    upload: '<path d="M12 16V4m0 0L7 9m5-5 5 5M5 20h14"/>',
    scan: '<path d="M4 8V5a1 1 0 0 1 1-1h3m8 0h3a1 1 0 0 1 1 1v3m0 8v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M8 12h8"/>',
    search: '<circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/>',
    users: '<path d="M16 20v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><circle cx="9.5" cy="7" r="4"/><path d="M17 11a4 4 0 0 1 4 4v1"/>',
    message: '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/>',
    file: '<path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5M9 13h6M9 17h4"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    spark: '<path d="m12 3 1.8 4.7L18 9.5l-4.2 1.8L12 16l-1.8-4.7L6 9.5l4.2-1.8z"/><path d="m19 16 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
    chevron: '<path d="m8 10 4 4 4-4"/>',
    briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1A1.7 1.7 0 0 0 4.6 15 1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/>',
    layout: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
    bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7M10 20h4"/>',
    filter: '<path d="M3 5h18M6 12h12M10 19h4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    back: '<path d="m15 18-6-6 6-6"/>',
    forward: '<path d="m9 18 6-6-6-6"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    candidate: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    radar: '<path d="m12 2 9 6.5-3.4 10.6H6.4L3 8.5z"/><path d="m12 7 4.3 3.1-1.6 5.1H9.3l-1.6-5.1z"/>',
    wallet: '<path d="M4 6h15a2 2 0 0 1 2 2v10H4a2 2 0 0 1-2-2V6a3 3 0 0 1 3-3h13"/><path d="M16 11h5v4h-5z"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.7 2.7 0 1 1 4.2 2.3c-1.2.7-1.7 1.2-1.7 2.2M12 17h.01"/>',
    more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'
  };

  function renderIcons(root = document) {
    root.querySelectorAll('[data-icon]').forEach((node) => {
      const name = node.getAttribute('data-icon');
      const body = icons[name] || icons.spark;
      node.innerHTML = `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
    });
  }

  function qs(selector, root = document) {
    return root.querySelector(selector);
  }

  function qsa(selector, root = document) {
    return Array.from(root.querySelectorAll(selector));
  }

  const memoryStorage = {};
  function storageGet(key) {
    try {
      return window.localStorage ? window.localStorage.getItem(key) : (memoryStorage[key] || null);
    } catch (_) {
      return memoryStorage[key] || null;
    }
  }

  function storageSet(key, value) {
    try {
      if (window.localStorage) window.localStorage.setItem(key, value);
      else memoryStorage[key] = value;
    } catch (_) {
      memoryStorage[key] = value;
    }
  }

  renderIcons();
  document.documentElement.dataset.prototypeStage = 'icons';

  const header = qs('.site-header');
  if (header) {
    const onScroll = () => header.classList.toggle('scrolled', window.scrollY > 12);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    qs('.mobile-menu-button')?.addEventListener('click', () => {
      header.classList.toggle('menu-open');
    });
  }

  const tutorialSteps = [
    {
      kicker: '01 / 创建项目',
      title: '先建立一条清晰的招聘主线',
      body: '职位、JD、筛选条件、候选人和面试记录都会归入同一个招聘项目，避免信息散落在多个页面。',
      metaA: ['需要准备', '职位名称与 JD'],
      metaB: ['预计用时', '约 2 分钟'],
      icon: 'briefcase'
    },
    {
      kicker: '02 / 导入简历',
      title: '把文件、邮箱与候选人统一收进来',
      body: '支持 PDF、DOCX 与图片简历。系统会展示上传、解析与异常状态，不让任务停在一个模糊的加载动画里。',
      metaA: ['导入方式', '本地文件 / 邮箱'],
      metaB: ['完成结果', '结构化简历'],
      icon: 'upload'
    },
    {
      kicker: '03 / 智能筛选',
      title: '先看结论，再查看它为什么成立',
      body: '硬性条件、匹配度、推荐等级、能力命中与风险提示被放在同一上下文中，分数不再是孤立结果。',
      metaA: ['AI 动作', '匹配与解释'],
      metaB: ['完成结果', '候选人清单'],
      icon: 'scan'
    },
    {
      kicker: '04 / AI 面试',
      title: '围绕真实经历持续追问',
      body: '系统结合职位要求、候选人简历和上一轮回答生成问题，让面试从固定题库升级为能力证据采集。',
      metaA: ['考察模式', '初步 / 中级 / 深度'],
      metaB: ['完成结果', '面试记录'],
      icon: 'message'
    },
    {
      kicker: '05 / 证据链报告',
      title: '让业务经理能够阅读、复核与决策',
      body: '评分、优势、能力缺口与风险都能回到对应问答证据。AI 提供判断线索，最终决策仍由招聘团队完成。',
      metaA: ['报告内容', '评分 / 证据 / 风险'],
      metaB: ['下一步', '分享或终面'],
      icon: 'file'
    }
  ];

  let tutorialIndex = 0;
  let returnTarget = 'app.html';

  function ensureModals() {
    if (qs('#tutorial-overlay')) return;
    document.body.insertAdjacentHTML('beforeend', `
      <div class="overlay" id="tutorial-overlay" role="dialog" aria-modal="true" aria-hidden="true" aria-label="首次使用教程">
        <div class="tutorial-modal">
          <div class="tutorial-visual">
            <div class="tutorial-brand" data-tutorial-kicker>01 / 创建项目</div>
            <div class="tutorial-art">
              <div class="tutorial-art-icon" data-tutorial-art-icon data-icon="briefcase"></div>
              <h3 data-tutorial-art-title>先建立一条清晰的招聘主线</h3>
              <p data-tutorial-art-body>约 2 分钟</p>
            </div>
            <div class="tutorial-progress" data-tutorial-progress></div>
          </div>
          <div class="tutorial-content">
            <button class="button-icon modal-close" type="button" data-close-tutorial aria-label="关闭教程"><span data-icon="close"></span></button>
            <div class="tutorial-step-count" data-tutorial-count>步骤 1 / 5</div>
            <h2 data-tutorial-title>先建立一条清晰的招聘主线</h2>
            <p data-tutorial-body></p>
            <div class="tutorial-facts">
              <div class="tutorial-fact"><small data-meta-a-label>需要准备</small><strong data-meta-a-value>职位名称与 JD</strong></div>
              <div class="tutorial-fact"><small data-meta-b-label>预计用时</small><strong data-meta-b-value>约 2 分钟</strong></div>
            </div>
            <div class="tutorial-actions">
              <button class="button-quiet" type="button" data-tutorial-skip>跳过教程</button>
              <div class="tutorial-action-group">
                <button class="button light" type="button" data-tutorial-back><span data-icon="back"></span>返回</button>
                <button class="button primary" type="button" data-tutorial-next>下一步<span data-icon="forward"></span></button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="overlay" id="auth-overlay" role="dialog" aria-modal="true" aria-hidden="true" aria-label="登录或注册">
        <div class="auth-modal">
          <div class="auth-aside">
            <div class="brand"><span class="brand-mark"></span><span class="brand-type"><strong>RENDU</strong><small>Recruit OS</small></span></div>
            <h3>把下一次招聘判断，交付得更清楚。</h3>
            <p>原型登录不会提交真实账号。登录后将返回你刚才选择的任务。</p>
          </div>
          <div class="auth-content">
            <button class="button-icon modal-close" type="button" data-close-auth aria-label="关闭登录"><span data-icon="close"></span></button>
            <h2 data-auth-title>欢迎回来</h2>
            <p data-auth-context>登录后将继续进入任度 AI 招聘工作台</p>
            <div class="auth-tabs">
              <button class="active" type="button" data-auth-tab="login">登录</button>
              <button type="button" data-auth-tab="register">注册试用</button>
            </div>
            <form data-auth-form>
              <div class="field"><label for="prototype-account">用户名或邮箱</label><input id="prototype-account" autocomplete="username" value="demo@rendu.ai" required></div>
              <div class="field"><label for="prototype-password">密码</label><input id="prototype-password" type="password" autocomplete="current-password" value="prototype" required></div>
              <div class="auth-options">
                <label class="checkbox-row"><input type="checkbox" checked>记住我</label>
                <a href="#" data-prototype-action data-message="密码找回将在正式版本接入">忘记密码？</a>
              </div>
              <button class="button primary auth-submit" type="submit" data-auth-submit>登录并继续</button>
              <p class="auth-terms">继续即代表你同意服务条款与隐私政策。此页面仅为交互原型。</p>
            </form>
          </div>
        </div>
      </div>`);
    renderIcons();
  }

  ensureModals();
  document.documentElement.dataset.prototypeStage = 'modals';

  const tutorialOverlay = qs('#tutorial-overlay');
  const authOverlay = qs('#auth-overlay');

  function lockBody() {
    document.body.classList.add('modal-open');
  }

  function unlockBody() {
    if (!qs('.overlay.open')) document.body.classList.remove('modal-open');
  }

  function setOverlay(overlay, open) {
    if (!overlay) return;
    overlay.classList.toggle('open', open);
    overlay.setAttribute('aria-hidden', String(!open));
    if (open) lockBody();
    else window.setTimeout(unlockBody, 0);
  }

  function updateTutorial() {
    if (!tutorialOverlay) return;
    const step = tutorialSteps[tutorialIndex];
    qs('[data-tutorial-kicker]', tutorialOverlay).textContent = step.kicker;
    qs('[data-tutorial-title]', tutorialOverlay).textContent = step.title;
    qs('[data-tutorial-body]', tutorialOverlay).textContent = step.body;
    qs('[data-meta-a-label]', tutorialOverlay).textContent = step.metaA[0];
    qs('[data-meta-a-value]', tutorialOverlay).textContent = step.metaA[1];
    qs('[data-meta-b-label]', tutorialOverlay).textContent = step.metaB[0];
    qs('[data-meta-b-value]', tutorialOverlay).textContent = step.metaB[1];
    qs('[data-tutorial-count]', tutorialOverlay).textContent = `步骤 ${tutorialIndex + 1} / ${tutorialSteps.length}`;
    qs('[data-tutorial-art-icon]', tutorialOverlay).setAttribute('data-icon', step.icon);
    qs('[data-tutorial-art-title]', tutorialOverlay).textContent = step.title;
    qs('[data-tutorial-art-body]', tutorialOverlay).textContent = step.metaB[1];
    const progress = qs('[data-tutorial-progress]', tutorialOverlay);
    progress.innerHTML = tutorialSteps.map((_, i) => `<span class="${i <= tutorialIndex ? 'active' : ''}"></span>`).join('');
    const back = qs('[data-tutorial-back]', tutorialOverlay);
    back.disabled = tutorialIndex === 0;
    back.style.opacity = tutorialIndex === 0 ? '.42' : '1';
    const next = qs('[data-tutorial-next]', tutorialOverlay);
    next.innerHTML = tutorialIndex === tutorialSteps.length - 1
      ? '开始使用 <span data-icon="arrow"></span>'
      : '下一步 <span data-icon="forward"></span>';
    renderIcons(tutorialOverlay);
  }

  function openTutorial(target = 'app.html', force = false) {
    document.documentElement.dataset.tutorialRequested = target;
    returnTarget = target;
    if (!force && storageGet('rendu_tutorial_seen') === '1') {
      document.documentElement.dataset.tutorialMode = 'returning';
      openAuth(target);
      return;
    }
    document.documentElement.dataset.tutorialMode = 'first';
    tutorialIndex = 0;
    updateTutorial();
    setOverlay(tutorialOverlay, true);
  }

  function closeTutorial() {
    setOverlay(tutorialOverlay, false);
  }

  function openAuth(target = 'app.html') {
    returnTarget = target;
    closeTutorial();
    window.setTimeout(() => {
      setOverlay(authOverlay, true);
      const context = qs('[data-auth-context]', authOverlay);
      if (context) {
        const label = target.includes('screening') ? '智能筛选工作台' : '任度 AI 招聘工作台';
        context.textContent = `登录后将继续进入${label}`;
      }
      qs('input', authOverlay)?.focus();
    }, 90);
  }

  function closeAuth() {
    setOverlay(authOverlay, false);
  }

  qsa('[data-start]').forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      document.documentElement.dataset.lastStartClick = button.getAttribute('data-target') || 'app.html';
      openTutorial(button.getAttribute('data-target') || 'app.html');
    });
  });
  document.documentElement.dataset.prototypeStage = 'events';

  qsa('[data-replay-tutorial]').forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      openTutorial(button.getAttribute('data-target') || 'app.html', true);
    });
  });

  qsa('[data-login]').forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      openAuth(button.getAttribute('data-target') || 'app.html');
    });
  });

  qs('[data-tutorial-back]')?.addEventListener('click', () => {
    tutorialIndex = Math.max(0, tutorialIndex - 1);
    updateTutorial();
  });

  qs('[data-tutorial-next]')?.addEventListener('click', () => {
    if (tutorialIndex < tutorialSteps.length - 1) {
      tutorialIndex += 1;
      updateTutorial();
      return;
    }
    storageSet('rendu_tutorial_seen', '1');
    openAuth(returnTarget);
  });

  qs('[data-tutorial-skip]')?.addEventListener('click', () => {
    storageSet('rendu_tutorial_seen', '1');
    openAuth(returnTarget);
  });

  qsa('[data-close-tutorial]').forEach((button) => button.addEventListener('click', closeTutorial));
  qsa('[data-close-auth]').forEach((button) => button.addEventListener('click', closeAuth));

  qsa('.overlay').forEach((overlay) => {
    overlay.addEventListener('click', (event) => {
      if (event.target !== overlay) return;
      setOverlay(overlay, false);
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    closeTutorial();
    closeAuth();
  });

  qsa('[data-auth-tab]').forEach((tab) => {
    tab.addEventListener('click', () => {
      qsa('[data-auth-tab]').forEach((item) => item.classList.toggle('active', item === tab));
      const mode = tab.getAttribute('data-auth-tab');
      qs('[data-auth-title]').textContent = mode === 'register' ? '创建试用账号' : '欢迎回来';
      qs('[data-auth-submit]').textContent = mode === 'register' ? '创建账号并继续' : '登录并继续';
    });
  });

  qs('[data-auth-form]')?.addEventListener('submit', (event) => {
    event.preventDefault();
    const submit = qs('[data-auth-submit]');
    const original = submit.textContent;
    submit.disabled = true;
    submit.textContent = '正在进入工作台…';
    window.setTimeout(() => {
      storageSet('rendu_auth_demo', '1');
      window.location.href = returnTarget;
      submit.disabled = false;
      submit.textContent = original;
    }, 650);
  });

  qsa('[data-demo-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      qsa('[data-demo-tab]').forEach((item) => item.classList.toggle('active', item === button));
      const screen = qs('[data-demo-screen]');
      if (!screen) return;
      const copy = {
        overview: ['产品总览', '从招聘项目到证据链报告', '在一条连续流程中完成简历筛选、候选人面试和业务决策。'],
        screening: ['闪电筛', '先看推荐，再回到匹配证据', '候选人的分数、能力命中与风险被放在同一个可解释界面中。'],
        interview: ['急速面', '动态追问，让经验边界显现', '问题来自职位、简历与上一轮回答，而不是固定题库的轮播。'],
        report: ['证据链报告', '把判断交付给真正做决策的人', '优势、能力缺口和风险均可定位至对应问答证据。']
      };
      const content = copy[button.getAttribute('data-demo-tab')] || copy.overview;
      qs('[data-demo-kicker]', screen).textContent = content[0];
      qs('[data-demo-title]', screen).textContent = content[1];
      qs('[data-demo-body]', screen).textContent = content[2];
      qsa('.demo-timeline span').forEach((line, index) => line.classList.toggle('active', index <= qsa('[data-demo-tab]').indexOf(button)));
    });
  });

  qsa('[data-workflow-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      qsa('[data-workflow-tab]').forEach((item) => item.classList.toggle('active', item === button));
      const data = JSON.parse(button.getAttribute('data-workflow-tab'));
      qs('[data-flow-index]').textContent = data.index;
      qs('[data-flow-title]').textContent = data.title;
      qs('[data-flow-copy]').textContent = data.copy;
      qs('[data-flow-user]').textContent = data.user;
      qs('[data-flow-system]').textContent = data.system;
      qs('[data-flow-output]').textContent = data.output;
      qs('[data-flow-next]').textContent = data.next;
    });
  });

  qsa('[data-candidate-row]').forEach((row) => {
    row.addEventListener('click', () => {
      qsa('[data-candidate-row]').forEach((item) => item.classList.toggle('selected', item === row));
      const name = row.getAttribute('data-name');
      const role = row.getAttribute('data-role');
      const score = row.getAttribute('data-score');
      const target = qs('[data-explanation-person]');
      if (!target) return;
      qs('strong', target).textContent = name;
      qs('small', target).textContent = role;
      qs('[data-explanation-score]').textContent = score;
    });
  });

  function toast(message) {
    let node = qs('.prototype-toast');
    if (!node) {
      node = document.createElement('div');
      node.className = 'prototype-toast';
      document.body.appendChild(node);
    }
    node.innerHTML = `<span data-icon="check"></span><span>${message}</span>`;
    renderIcons(node);
    requestAnimationFrame(() => node.classList.add('show'));
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => node.classList.remove('show'), 2400);
  }

  qsa('[data-prototype-action]').forEach((button) => {
    button.addEventListener('click', () => toast(button.getAttribute('data-message') || '原型交互已触发'));
  });

  window.RenduPrototype = { openTutorial, openAuth, toast, renderIcons };
  document.documentElement.dataset.prototypeStage = 'ready';
})();
