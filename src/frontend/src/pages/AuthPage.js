import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { authApi } from '../services/authApi.js';
import { iconMail, iconKey } from '../utils/icons.js';

export function AuthPage() {
  const page = createElement('div', { className: 'page active page-auth' });
  const card = createElement('div', { className: 'auth-card' });

  // Brand header
  const brand = createElement('div', { className: 'auth-brand' });
  brand.innerHTML =
    '<div style="width:48px;height:48px;border-radius:14px;background:linear-gradient(135deg,var(--accent-brand),#1B5E20);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:1.2rem;margin:0 auto 12px">SM</div>' +
    '<h2 class="auth-title" id="authTitle">登录 ScholarMind</h2>' +
    '<p style="font-size:.82rem;color:var(--text-tertiary);text-align:center;margin-bottom:20px">免费注册，赠送 20 次对话</p>';
  card.appendChild(brand);

  let isLogin = true;

  const form = createElement('form', { className: 'auth-form' });

  // Email input with SVG icon
  const emailWrap = createElement('div', { style: 'position:relative' });
  const emailInput = createElement('input', {
    type: 'text', placeholder: '您的邮箱地址', className: 'auth-input',
    required: true, inputMode: 'email', autoComplete: 'email',
    style: 'padding-left:44px'
  });
  const emailIconEl = createElement('span', { style: 'position:absolute;left:14px;top:50%;transform:translateY(-50%);opacity:.5;pointer-events:none;display:inline-flex;align-items:center;color:var(--text-tertiary)' });
  emailIconEl.innerHTML = iconMail(18);
  emailWrap.appendChild(emailIconEl);
  emailWrap.appendChild(emailInput);

  // Code row
  const codeRow = createElement('div', { style: 'display:flex;gap:10px' });
  const codeWrap = createElement('div', { style: 'position:relative;flex:1' });
  const codeInput = createElement('input', {
    type: 'text', placeholder: '6 位验证码', className: 'auth-input',
    maxLength: 6, inputMode: 'numeric', autoComplete: 'one-time-code',
    style: 'padding-left:40px'
  });
  const codeIconEl = createElement('span', { style: 'position:absolute;left:14px;top:50%;transform:translateY(-50%);opacity:.5;pointer-events:none;display:inline-flex;align-items:center;color:var(--text-tertiary)' });
  codeIconEl.textContent = '#';
  codeWrap.appendChild(codeIconEl);
  codeWrap.appendChild(codeInput);
  const sendCodeBtn = createElement('button', {
    type: 'button',
    className: 'auth-send-code-btn',
    style: 'padding:0 16px;border:1.5px solid var(--accent-brand);border-radius:12px;background:transparent;color:var(--accent-brand);font-weight:600;font-size:.82rem;cursor:pointer;white-space:nowrap;transition:all .2s;min-width:100px'
  }, '发送验证码');
  codeRow.appendChild(codeWrap);
  codeRow.appendChild(sendCodeBtn);

  // Email hint
  const emailHint = createElement('div', { style: 'font-size:.74rem;color:var(--text-tertiary);text-align:center;margin-top:2px' }, '未收到？请检查垃圾邮件箱');

  // Divider
  const divider = createElement('div', { style: 'display:flex;align-items:center;gap:12px;margin:4px 0;color:var(--text-tertiary);font-size:.76rem' });
  divider.innerHTML = '<span style="flex:1;height:1px;background:var(--border)"></span>或使用密码<span style="flex:1;height:1px;background:var(--border)"></span>';

  // Password area (collapsible with transition)
  const pwdToggle = createElement('div', {
    style: 'color:var(--text-tertiary);font-size:.8rem;text-align:center;cursor:pointer;padding:6px;transition:color .2s'
  }, '+ 使用密码登录');
  const pwdArea = createElement('div', { style: 'overflow:hidden;max-height:0;opacity:0;transition:max-height .35s ease,opacity .25s ease,margin .25s ease' });
  const pwdWrap = createElement('div', { style: 'position:relative' });
  const passwordInput = createElement('input', {
    type: 'password', placeholder: '设置密码（至少 6 位）', className: 'auth-input',
    minLength: 6, style: 'padding-left:44px'
  });
  const pwdIconEl = createElement('span', { style: 'position:absolute;left:14px;top:50%;transform:translateY(-50%);opacity:.5;pointer-events:none;display:inline-flex;align-items:center;color:var(--text-tertiary)' });
  pwdIconEl.innerHTML = iconKey(18);
  pwdWrap.appendChild(pwdIconEl);
  pwdWrap.appendChild(passwordInput);
  pwdArea.appendChild(pwdWrap);
  const nicknameInput = createElement('input', {
    type: 'text', placeholder: '昵称（可选）', className: 'auth-input',
    maxLength: 64, style: 'padding-left:44px;display:none'
  });
  pwdArea.appendChild(nicknameInput);

  let pwdVisible = false;

  form.appendChild(emailWrap);
  form.appendChild(codeRow);
  form.appendChild(emailHint);
  form.appendChild(divider);
  form.appendChild(pwdToggle);
  form.appendChild(pwdArea);

  // Submit
  const submitBtn = createElement('button', { type: 'submit', className: 'btn btn-primary auth-submit' }, '登录');
  form.appendChild(submitBtn);

  // Switch login/register
  const switchText = createElement('p', { className: 'auth-switch' }, '还没有账号？');
  const switchLink = createElement('a', { href: '#', className: 'auth-switch-link' }, '注册');
  switchText.appendChild(switchLink);
  form.appendChild(switchText);

  // Email providers hint
  form.appendChild(createElement('div', {
    style: 'font-size:.74rem;color:var(--text-tertiary);text-align:center;opacity:.7;margin-top:4px'
  }, '支持 QQ邮箱 · 163 · 126 · Gmail · Outlook 等'));

  card.appendChild(form);
  page.appendChild(card);

  // Password toggle with transition
  pwdToggle.addEventListener('click', () => {
    pwdVisible = !pwdVisible;
    if (pwdVisible) {
      pwdArea.style.maxHeight = '200px';
      pwdArea.style.opacity = '1';
      pwdArea.style.marginBottom = '8px';
    } else {
      pwdArea.style.maxHeight = '0';
      pwdArea.style.opacity = '0';
      pwdArea.style.marginBottom = '0';
    }
    nicknameInput.style.display = (!pwdVisible || isLogin) ? 'none' : 'block';
    pwdToggle.textContent = pwdVisible ? '− 收起密码' : '+ 使用密码登录';
  });

  // Code countdown with proper cleanup
  let codeCountdown = 0;
  let countdownTimer = null;
  function clearCountdown() {
    if (countdownTimer) { clearTimeout(countdownTimer); countdownTimer = null; }
    codeCountdown = 0;
    sendCodeBtn.textContent = '发送验证码';
    sendCodeBtn.disabled = false;
    sendCodeBtn.style.borderColor = '';
    sendCodeBtn.style.color = '';
  }

  sendCodeBtn.addEventListener('click', async () => {
    if (codeCountdown > 0) return;
    const target = emailInput.value.trim();
    if (!target) return;
    clearCountdown();
    sendCodeBtn.disabled = true;
    sendCodeBtn.textContent = '发送中…';
    try {
      await authApi.sendCode(target, isLogin ? 'login' : 'register');
      sendCodeBtn.style.borderColor = 'var(--text-tertiary)';
      sendCodeBtn.style.color = 'var(--text-tertiary)';
      emailHint.textContent = '验证码已发送，请查收（含垃圾邮件箱）';
      emailHint.style.color = 'var(--color-success)';
      codeInput.focus();
      codeCountdown = 60;
      sendCodeBtn.textContent = codeCountdown + 's';

      function tick() {
        if (codeCountdown <= 1) {
          clearCountdown();
        } else {
          codeCountdown--;
          sendCodeBtn.textContent = codeCountdown + 's';
          countdownTimer = setTimeout(tick, 1000);
        }
      }
      countdownTimer = setTimeout(tick, 1000);
    } catch (err) {
      clearCountdown();
      const errorEl = form.querySelector('.auth-error');
      if (errorEl) errorEl.textContent = err.message;
    }
  });

  // Switch mode — clear form state
  function switchMode() {
    isLogin = !isLogin;
    document.getElementById('authTitle').textContent = isLogin ? '登录 ScholarMind' : '注册 ScholarMind';
    submitBtn.textContent = isLogin ? '登录' : '注册';
    nicknameInput.style.display = (!pwdVisible || isLogin) ? 'none' : 'block';
    switchText.innerHTML = isLogin ? '还没有账号？' : '已有账号？';
    const link = createElement('a', { href: '#', className: 'auth-switch-link' }, isLogin ? '注册' : '登录');
    link.addEventListener('click', (e) => { e.preventDefault(); switchMode(); });
    switchText.appendChild(link);
    // Clear error messages
    const oldErr = form.querySelector('.auth-error');
    if (oldErr) oldErr.remove();
  }
  switchLink.addEventListener('click', (e) => { e.preventDefault(); switchMode(); });

  // Submit
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const target = emailInput.value.trim();
    const code = codeInput.value.trim();
    const password = passwordInput.value;
    if (!target) return;

    submitBtn.disabled = true;
    submitBtn.textContent = '处理中...';

    try {
      let res;
      if (code && code.length === 6) {
        res = await authApi.loginWithCode(target, code);
      } else if (password && password.length >= 6) {
        res = isLogin
          ? await authApi.login(target, password)
          : await authApi.register(target, password, nicknameInput.value.trim());
      } else {
        throw new Error('请输入验证码（推荐）或至少 6 位密码');
      }

      state.auth = { user: res.user, token: res.access_token, isAuthenticated: true, entitlements: res.entitlements };
      localStorage.setItem('sm_token', res.access_token);
      localStorage.setItem('sm_refresh_token', res.refresh_token);
      localStorage.setItem('sm_user', JSON.stringify(res.user));
      localStorage.setItem('sm_entitlements', JSON.stringify(res.entitlements));

      navigateTo('homepage');
    } catch (err) {
      const old = form.querySelector('.auth-error');
      if (old) old.remove();
      const errorMsg = createElement('p', { className: 'auth-error' }, err.message || '操作失败');
      form.insertBefore(errorMsg, submitBtn);
      setTimeout(() => { if (errorMsg.parentNode) errorMsg.remove(); }, 4000);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = isLogin ? '登录' : '注册';
    }
  });

  return page;
}