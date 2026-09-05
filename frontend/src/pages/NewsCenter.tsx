import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  BarChartOutlined,
  CloudOutlined,
  DollarOutlined,
  FireOutlined,
  HolderOutlined,
  ReloadOutlined,
  RiseOutlined,
  SearchOutlined,
  StarFilled,
  StarOutlined,
  StockOutlined,
  FallOutlined,
  SwapRightOutlined
} from '@ant-design/icons'
import { Alert, Button, Empty, Input, Space, Spin, Tabs, Tag, Typography } from 'antd'
import type { NewsItem } from '../api/news'
import { fetchNews } from '../api/news'

const { Text, Title } = Typography

type CategoryKey = 'tech' | 'finance'
type SortOrder = 'asc' | 'desc'
type ItemType = 'timeline' | 'article' | 'github' | 'stock' | 'leaderboard' | 'hot' | 'normal'

type PlatformConfig = {
  platform: string
  title: string
  icon: React.ReactNode
  type: ItemType
}

type PlatformState = {
  data: NewsItem[]
  loading: boolean
  error: string
  order?: SortOrder
}

const PLATFORM_GROUPS: Record<CategoryKey, { title: string; description: string; platforms: PlatformConfig[] }> = {
  tech: {
    title: '科技资讯',
    description: '科技行业最新资讯和趋势',
    platforms: [
      { platform: 'github', title: 'GitHub 趋势', icon: <CloudOutlined />, type: 'github' },
      { platform: '_36kr', title: '36氪', icon: <FireOutlined />, type: 'timeline' },
      { platform: 'ithome', title: 'IT之家', icon: <CloudOutlined />, type: 'timeline' },
      { platform: 'solidot', title: '奇客 Solidot', icon: <CloudOutlined />, type: 'timeline' },
      { platform: 'v2ex', title: 'V2EX', icon: <CloudOutlined />, type: 'timeline' },
      { platform: 'coolapk', title: '酷安', icon: <CloudOutlined />, type: 'timeline' },
      { platform: 'jin10', title: '金十数据', icon: <BarChartOutlined />, type: 'timeline' },
      { platform: 'pcbeta_windows', title: '远景论坛', icon: <CloudOutlined />, type: 'timeline' },
      { platform: 'juejin', title: '稀土掘金', icon: <CloudOutlined />, type: 'article' },
      { platform: 'sspai', title: '少数派', icon: <CloudOutlined />, type: 'article' },
      { platform: 'csdn', title: 'CSDN', icon: <CloudOutlined />, type: 'article' },
      { platform: 'fishpi', title: '摸鱼派', icon: <CloudOutlined />, type: 'article' },
      { platform: '_51cto', title: '51CTO', icon: <CloudOutlined />, type: 'normal' },
      { platform: 'nowcoder', title: '牛客网', icon: <CloudOutlined />, type: 'normal' }
    ]
  },
  finance: {
    title: '财经新闻',
    description: '金融市场和经济动态',
    platforms: [
      { platform: 'wallstreetcn_hot', title: '华尔街见闻热榜', icon: <DollarOutlined />, type: 'hot' },
      { platform: 'jqka', title: '同花顺要闻', icon: <DollarOutlined />, type: 'timeline' },
      { platform: 'cls_telegraph', title: '财联社', icon: <DollarOutlined />, type: 'timeline' },
      { platform: 'gelonghui', title: '格隆汇', icon: <DollarOutlined />, type: 'timeline' },
      { platform: 'wallstreetcn_live', title: '华尔街见闻直播', icon: <DollarOutlined />, type: 'timeline' },
      { platform: 'wallstreetcn_news', title: '华尔街见闻新闻', icon: <DollarOutlined />, type: 'timeline' },
      { platform: 'hotstock', title: '雪球热股', icon: <StockOutlined />, type: 'stock' },
      { platform: 'stock_sha', title: '沪A 涨跌幅榜', icon: <StockOutlined />, type: 'leaderboard' },
      { platform: 'stock_shb', title: '沪B 涨跌幅榜', icon: <StockOutlined />, type: 'leaderboard' },
      { platform: 'stock_sza', title: '深A 涨跌幅榜', icon: <StockOutlined />, type: 'leaderboard' },
      { platform: 'stock_szb', title: '深B 涨跌幅榜', icon: <StockOutlined />, type: 'leaderboard' },
      { platform: 'stock_cyb', title: '创业板 涨跌幅榜', icon: <StockOutlined />, type: 'leaderboard' },
      { platform: 'stock_zxb', title: '中小板 涨跌幅榜', icon: <StockOutlined />, type: 'leaderboard' },
      { platform: 'stock_hk', title: '港股 涨跌幅榜', icon: <StockOutlined />, type: 'leaderboard' },
      { platform: 'stock_us', title: '美股 涨跌幅榜', icon: <StockOutlined />, type: 'leaderboard' }
    ]
  }
}

const STORAGE_KEYS: Record<CategoryKey, string> = {
  tech: 'platform-orders-tech',
  finance: 'platform-orders-finance'
}

const FAVORITE_KEYS: Record<CategoryKey, string> = {
  tech: 'favorite-platforms-tech',
  finance: 'favorite-platforms-finance'
}

function loadPlatformOrder(category: CategoryKey) {
  const defaults = PLATFORM_GROUPS[category].platforms
  try {
    const raw = localStorage.getItem(STORAGE_KEYS[category])
    if (!raw) return defaults
    const saved = JSON.parse(raw) as string[]
    const map = new Map(defaults.map((item) => [item.platform, item]))
    const ordered = saved.map((key) => map.get(key)).filter(Boolean) as PlatformConfig[]
    const rest = defaults.filter((item) => !saved.includes(item.platform))
    return [...ordered, ...rest]
  } catch {
    return defaults
  }
}

function savePlatformOrder(category: CategoryKey, platforms: PlatformConfig[]) {
  localStorage.setItem(STORAGE_KEYS[category], JSON.stringify(platforms.map((item) => item.platform)))
}

function loadFavoritePlatforms(category: CategoryKey) {
  try {
    const raw = localStorage.getItem(FAVORITE_KEYS[category])
    if (!raw) return []
    return JSON.parse(raw) as string[]
  } catch {
    return []
  }
}

function saveFavoritePlatforms(category: CategoryKey, favorites: string[]) {
  localStorage.setItem(FAVORITE_KEYS[category], JSON.stringify(favorites))
}

function getRelativeTime(item: NewsItem) {
  const rawDate = item.extra?.date
  if (rawDate !== undefined && rawDate !== null) {
    const itemTime = typeof rawDate === 'number' ? rawDate : Number.parseInt(String(rawDate), 10)
    if (Number.isFinite(itemTime)) {
      const diff = Date.now() - itemTime
      const minutes = Math.floor(diff / (1000 * 60))
      const hours = Math.floor(diff / (1000 * 60 * 60))
      const days = Math.floor(diff / (1000 * 60 * 60 * 24))
      if (minutes < 1) return '刚刚'
      if (minutes < 60) return `${minutes}分钟前`
      if (hours < 24) return `${hours}小时前`
      if (days < 7) return `${days}天前`
      return new Date(itemTime).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
    }
  }
  return item.extra?.dateStr || item.publishedAt || ''
}

function formatNumber(num?: number) {
  if (num === undefined || num === null) return ''
  if (num >= 1000) return `${(num / 1000).toFixed(1)}k`
  return String(num)
}

function formatMarketCap(value?: string | number) {
  if (value === undefined || value === null) return '-'
  const num = Number(value)
  if (Number.isNaN(num)) return String(value)
  const abs = Math.abs(num)
  if (abs >= 1e12) return `${(num / 1e12).toFixed(2).replace(/\.00$/, '')}万亿`
  if (abs >= 1e8) return `${(num / 1e8).toFixed(2).replace(/\.00$/, '')}亿`
  if (abs >= 1e4) return `${(num / 1e4).toFixed(2).replace(/\.00$/, '')}万`
  return Intl.NumberFormat('zh-CN').format(num)
}

function percentTone(percent?: string | number) {
  const text = String(percent ?? '').trim()
  if (!text) return 'neutral'
  if (text.startsWith('-')) return 'down'
  if (text.startsWith('+') || /^\d/.test(text)) return 'up'
  return 'neutral'
}

function openNews(item: NewsItem) {
  if (item.url) window.open(item.url, '_blank', 'noopener,noreferrer')
}

function RankNumber({ index, hot }: { index: number; hot?: boolean }) {
  return (
    <span className={hot ? `mynews-rank mynews-rank-hot mynews-rank-${index + 1}` : 'mynews-rank'}>
      {index + 1}
    </span>
  )
}

function TimelineNewsItem({ item, index, isLast }: { item: NewsItem; index: number; isLast?: boolean }) {
  return (
    <div className="mynews-timeline-wrap" onClick={() => openNews(item)}>
      {!isLast ? <div className="mynews-timeline-line" /> : null}
      <div className="mynews-row mynews-timeline-row">
        <div className="mynews-time">{getRelativeTime(item)}</div>
        <div className="mynews-row-main">
          <div className="mynews-title" title={item.extra?.desc || item.title}>{item.title}</div>
          {item.extra?.hover ? <div className="mynews-subtitle" title={item.extra.hover}>{item.extra.hover}</div> : null}
        </div>
        <StarOutlined className="mynews-item-star" />
      </div>
    </div>
  )
}

function HotSearchItem({ item, index }: { item: NewsItem; index: number }) {
  return (
    <div className="mynews-row" onClick={() => openNews(item)}>
      <RankNumber index={index} hot />
      <div className="mynews-hot-main">
        <div className="mynews-title" title={item.title}>{item.title}</div>
        {item.extra?.num ? <span className="mynews-hot-num">{item.extra.num}</span> : null}
      </div>
      {item.extra?.icon?.url ? <img className="mynews-hot-icon" src={item.extra.icon.url} alt="" /> : null}
      <StarOutlined className="mynews-item-star" />
    </div>
  )
}

function ArticleReadItem({ item, index }: { item: NewsItem; index: number }) {
  return (
    <div className="mynews-row mynews-article-row" onClick={() => openNews(item)}>
      <RankNumber index={index} />
      <div className="mynews-row-main">
        <div className="mynews-title" title={item.extra?.desc || item.title}>{item.title}</div>
        <div className="mynews-article-meta">
          {item.extra?.view ? <span>{formatNumber(item.extra.view)} 浏览</span> : null}
          {item.extra?.like ? <span>{formatNumber(item.extra.like)} 互动</span> : null}
          {item.extra?.collect ? <span>{formatNumber(item.extra.collect)} 收藏</span> : null}
        </div>
      </div>
      <StarOutlined className="mynews-item-star" />
    </div>
  )
}

function GitHubNewsItem({ item, index }: { item: NewsItem; index: number }) {
  return (
    <div className="mynews-row" onClick={() => openNews(item)}>
      <RankNumber index={index} />
      <div className="mynews-row-main">
        <div className="mynews-github-line">
          <div className="mynews-title" title={item.title}>{item.title}</div>
          {item.extra?.info ? (
            <span className="mynews-star-info"><StarFilled /> {String(item.extra.info).replace('✰ ', '')}</span>
          ) : null}
        </div>
        {item.extra?.hover ? <div className="mynews-subtitle" title={item.extra.hover}>{item.extra.hover}</div> : null}
      </div>
      <StarOutlined className="mynews-item-star" />
    </div>
  )
}

function NormalNewsItem({ item, index }: { item: NewsItem; index: number }) {
  return (
    <div className="mynews-row" onClick={() => openNews(item)}>
      <RankNumber index={index} />
      <div className="mynews-row-main">
        <div className="mynews-title" title={item.title}>{item.title}</div>
      </div>
      <StarOutlined className="mynews-item-star" />
    </div>
  )
}

function StockNewsItem({ item, index }: { item: NewsItem; index: number }) {
  const info = String(item.extra?.info || '')
  const tone = info.startsWith('-') ? 'down' : 'up'
  return (
    <div className="mynews-row" onClick={() => openNews(item)}>
      <RankNumber index={index} />
      <div className="mynews-row-main">
        <div className="mynews-stock-line">
          <div className="mynews-title" title={item.title}>{item.title}</div>
          {info ? (
            <span className={`mynews-stock-value ${tone}`}>
              {info} {tone === 'down' ? <FallOutlined /> : <RiseOutlined />}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function StockLeaderboardItem({ item, index }: { item: NewsItem; index: number }) {
  const tone = percentTone(item.extra?.percent)
  return (
    <div className="mynews-row mynews-stock-board-row" onClick={() => openNews(item)}>
      <RankNumber index={index} />
      <div className="mynews-row-main">
        <div className="mynews-stock-board-line">
          <div className="mynews-title" title={item.title}>{item.title}</div>
          <div className="mynews-stock-badges">
            <span className="mynews-price">{item.extra?.current ?? '-'}</span>
            <span className={`mynews-change ${tone}`}>{item.extra?.change ?? '-'}</span>
            <span className={`mynews-change ${tone}`}>{item.extra?.percent ?? '-'}%</span>
            {tone === 'down' ? <FallOutlined className={`mynews-trend ${tone}`} /> : tone === 'up' ? <RiseOutlined className={`mynews-trend ${tone}`} /> : <SwapRightOutlined className="mynews-trend neutral" />}
          </div>
        </div>
        <div className="mynews-market-cap">市值 <span>{formatMarketCap(item.extra?.market_capital)}</span></div>
      </div>
    </div>
  )
}

function NewsItemView({ config, item, index, isLast }: { config: PlatformConfig; item: NewsItem; index: number; isLast?: boolean }) {
  switch (config.type) {
    case 'github':
      return <GitHubNewsItem item={item} index={index} />
    case 'timeline':
      return <TimelineNewsItem item={item} index={index} isLast={isLast} />
    case 'hot':
      return <HotSearchItem item={item} index={index} />
    case 'article':
      return <ArticleReadItem item={item} index={index} />
    case 'stock':
      return <StockNewsItem item={item} index={index} />
    case 'leaderboard':
      return <StockLeaderboardItem item={item} index={index} />
    default:
      return <NormalNewsItem item={item} index={index} />
  }
}

function NewsPlatformCard({
  config,
  state,
  isFavorited,
  onToggleFavorite,
  onRefresh,
  onDragStart,
  onDrop
}: {
  config: PlatformConfig
  state: PlatformState
  isFavorited: boolean
  onToggleFavorite: () => void
  onRefresh: (order?: SortOrder) => void
  onDragStart: () => void
  onDrop: () => void
}) {
  const isLeaderboard = config.type === 'leaderboard'
  return (
    <div
      className="mynews-card"
      draggable
      onDragStart={onDragStart}
      onDragOver={(event) => event.preventDefault()}
      onDrop={onDrop}
    >
      <div className="mynews-card-head">
        <div className="mynews-card-title">
          <span className="mynews-card-icon">{config.icon}</span>
          <span>{config.title}</span>
        </div>
        <div className="mynews-card-actions">
          <button className={`mynews-icon-btn ${isFavorited ? 'is-favorited' : ''}`} title="收藏整个平台" onClick={onToggleFavorite}>
            {isFavorited ? <StarFilled /> : <StarOutlined />}
          </button>
          {isLeaderboard ? (
            <>
              <button
                className={`mynews-icon-btn ${state.order !== 'asc' ? 'active-up' : ''}`}
                title="涨幅榜"
                onClick={() => onRefresh('desc')}
              >
                <RiseOutlined />
              </button>
              <button
                className={`mynews-icon-btn ${state.order === 'asc' ? 'active-down' : ''}`}
                title="跌幅榜"
                onClick={() => onRefresh('asc')}
              >
                <FallOutlined />
              </button>
            </>
          ) : null}
          <button className="mynews-icon-btn" title="刷新" onClick={() => onRefresh(state.order)}><ReloadOutlined /></button>
          <button className="mynews-icon-btn drag-handle" title="拖拽排序"><HolderOutlined /></button>
        </div>
      </div>

      <div className="mynews-card-body">
        {state.loading ? (
          <div className="mynews-loading"><Spin /></div>
        ) : state.error ? (
          <Alert type="error" showIcon message="加载失败" description={state.error} />
        ) : state.data.length ? (
          <div className="mynews-list">
            {state.data.slice(0, 50).map((item, index) => (
              <NewsItemView key={String(item.id || item.url || index)} config={config} item={item} index={index} isLast={index >= state.data.length - 1} />
            ))}
          </div>
        ) : (
          <div className="mynews-empty"><Empty description="暂无数据" /></div>
        )}
      </div>
    </div>
  )
}

export default function NewsCenter() {
  const [activeTab, setActiveTab] = useState<CategoryKey>('tech')
  const [query, setQuery] = useState('')
  const [techPlatforms, setTechPlatforms] = useState<PlatformConfig[]>(() => loadPlatformOrder('tech'))
  const [financePlatforms, setFinancePlatforms] = useState<PlatformConfig[]>(() => loadPlatformOrder('finance'))
  const [techFavorites, setTechFavorites] = useState<string[]>(() => loadFavoritePlatforms('tech'))
  const [financeFavorites, setFinanceFavorites] = useState<string[]>(() => loadFavoritePlatforms('finance'))
  const [states, setStates] = useState<Record<string, PlatformState>>({})
  const statesRef = useRef<Record<string, PlatformState>>({})
  const dragRef = useRef<{ category: CategoryKey; platform: string } | null>(null)

  const activePlatforms = activeTab === 'tech' ? techPlatforms : financePlatforms
  const activeFavorites = activeTab === 'tech' ? techFavorites : financeFavorites
  const activeConfig = PLATFORM_GROUPS[activeTab]

  const filteredPlatforms = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return activePlatforms
    return activePlatforms.filter((item) => item.title.toLowerCase().includes(keyword) || item.platform.toLowerCase().includes(keyword))
  }, [activePlatforms, query])

  const updateState = (platform: string, patch: Partial<PlatformState>) => {
    setStates((prev) => {
      const next = {
        ...prev,
        [platform]: {
          data: [],
          loading: false,
          error: '',
          ...prev[platform],
          ...patch
        }
      }
      statesRef.current = next
      return next
    })
  }

  const loadSingle = async (platform: string, order?: SortOrder) => {
    const nextOrder = order || statesRef.current[platform]?.order
    updateState(platform, { loading: true, error: '', order: nextOrder })
    try {
      const data = await fetchNews(platform, nextOrder, Date.now())
      updateState(platform, { data, loading: false, error: '', order: nextOrder })
    } catch (error: any) {
      updateState(platform, { loading: false, error: error?.message || '网络请求失败', order: nextOrder })
    }
  }

  const loadCategory = async (category: CategoryKey) => {
    const platforms = category === 'tech' ? techPlatforms : financePlatforms
    await Promise.allSettled(platforms.map((item) => loadSingle(item.platform, item.type === 'leaderboard' ? statesRef.current[item.platform]?.order || 'desc' : undefined)))
  }

  useEffect(() => {
    void loadCategory('tech')
    void loadCategory('finance')
  }, [])

  const refreshAll = () => {
    void loadCategory(activeTab)
  }

  const movePlatform = (category: CategoryKey, fromPlatform: string, toPlatform: string) => {
    const setter = category === 'tech' ? setTechPlatforms : setFinancePlatforms
    setter((prev) => {
      const list = [...prev]
      const fromIndex = list.findIndex((item) => item.platform === fromPlatform)
      const toIndex = list.findIndex((item) => item.platform === toPlatform)
      if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return prev
      const [moved] = list.splice(fromIndex, 1)
      list.splice(toIndex, 0, moved)
      savePlatformOrder(category, list)
      return list
    })
  }

  const toggleFavoritePlatform = (category: CategoryKey, platform: string) => {
    const favorites = category === 'tech' ? techFavorites : financeFavorites
    const setFavorites = category === 'tech' ? setTechFavorites : setFinanceFavorites
    const setPlatforms = category === 'tech' ? setTechPlatforms : setFinancePlatforms
    const hasFavorite = favorites.includes(platform)

    const nextFavorites = hasFavorite
      ? favorites.filter((item) => item !== platform)
      : [platform, ...favorites.filter((item) => item !== platform)]

    setFavorites(nextFavorites)
    saveFavoritePlatforms(category, nextFavorites)

    setPlatforms((prev) => {
      const list = [...prev]
      const index = list.findIndex((item) => item.platform === platform)
      if (index < 0) return prev
      const [target] = list.splice(index, 1)

      if (hasFavorite) {
        const favoriteSet = new Set(nextFavorites)
        const favoriteItems = list.filter((item) => favoriteSet.has(item.platform))
        const normalItems = list.filter((item) => !favoriteSet.has(item.platform))
        const nextList = [...favoriteItems, target, ...normalItems]
        savePlatformOrder(category, nextList)
        return nextList
      }

      const nextList = [target, ...list]
      savePlatformOrder(category, nextList)
      return nextList
    })
  }

  const itemCount = activePlatforms.reduce((sum, item) => sum + (states[item.platform]?.data.length || 0), 0)

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }} className="news-center-page mynews-page">
      <div className="mynews-page-title-block">
        <div>
          <Title level={2} className="page-title">{activeConfig.title}</Title>
          <Text className="page-description">{activeConfig.description}</Text>
          <div className="news-center-hero-tags">
            <Tag color="blue">{activePlatforms.length} 个平台</Tag>
            <Tag color="cyan">{itemCount} 条已加载内容</Tag>
            <Tag color="gold">可拖拽排序</Tag>
          </div>
        </div>
        <Button icon={<ReloadOutlined />} onClick={refreshAll}>刷新全部</Button>
      </div>

      <div className="mynews-toolbar">
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as CategoryKey)}
          items={[
            { key: 'tech', label: '科技资讯' },
            { key: 'finance', label: '财经新闻' }
          ]}
        />
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="筛选平台"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="news-center-search"
        />
      </div>

      <div className="mynews-grid">
        {filteredPlatforms.map((config) => (
          <NewsPlatformCard
            key={config.platform}
            config={config}
            state={states[config.platform] || { data: [], loading: false, error: '', order: config.type === 'leaderboard' ? 'desc' : undefined }}
            isFavorited={activeFavorites.includes(config.platform)}
            onToggleFavorite={() => toggleFavoritePlatform(activeTab, config.platform)}
            onRefresh={(order) => void loadSingle(config.platform, order)}
            onDragStart={() => {
              dragRef.current = { category: activeTab, platform: config.platform }
            }}
            onDrop={() => {
              if (dragRef.current && dragRef.current.category === activeTab) {
                movePlatform(activeTab, dragRef.current.platform, config.platform)
              }
              dragRef.current = null
            }}
          />
        ))}
      </div>
    </Space>
  )
}
