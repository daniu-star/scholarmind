// R2-T22 · 真实数据图表面板（只做表单与展示，取数/提交由页面负责）
//
// 设计约束（对应 PRD FR-13 / R2_INTERFACE_SPEC §2）：
// * 只允许在「已打开文档版本」的数值表上出图，列名必须由用户显式确认，
//   不做猜测式自动选列；
// * 开关关闭或能力不可用时**禁用按钮并写明原因**，不提供占位图；
// * 结果只展示后端返回的 validation（来源/行数/列映射/值域/摘要），
//   前端不自行计算任何数值，避免出现与后端不一致的“看起来对”的图。
import { createElement } from '../../utils/dom.js';
import {
  button,
  keyValue,
  labeledField,
  notice,
  pill,
  shortId,
} from './shared.js';

// 与后端 src/backend/services/chart_service.py 的 CHART_NAMES 保持一致；
// 后端只注册这 12 种灰阶学术风格图表（不含 bar/line/pie 等基础类型）。
export const CHART_TYPE_OPTIONS = [
  ['gradient_area', '梯度面积图'],
  ['ribbon', '缎带图'],
  ['violin', '小提琴图'],
  ['swarm', '蜂群图'],
  ['scatter_density', '散点密度图'],
  ['bubble_kde', '气泡散点+KDE图'],
  ['parallel', '平行坐标图'],
  ['contour', '等高线地形图'],
  ['surface3d', '3D 地形图'],
  ['alluvial', '冲积图'],
  ['chord', '和弦图'],
  ['heatmap_dendro', '热力聚类图'],
];

const DEFAULT_VALUES = {
  chartType: 'gradient_area',
  tableIndex: 0,
  xColumn: '',
  yColumns: '',
  title: '',
};

function select(options, value, { onChange, disabled }) {
  const el = createElement('select', {
    className: 'rw-input',
    disabled: disabled ? 'disabled' : undefined,
  });
  options.forEach(([key, label]) => {
    const opt = createElement('option', { value: key }, label);
    if (key === value) opt.selected = true;
    el.appendChild(opt);
  });
  if (onChange && !disabled) el.addEventListener('change', () => onChange(el.value));
  return el;
}

function textInput(value, { onChange, placeholder, disabled }) {
  const el = createElement('input', {
    className: 'rw-input',
    type: 'text',
    value: value || '',
    placeholder: placeholder || '',
  });
  if (disabled) el.disabled = true;
  if (onChange && !disabled) {
    el.addEventListener('input', () => onChange(el.value));
  }
  return el;
}

function rangeRows(validation) {
  const ranges = validation?.value_ranges || {};
  return Object.entries(ranges).map(([column, range]) => [
    `值域 · ${column}`,
    range && Number.isFinite(range.min) && Number.isFinite(range.max)
      ? `${range.min} – ${range.max}`
      : '—',
  ]);
}

/**
 * @param {object} options
 * @param {string[]} [options.columns]  当前版本第一张数值表的列名（表格表头）
 * @param {number} [options.tableCount] 当前版本可识别的表格数量
 * @param {string} [options.disabledReason] 非空即禁用生成按钮并展示原因
 * @param {object} [options.values]     {chartType,xColumn,yColumns,title}
 * @param {object|null} [options.result] {blobUrl,validation,artifactId,filename}
 * @param {string} [options.error]
 * @param {boolean} [options.loading]
 * @param {(patch:object)=>void} [options.onChange]
 * @param {()=>void} [options.onGenerate]
 */
export function ChartPanel({
  columns = [],
  tables = [],
  tableCount = 0,
  disabledReason = '',
  values = DEFAULT_VALUES,
  result = null,
  error = '',
  loading = false,
  onChange = () => {},
  onGenerate = () => {},
} = {}) {
  const current = { ...DEFAULT_VALUES, ...(values || {}) };
  const disabled = Boolean(disabledReason) || loading;
  const card = createElement('section', { className: 'rw-card rw-chart-panel' });

  const head = createElement('div', { className: 'rw-card-head' });
  head.appendChild(
    createElement('h3', { className: 'rw-card-title' }, '真实数据图表')
  );
  head.appendChild(
    pill(
      disabledReason ? '不可用' : tableCount > 0 ? `识别到 ${tableCount} 张表` : '待识别表格',
      disabledReason ? 'red' : tableCount > 0 ? 'green' : 'gray'
    )
  );
  card.appendChild(head);

  card.appendChild(
    createElement(
      'p',
      { className: 'rw-card-sub' },
      '只读取当前文档版本里的数值表，按你确认的列出图；校验信息（来源、行数、值域、摘要）随成果一起返回。'
    )
  );

  // 1. 能力/表格状态：不可用或没有表时，明确说明原因，而不是给一个点了没反应的按钮。
  if (disabledReason) {
    card.appendChild(
      notice({ tone: 'amber', title: '图表能力当前不可用', text: disabledReason })
    );
  } else if (tableCount === 0) {
    card.appendChild(
      notice({
        tone: 'gray',
        title: '当前版本没有可识别的数值表',
        text: '上传含数值表的 Markdown/CSV/XLSX 文档后，这里会列出可选的列名。',
      })
    );
  }

  // 2. 表单
  const grid = createElement('div', { className: 'rw-chart-form' });

  // 多张表时让用户显式选表：分类表交给后端只会 422，不猜。
  if (tables.length > 1) {
    const tableOptions = tables.map((item) => [
      String(item.index),
      `表 ${item.index + 1}（${item.columns.join(' / ').slice(0, 40)}）${item.numeric ? '' : ' · 非全数值'}`,
    ]);
    grid.appendChild(
      labeledField(
        '表格',
        select(tableOptions, String(current.tableIndex ?? 0), {
          disabled: Boolean(disabledReason),
          onChange: (tableIndex) => onChange({ tableIndex: Number(tableIndex) }),
        }),
        '只对全数值表出图；分类表会被后端拒绝'
      )
    );
  }

  grid.appendChild(
    labeledField(
      '图表类型',
      select(CHART_TYPE_OPTIONS, current.chartType, {
        disabled: Boolean(disabledReason),
        onChange: (chartType) => onChange({ chartType }),
      }),
      '后端只提供 PRD 认定的 12 种灰阶学术风格图表'
    )
  );

  const columnOptions = [
    ['', '请选择列'],
    ...columns.map((name) => [name, name]),
  ];
  grid.appendChild(
    labeledField(
      '横轴（X）',
      columns.length
        ? select(columnOptions, current.xColumn, {
            disabled: Boolean(disabledReason),
            onChange: (xColumn) => onChange({ xColumn }),
          })
        : textInput(current.xColumn, {
            disabled: Boolean(disabledReason),
            placeholder: '列名，如 年份',
            onChange: (xColumn) => onChange({ xColumn }),
          }),
      columns.length ? '' : '没有读到表头时请手动填写列名'
    )
  );

  grid.appendChild(
    labeledField(
      '纵轴（Y，逗号分隔，最多 8 列）',
      textInput(current.yColumns, {
        disabled: Boolean(disabledReason),
        placeholder: '如 论文数,平均页数',
        onChange: (yColumns) => onChange({ yColumns }),
      }),
      '多列会按同一横轴画多系列'
    )
  );

  grid.appendChild(
    labeledField(
      '标题（可选）',
      textInput(current.title, {
        disabled: Boolean(disabledReason),
        placeholder: '图表标题',
        onChange: (title) => onChange({ title }),
      })
    )
  );

  card.appendChild(grid);

  const actions = createElement('div', { className: 'rw-card-actions' });
  actions.appendChild(
    button(loading ? '生成中…' : '生成图表', {
      tone: 'primary',
      disabled,
      title: disabledReason || '按当前列生成 PNG 图表',
      onClick: onGenerate,
    })
  );
  card.appendChild(actions);

  if (error) {
    card.appendChild(notice({ tone: 'red', title: '生成失败', text: error }));
  }

  // 3. 结果：图 + 可复算的校验信息
  if (result && result.blobUrl) {
    const resultBox = createElement('div', { className: 'rw-chart-result' });
    const img = createElement('img', {
      className: 'rw-chart-image',
      src: result.blobUrl,
      alt: current.title || '真实数据图表',
    });
    resultBox.appendChild(img);

    const validation = result.validation || {};
    const rows = [
      ['成果 ID', result.artifactId ? shortId(result.artifactId, 14) : '—'],
      ['来源版本', validation.source_document_version_id || '—'],
      ['表格序号', validation.table_index ?? 0],
      ['行数', validation.row_count ?? '—'],
      ['列映射', `${validation.x_column || current.xColumn || '—'} → ${(validation.y_columns || []).join(', ') || current.yColumns || '—'}`],
      ...rangeRows(validation),
      ['数据摘要', validation.data_digest ? shortId(validation.data_digest, 16) : '—'],
      ['PNG 摘要', validation.png_sha256 ? shortId(validation.png_sha256, 16) : '—'],
      ['渲染校验', validation.render_verified === true ? '重开校验通过' : '—'],
      ['文件大小', result.bytes ? `${Math.round(result.bytes / 1024)} KB` : '—'],
    ];
    resultBox.appendChild(keyValue(rows));
    card.appendChild(resultBox);
  }

  return card;
}

export default ChartPanel;
