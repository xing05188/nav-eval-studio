export const DATASET_KINDS = [
  { value: 'r2r_ce', label: 'R2R-CE' },
  { value: 'rxr_ce', label: 'RxR-CE' },
  { value: 'custom', label: '自定义' },
]

export function kindLabel(kind) {
  return DATASET_KINDS.find((item) => item.value === kind)?.label || kind || '未知'
}

export function datasetStatus(status) {
  const map = {
    ready: { label: '可用', type: 'success' },
    missing: { label: '路径缺失', type: 'danger' },
    invalid: { label: '格式异常', type: 'warning' },
    unknown: { label: '未扫描', type: 'info' },
  }
  return map[status] || { label: status || '未知', type: 'info' }
}

export function formatBytes(value) {
  const size = Number(value) || 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

export function formatPercent(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(digits)}%`
}

export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return Number(value).toFixed(digits)
}

export function shortTime(value) {
  return value || '—'
}

const FAILURE_LABELS = {
  timeout: '超时',
  collision: '碰撞',
  off_track: '偏离轨迹',
  loop: '原地打转',
  stuck: '卡死',
  early_stop: '提前停止',
  goal_unreachable: '目标不可达',
  parse_error: '动作解析失败',
  oom: '显存不足',
  unknown: '未知',
}

export function failureLabel(reason) {
  return FAILURE_LABELS[reason] || reason || '未知'
}
