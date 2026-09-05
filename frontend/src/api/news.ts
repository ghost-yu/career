import { api } from './client'

export type NewsItem = {
  id: string
  title: string
  url: string
  content?: string
  source?: string
  publishedAt?: string
  image?: string
  platform?: string
  tags?: string[]
  extra?: {
    info?: string
    hover?: string
    date?: string | number
    dateStr?: string
    rank?: number
    icon?: {
      url: string
      scale?: number
      info?: string
    }
    num?: number
    view?: number
    like?: number
    comment?: number | { content: string; avatar: string }
    collect?: number
    score?: number
    desc?: string
    current?: number
    percent?: string
    change?: string
    market_capital?: string
  }
}

const newsCache = new Map<string, NewsItem[]>()
let preloadStarted = false

function cacheKey(platform: string, order?: 'asc' | 'desc') {
  return `${platform}:${order || 'default'}`
}

export async function fetchNews(platform: string, order?: 'asc' | 'desc', timestamp?: number) {
  const key = cacheKey(platform, order)
  if (!timestamp && newsCache.has(key)) {
    return newsCache.get(key) || []
  }
  const baseURL = String(import.meta.env.VITE_NEWS_API_BASE_URL || '').trim() || undefined
  const response = await api.get<NewsItem[] | { code?: number; msg?: string; data?: NewsItem[] }>('/news', {
    ...(baseURL ? { baseURL } : {}),
    params: {
      platform,
      ...(order ? { order } : {}),
      ...(timestamp ? { _t: timestamp } : {})
    }
  })
  const payload = response.data
  const items = Array.isArray(payload) ? payload : payload?.data || []
  newsCache.set(key, items)
  return items
}

export function preloadNews() {
  if (preloadStarted) return
  preloadStarted = true
  const platforms: Array<{ platform: string; order?: 'asc' | 'desc' }> = [
    { platform: 'github' },
    { platform: '_36kr' },
    { platform: 'ithome' },
    { platform: 'wallstreetcn_hot' },
    { platform: 'jqka' },
    { platform: 'cls_telegraph' },
    { platform: 'stock_us', order: 'desc' },
    { platform: 'stock_hk', order: 'desc' }
  ]
  void Promise.allSettled(platforms.map(item => fetchNews(item.platform, item.order)))
}
