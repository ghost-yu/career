export function formatNumber(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === '') return '-'
  const n = Number(value)
  if (Number.isNaN(n)) return String(value)
  return new Intl.NumberFormat('zh-CN').format(n)
}

export function formatCurrency(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === '') return '-'
  const n = Number(value)
  if (Number.isNaN(n)) return String(value)
  return `¥${new Intl.NumberFormat('zh-CN').format(n)}`
}

export function formatMonthlySalary(min?: number | null, max?: number | null, period?: string | null) {
  if (min == null && max == null) return '面议'
  const suffix = period === 'year' ? '（折算月薪）' : period === 'day' ? '（日薪折算）' : period === 'hour' ? '（时薪折算）' : '/月'
  if (min != null && max != null && min !== max) return `${formatCurrency(min)} - ${formatCurrency(max)} ${suffix}`
  return `${formatCurrency(min ?? max)} ${suffix}`
}

export function percent(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '-'
  return `${Math.round(value)}%`
}

export function toArray<T = any>(value: any): T[] {
  if (Array.isArray(value)) return value
  return []
}

export function taskBadgeClass(status?: string) {
  const s = (status || '').toUpperCase()
  if (s === 'SUCCESS') return 'badge-success'
  if (s === 'FAILED') return 'badge-danger'
  if (s === 'RUNNING') return 'badge-primary'
  return 'badge-warning'
}

export function methodBadgeClass(method?: string) {
  const m = (method || '').toUpperCase()
  if (m === 'GET') return 'badge-primary'
  if (m === 'POST') return 'badge-success'
  if (m === 'PUT' || m === 'PATCH') return 'badge-warning'
  if (m === 'DELETE') return 'badge-danger'
  return 'badge-secondary'
}
