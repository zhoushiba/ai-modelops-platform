/** 展示层格式化工具：状态标签、时间、体积、百分比、任务类型文案。 */

export function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function formatShortTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function formatPercent(value?: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

export function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toLocaleString('zh-CN')
}

export function formatBytes(bytes?: number | null): string {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

export function formatDuration(ms?: number | null): string {
  if (!ms) return '—'
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return `${minutes}m ${seconds}s`
}

export function truncate(text?: string | null, max = 80): string {
  if (!text) return '—'
  return text.length > max ? `${text.slice(0, max)}…` : text
}

const JOB_STATUS: Record<string, { text: string; type: 'info' | 'primary' | 'success' | 'warning' | 'danger' }> = {
  queued: { text: '排队中', type: 'info' },
  running: { text: '训练中', type: 'primary' },
  succeeded: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  canceled: { text: '已取消', type: 'warning' },
}

const DEPLOY_STATUS: Record<string, { text: string; type: 'info' | 'primary' | 'success' | 'warning' | 'danger' }> = {
  running: { text: '运行中', type: 'success' },
  starting: { text: '启动中', type: 'warning' },
  stopped: { text: '已停止', type: 'info' },
  failed: { text: '异常', type: 'danger' },
}

const MODEL_STATUS: Record<string, { text: string; type: 'info' | 'primary' | 'success' | 'warning' | 'danger' }> = {
  staging: { text: '预发布', type: 'warning' },
  production: { text: '生产', type: 'success' },
  archived: { text: '已归档', type: 'info' },
}

export function jobStatus(status?: string) {
  return JOB_STATUS[status || ''] || { text: status || '未知', type: 'info' as const }
}

export function deployStatus(status?: string) {
  return DEPLOY_STATUS[status || ''] || { text: status || '未知', type: 'info' as const }
}

export function modelStatus(status?: string) {
  return MODEL_STATUS[status || ''] || { text: status || '未知', type: 'info' as const }
}

export function taskTypeLabel(taskType?: string): string {
  if (taskType === 'text_classification') return '文本分类'
  if (taskType === 'rag_corpus') return 'RAG 知识库'
  return taskType || '—'
}

/** 简单抽样：把数值序列压缩成给定数量的柱子（用于无依赖的迷你柱状图）。 */
export function toBars(values: number[], maxBars = 14): number[] {
  if (values.length <= maxBars) return values
  const size = Math.ceil(values.length / maxBars)
  const result: number[] = []
  for (let i = 0; i < values.length; i += size) {
    result.push(values.slice(i, i + size).reduce((a, b) => a + b, 0))
  }
  return result
}

export interface MiniBar {
  label: string
  value: number
  height: number
}

/** 带标签的迷你柱状图数据：超过 maxBars 时按桶求和，高度是相对最大值的百分比。 */
export function toLabeledBars(points: { label: string; value: number }[], maxBars = 14): MiniBar[] {
  if (!points.length) return []
  const size = points.length <= maxBars ? 1 : Math.ceil(points.length / maxBars)
  const merged: { label: string; value: number }[] = []
  for (let i = 0; i < points.length; i += size) {
    const chunk = points.slice(i, i + size)
    merged.push({ label: chunk[0].label, value: chunk.reduce((sum, point) => sum + point.value, 0) })
  }
  const max = Math.max(1, ...merged.map((point) => point.value))
  return merged.map((point) => ({
    ...point,
    height: Math.max(4, Math.round((point.value / max) * 100)),
  }))
}
