import { createElement } from '../utils/dom.js';
import { navigateTo } from '../app/router.js';
import { paymentApi } from '../services/paymentApi.js';
import { showToast } from '../components/ConfirmDialog.js';
import { iconCheck } from '../utils/icons.js';

export function PricingPage() {
  const page = createElement('div', { className: 'page active page-pricing' });
  page.appendChild(createElement('h1', { className: 'pricing-title' }, '选择适合你的套餐'));

  const packages = [
    { id: 'paper_once', name: '单次生成', price: 4.99, tokens: '1 次额度', model: 'Flash 模型', features: ['一键论文生成 Pipeline 1 次', '永久有效，使用后扣除'] },
    { id: 'paper_bundle_5', name: '论文进阶包', price: 19.99, tokens: '5 次共享额度', model: 'Flash 模型', features: ['论文生成或修改共 5 次', '外审专家服务 30 天'], popular: true },
    { id: 'monthly_all', name: '全功能月度', price: 39.9, tokens: '不限次数', model: 'Flash 模型', features: ['全部 Agent 与快速通道', '不限对话与 Pipeline', '有效期 30 天'] },
    { id: 'monthly_pro', name: '全功能 Pro 月度', price: 59.9, tokens: '不限次数', model: 'Pro 模型', features: ['全功能月度全部权益', '默认使用 Pro 深度模型', '有效期 30 天'] },
  ];

  const grid = createElement('div', { className: 'pricing-grid' });
  packages.forEach(pkg => {
    const card = createElement('div', { className: `pricing-card ${pkg.popular ? 'popular' : ''}` });
    if (pkg.popular) card.appendChild(createElement('div', { className: 'pricing-badge' }, '推荐'));
    card.appendChild(createElement('h2', { className: 'pricing-name' }, pkg.name));
    card.appendChild(createElement('div', { className: 'pricing-price' }, `¥${pkg.price}` + (pkg.id.startsWith('monthly_') ? '/30天' : '')));
    card.appendChild(createElement('div', { className: 'pricing-tokens' }, pkg.tokens));
    card.appendChild(createElement('div', { className: 'pricing-model' }, pkg.model));
    const features = createElement('ul', { className: 'pricing-features' });
    pkg.features.forEach(f => {
      const li = createElement('li', {});
      li.innerHTML = iconCheck(14) + ' ' + f;
      features.appendChild(li);
    });
    card.appendChild(features);

    {
      const btns = createElement('div', { className: 'pricing-actions' });
      const wechatBtn = createElement('button', { className: 'btn btn-primary' }, '微信支付');
      wechatBtn.addEventListener('click', () => createOrder(pkg.id, 'wechat'));
      const alipayBtn = createElement('button', { className: 'btn btn-outline' }, '支付宝');
      alipayBtn.addEventListener('click', () => createOrder(pkg.id, 'alipay'));
      btns.appendChild(wechatBtn);
      btns.appendChild(alipayBtn);
      card.appendChild(btns);
    }
    grid.appendChild(card);
  });
  page.appendChild(grid);

  async function createOrder(plan, method) {
    try {
      const res = await paymentApi.createOrder(plan, method);
      // 检查是否为个人收款码模式
      if (res.wechat_qr_url || res.alipay_qr_url) {
        showPersonalQRModal(res);
        return;
      }
      if (method === 'wechat') {
        showQRCode(res.pay_url, res.order_no);
      } else {
        window.open(res.pay_url, '_blank');
        pollOrderStatus(res.order_no);
      }
    } catch (err) {
      showToast('创建订单失败：' + (err.message || '请先登录'), 'error');
    }
  }

  function showPersonalQRModal(order) {
    const modal = createElement('div', { className: 'qr-modal' });
    const qrImages = [];
    if (order.wechat_qr_url) qrImages.push(`<div style="text-align:center"><img src="${order.wechat_qr_url}" style="width:160px;height:160px;border-radius:10px;background:#fff;padding:8px" alt="微信收款码"><div style="font-size:.74rem;margin-top:4px">微信支付</div></div>`);
    if (order.alipay_qr_url) qrImages.push(`<div style="text-align:center"><img src="${order.alipay_qr_url}" style="width:160px;height:160px;border-radius:10px;background:#fff;padding:8px" alt="支付宝收款码"><div style="font-size:.74rem;margin-top:4px">支付宝</div></div>`);

    modal.innerHTML =
      `<div class="qr-modal-content">` +
        `<h3>请完成支付</h3>` +
        `<div style="font-size:1.8rem;font-weight:700;color:var(--accent-green);text-align:center;margin:8px 0">¥${order.amount_yuan || '--'}</div>` +
        `<div style="text-align:center;font-size:.82rem;color:var(--text-tertiary);margin-bottom:12px">${order.subject || ''}</div>` +
        `<div style="display:flex;gap:16px;justify-content:center;margin-bottom:16px">${qrImages.join('')}</div>` +
        `<button id="qrConfirmBtn" class="btn btn-primary" style="width:100%;margin-bottom:8px">我已完成支付</button>` +
        `<div style="text-align:center;font-size:.74rem;color:var(--text-tertiary)">订单号：${order.order_no}</div>` +
      `</div>`;
    document.body.appendChild(modal);

    const confirmBtn = modal.querySelector('#qrConfirmBtn');
    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = '正在确认…';
      try {
        const result = await paymentApi.confirmPayment(order.order_no);
        if (result.status === 'paid') {
          showToast('支付成功，权益已经到账', 'success');
          modal.remove();
          navigateTo('homepage');
        } else {
          showToast(result.message || '等待审核中', 'info');
        }
      } catch (err) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = '我已完成支付';
        showToast('确认失败：' + (err.message || ''), 'error');
      }
    });
  }

  function showQRCode(url, orderNo) {
    const modal = createElement('div', { className: 'qr-modal' });
    modal.innerHTML = `<div class="qr-modal-content"><h3>微信扫码支付</h3><div class="qr-placeholder">请用微信扫描支付码<br/><small>${url}</small><br/>订单号: ${orderNo}</div><button class="btn btn-outline">关闭</button></div>`;
    modal.querySelector('button').addEventListener('click', () => { modal.remove(); pollOrderStatus(orderNo); });
    document.body.appendChild(modal);
    pollOrderStatus(orderNo);
  }

  async function pollOrderStatus(orderNo) {
    for (let i = 0; i < 60; i++) {
      try {
        const res = await paymentApi.getOrderStatus(orderNo);
        if (res.status === 'paid') {
          showToast('支付成功，权益已经到账', 'success');
          navigateTo('homepage');
          return;
        }
      } catch {}
      await new Promise(r => setTimeout(r, 2000));
    }
  }

  return page;
}
