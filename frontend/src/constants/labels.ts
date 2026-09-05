export const jobFamilyLabelMap: Record<string, string> = {
  backend: '后端开发',
  frontend: '前端开发',
  ai: '人工智能',
  data: '数据开发',
  qa: '测试质量',
  ops: '运维云平台',
  product: '产品运营',
  design: '设计体验',
  security: '网络安全',
  implementation: '实施交付',
  embedded: '嵌入式',
  mobile: '移动开发',
  general: '综合方向'
}

export const levelLabelMap: Record<string, string> = {
  junior: '初级/校招',
  mid: '中级',
  senior: '高级/资深',
  lead: '负责人/专家'
}

export const familyOptions = [
  { label: '全部', value: '' },
  { label: '后端开发', value: 'backend' },
  { label: '前端开发', value: 'frontend' },
  { label: '人工智能', value: 'ai' },
  { label: '数据开发', value: 'data' },
  { label: '测试质量', value: 'qa' },
  { label: '运维云平台', value: 'ops' },
  { label: '产品运营', value: 'product' },
  { label: '设计体验', value: 'design' },
  { label: '网络安全', value: 'security' },
  { label: '实施交付', value: 'implementation' },
  { label: '嵌入式', value: 'embedded' },
  { label: '移动开发', value: 'mobile' },
  { label: '综合方向', value: 'general' }
]

export const familyChoiceOptions = familyOptions.filter(item => item.value)

const aliasMap: Record<string, string> = {
  '后端': 'backend',
  '后端开发': 'backend',
  '前端': 'frontend',
  '前端开发': 'frontend',
  '人工智能': 'ai',
  '算法': 'ai',
  '数据': 'data',
  '数据开发': 'data',
  '测试': 'qa',
  '测试质量': 'qa',
  '运维': 'ops',
  '运维云平台': 'ops',
  '产品': 'product',
  '产品运营': 'product',
  '设计': 'design',
  '设计体验': 'design',
  '安全': 'security',
  '网络安全': 'security',
  '实施': 'implementation',
  '实施交付': 'implementation',
  '嵌入式': 'embedded',
  '移动': 'mobile',
  '移动开发': 'mobile',
  '综合': 'general',
  '综合方向': 'general'
}

export function normalizeFamily(value?: string) {
  if (!value) return ''
  const raw = String(value).trim()
  return aliasMap[raw] || raw
}

export function familyLabel(value?: string, fallback = '综合方向') {
  const key = normalizeFamily(value)
  if (!key) return fallback
  return jobFamilyLabelMap[key] || value || fallback
}

export function levelLabel(value?: string, fallback = '中级') {
  if (!value) return fallback
  return levelLabelMap[value] || value
}
