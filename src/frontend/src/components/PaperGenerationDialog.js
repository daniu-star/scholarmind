import { paperPipelineApi } from '../services/paperPipelineApi.js';
import { state } from '../app/store.js';
import { iconClose, iconSparkles, iconCheck } from '../utils/icons.js';

const RESEARCH_TYPES = [
  { id: 'qualitative', name: '质化研究' },
  { id: 'quantitative', name: '量化研究' },
  { id: 'computational', name: '计算社会科学' },
  { id: 'mixed', name: '混合方法' },
  { id: 'interview_report', name: '访谈报告' },
  { id: 'theoretical', name: '理论建构' },
];

const JOURNAL_STYLES = [
  { id: 'xwycbyj', name: '新闻与传播研究' },
  { id: 'gjxwj', name: '国际新闻界' },
  { id: 'xwdx', name: '新闻大学' },
  { id: 'shxyj', name: '社会学研究' },
];

export function showPaperGenerationDialog({ onStarted, onCancel } = {}) {
  const existing = document.getElementById('paperGenDialog');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'paperGenDialog';
  overlay.className = 'topic-dialog-overlay';
  overlay.innerHTML =
    '<div class="topic-dialog-card paper-gen-card">' +
      '<div class="topic-dialog-decoration"></div>' +
      '<div class="topic-dialog-header">' +
        '<div class="topic-dialog-icon-wrap"><span class="topic-dialog-icon-emoji">' + iconSparkles(20) + '</span></div>' +
        '<h3 class="topic-dialog-title">一键生成论文</h3>' +
        '<button class="paper-gen-close" aria-label="关闭">' + iconClose(18) + '</button>' +
      '</div>' +
      '<p class="topic-dialog-desc">基于 13 Agent 循环式论文精炼 Pipeline（v7.0 GAN 对抗评分），将研究主题打磨至顶刊发表水平</p>' +
      '<div class="paper-gen-form">' +
        '<div class="paper-gen-field">' +
          '<label class="paper-gen-label">研究主题 <span class="paper-gen-required">*</span></label>' +
          '<textarea class="paper-gen-textarea" rows="3" placeholder="例如：算法推荐对信息茧房的影响机制研究" id="pg-topic"></textarea>' +
        '</div>' +
        '<div class="paper-gen-field">' +
          '<label class="paper-gen-label">研究类型</label>' +
          '<div class="paper-gen-chips" id="pg-research-type">' +
            RESEARCH_TYPES.map((t, i) =>
              '<button class="paper-gen-chip' + (i === 0 ? ' selected' : '') + '" data-value="' + t.id + '">' + t.name + '</button>'
            ).join('') +
          '</div>' +
        '</div>' +
        '<div class="paper-gen-field">' +
          '<label class="paper-gen-label">期刊格式</label>' +
          '<div class="paper-gen-chips" id="pg-journal-style">' +
            JOURNAL_STYLES.map((j, i) =>
              '<button class="paper-gen-chip' + (i === 0 ? ' selected' : '') + '" data-value="' + j.id + '">' + j.name + '</button>'
            ).join('') +
          '</div>' +
        '</div>' +
        '<div class="paper-gen-row">' +
          '<div class="paper-gen-field paper-gen-field-half">' +
            '<label class="paper-gen-label">字数目标</label>' +
            '<input type="number" class="paper-gen-input" id="pg-words" value="15000" min="3000" max="50000" step="500">' +
          '</div>' +
          '<div class="paper-gen-field paper-gen-field-half">' +
            '<label class="paper-gen-label">最大轮次</label>' +
            '<input type="number" class="paper-gen-input" id="pg-rounds" value="5" min="1" max="10">' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="paper-gen-actions">' +
        '<button class="btn btn-ghost paper-gen-cancel">取消</button>' +
        '<button class="btn btn-primary paper-gen-start">' +
          '<span class="paper-gen-start-text">启动 Pipeline</span>' +
        '</button>' +
      '</div>' +
      '<div class="paper-gen-status" id="pg-status" style="display:none;"></div>' +
    '</div>';

  document.body.appendChild(overlay);

  const card = overlay.querySelector('.paper-gen-card');
  const closeBtn = overlay.querySelector('.paper-gen-close');
  const cancelBtn = overlay.querySelector('.paper-gen-cancel');
  const startBtn = overlay.querySelector('.paper-gen-start');
  const startText = overlay.querySelector('.paper-gen-start-text');
  const statusEl = overlay.querySelector('#pg-status');

  let selectedResearchType = RESEARCH_TYPES[0].id;
  let selectedJournalStyle = JOURNAL_STYLES[0].id;

  overlay.querySelectorAll('#pg-research-type .paper-gen-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      overlay.querySelectorAll('#pg-research-type .paper-gen-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      selectedResearchType = chip.dataset.value;
    });
  });

  overlay.querySelectorAll('#pg-journal-style .paper-gen-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      overlay.querySelectorAll('#pg-journal-style .paper-gen-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      selectedJournalStyle = chip.dataset.value;
    });
  });

  function close() {
    if (overlay.parentNode) overlay.remove();
    if (onCancel) onCancel();
  }

  closeBtn.addEventListener('click', close);
  cancelBtn.addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

  startBtn.addEventListener('click', async () => {
    const topic = overlay.querySelector('#pg-topic').value.trim();
    if (!topic) {
      const ta = overlay.querySelector('#pg-topic');
      ta.style.animation = 'shake 0.4s ease';
      setTimeout(() => { ta.style.animation = ''; }, 400);
      ta.focus();
      return;
    }

    const words = parseInt(overlay.querySelector('#pg-words').value, 10) || 15000;
    const rounds = parseInt(overlay.querySelector('#pg-rounds').value, 10) || 5;
    const sessionId = 'pg-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);

    startBtn.disabled = true;
    startText.textContent = '启动中...';
    statusEl.style.display = '';
    statusEl.className = 'paper-gen-status paper-gen-status-loading';
    statusEl.innerHTML = '<span class="paper-gen-spinner"></span>正在启动 13 Agent Pipeline...';

    try {
      // P1-T2/T4 修复：guidance_data 字段名对齐后端（topic 而非 research_topic）；
      // discipline 从 state 动态读取，避免硬编码 'humanities'（后端 Literal 不支持，会 422）
      // 后端支持的 discipline: communication/journalism/sociology/psychology/education/literature/history/management/economics
      const discipline = state.discipline || 'communication';
      const res = await paperPipelineApi.startPipeline({
        session_id: sessionId,
        agent_id: 'architect',
        guidance_data: {
          topic: topic,                // P1-T2: 后端 validator 要求 topic 非空字符串
          user_target_words: words,    // 保留：后端 dict 接受任意附加字段
        },
        discipline: discipline,        // P1-T4: 从 state 动态读取
        research_type: selectedResearchType,
        journal_style: selectedJournalStyle,
        max_rounds: rounds,
        pass_threshold: 90,
      });

      statusEl.className = 'paper-gen-status paper-gen-status-success';
      statusEl.innerHTML = iconCheck(16) + ' Pipeline 已启动！ID: ' + (res.pipeline_id || '').slice(0, 12) + '...';

      startText.textContent = '已启动';
      setTimeout(() => {
        close();
        if (onStarted) onStarted(res);
      }, 1500);
    } catch (err) {
      statusEl.className = 'paper-gen-status paper-gen-status-error';
      statusEl.textContent = '启动失败: ' + (err.message || '未知错误');
      startBtn.disabled = false;
      startText.textContent = '重试';
    }
  });

  requestAnimationFrame(() => card.classList.add('topic-dialog-card-in'));
}
