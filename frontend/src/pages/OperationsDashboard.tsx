import { useEffect, useMemo, useState } from 'react'
import {
  Radio,
  DatePicker,
  Table,
  Spin,
  Typography,
  message,
  Space,
} from 'antd'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import {
  SearchOutlined,
  MessageOutlined,
  UserOutlined,
  LikeOutlined,
  DislikeOutlined,
  DashboardOutlined,
} from '@ant-design/icons'
import api from '@/services/api'
import StatCard from '@/components/ui/StatCard'
import DataCard from '@/components/ui/DataCard'
import { useTranslation } from '@/i18n'
import { colors, radius, spacing, typography } from '@/styles/theme'

const { RangePicker } = DatePicker
const { Text, Title } = Typography

interface FeedbackSummary {
  positive: number
  negative: number
  total: number
}

interface TopKBItem {
  kb_id: string
  name: string
  search_count: number
  upload_count: number
  total: number
}

interface DailyTrendItem {
  date: string
  search_count: number
  chat_count: number
}

interface DashboardMetrics {
  search_count: number
  chat_count: number
  active_users: number
  feedback_summary: FeedbackSummary
  top_kbs: TopKBItem[]
  daily_trend: DailyTrendItem[]
}

type RangePreset = '7' | '30' | 'custom'

const SimpleLineChart = ({ data }: { data: DailyTrendItem[] }) => {
  if (data.length === 0) return null

  const width = 800
  const height = 260
  const padding = { top: 20, right: 30, bottom: 40, left: 50 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom

  const maxValue = Math.max(
    1,
    ...data.map((d) => Math.max(d.search_count, d.chat_count))
  )

  const xFor = (i: number) =>
    padding.left + (i / Math.max(1, data.length - 1)) * chartWidth
  const yFor = (v: number) =>
    padding.top + chartHeight - (v / maxValue) * chartHeight

  const searchPoints = data
    .map((d, i) => `${xFor(i)},${yFor(d.search_count)}`)
    .join(' ')
  const chatPoints = data
    .map((d, i) => `${xFor(i)},${yFor(d.chat_count)}`)
    .join(' ')

  const yTicks = [0, maxValue * 0.25, maxValue * 0.5, maxValue * 0.75, maxValue]
  const xTickCount = Math.min(data.length, 7)
  const xStep = Math.max(1, Math.floor(data.length / xTickCount))

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      style={{ width: '100%', height: 'auto', minHeight: 260 }}
      preserveAspectRatio="xMidYMid meet"
    >
      {/* grid lines */}
      {yTicks.map((t, i) => (
        <line
          key={`grid-${i}`}
          x1={padding.left}
          y1={yFor(t)}
          x2={width - padding.right}
          y2={yFor(t)}
          stroke={colors.border}
          strokeDasharray="4 4"
        />
      ))}
      {/* y axis labels */}
      {yTicks.map((t, i) => (
        <text
          key={`ylabel-${i}`}
          x={padding.left - 10}
          y={yFor(t) + 4}
          textAnchor="end"
          fontSize={12}
          fill={colors.textMuted}
        >
          {Math.round(t)}
        </text>
      ))}
      {/* x axis labels */}
      {data.map((d, i) =>
        i % xStep === 0 ? (
          <text
            key={`xlabel-${i}`}
            x={xFor(i)}
            y={height - 10}
            textAnchor="middle"
            fontSize={12}
            fill={colors.textMuted}
          >
            {d.date.slice(5)}
          </text>
        ) : null
      )}
      {/* lines */}
      <polyline
        fill="none"
        stroke={colors.accent}
        strokeWidth={2}
        points={searchPoints}
      />
      <polyline
        fill="none"
        stroke={colors.info}
        strokeWidth={2}
        points={chatPoints}
      />
      {/* points */}
      {data.map((d, i) => (
        <g key={`pt-${i}`}>
          <circle cx={xFor(i)} cy={yFor(d.search_count)} r={3} fill={colors.accent} />
          <circle cx={xFor(i)} cy={yFor(d.chat_count)} r={3} fill={colors.info} />
        </g>
      ))}
      {/* legend */}
      <g transform={`translate(${width - 140}, 12)`}>
        <rect width={130} height={46} rx={radius.sm} fill={colors.surface} stroke={colors.border} />
        <line x1={10} y1={18} x2={30} y2={18} stroke={colors.accent} strokeWidth={2} />
        <text x={36} y={22} fontSize={12} fill={colors.textSecondary}>
          搜索量
        </text>
        <line x1={10} y1={34} x2={30} y2={34} stroke={colors.info} strokeWidth={2} />
        <text x={36} y={38} fontSize={12} fill={colors.textSecondary}>
          问答量
        </text>
      </g>
    </svg>
  )
}

const OperationsDashboard = () => {
  const { t } = useTranslation()
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null)
  const [loading, setLoading] = useState(false)
  const [preset, setPreset] = useState<RangePreset>('7')
  const [customDates, setCustomDates] = useState<[Dayjs, Dayjs] | null>(null)

  const dateRange = useMemo(() => {
    const end = dayjs()
    let start = dayjs()
    if (preset === '7') {
      start = end.subtract(6, 'day')
    } else if (preset === '30') {
      start = end.subtract(29, 'day')
    } else if (customDates) {
      return { start: customDates[0], end: customDates[1] }
    } else {
      start = end.subtract(6, 'day')
    }
    return { start, end }
  }, [preset, customDates])

  const fetchMetrics = async () => {
    setLoading(true)
    try {
      const res = await api.get('/v1/operations/dashboard', {
        params: {
          start: dateRange.start.format('YYYY-MM-DD'),
          end: dateRange.end.format('YYYY-MM-DD'),
        },
      })
      setMetrics(res.data)
    } catch {
      message.error(t('operations.loadFailed') || '加载运营数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchMetrics()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange])

  const columns = [
    {
      title: t('operations.kbName') || '知识库',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: t('operations.searchCount') || '搜索次数',
      dataIndex: 'search_count',
      key: 'search_count',
      sorter: (a: TopKBItem, b: TopKBItem) => a.search_count - b.search_count,
    },
    {
      title: t('operations.uploadCount') || '上传次数',
      dataIndex: 'upload_count',
      key: 'upload_count',
      sorter: (a: TopKBItem, b: TopKBItem) => a.upload_count - b.upload_count,
    },
    {
      title: t('operations.total') || '合计',
      dataIndex: 'total',
      key: 'total',
      sorter: (a: TopKBItem, b: TopKBItem) => a.total - b.total,
    },
  ]

  return (
    <div>
      <Title level={4} style={{ marginTop: 0, marginBottom: spacing.lg, color: colors.textPrimary }}>
        <DashboardOutlined style={{ marginRight: spacing.sm, color: colors.accent }} />
        {t('nav.operations') || '运营看板'}
      </Title>

      <DataCard
        style={{ marginBottom: spacing.lg }}
        bodyStyle={{ padding: spacing.md }}
      >
        <Space wrap>
          <Radio.Group
            value={preset}
            onChange={(e) => setPreset(e.target.value as RangePreset)}
          >
            <Radio.Button value="7">{t('operations.last7Days') || '最近 7 天'}</Radio.Button>
            <Radio.Button value="30">{t('operations.last30Days') || '最近 30 天'}</Radio.Button>
            <Radio.Button value="custom">{t('operations.customRange') || '自定义'}</Radio.Button>
          </Radio.Group>
          {preset === 'custom' && (
            <RangePicker
              value={customDates}
              onChange={(dates) => {
                if (dates && dates[0] && dates[1]) {
                  setCustomDates([dates[0], dates[1]])
                } else {
                  setCustomDates(null)
                }
              }}
            />
          )}
          <Text type="secondary" style={{ fontSize: typography.sizes.sm }}>
            {dateRange.start.format('YYYY-MM-DD')} ~ {dateRange.end.format('YYYY-MM-DD')}
          </Text>
        </Space>
      </DataCard>

      {loading && (
        <div style={{ textAlign: 'center', padding: spacing.xl }}>
          <Spin />
        </div>
      )}

      {!loading && metrics && (
        <>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: spacing.lg,
              marginBottom: spacing.lg,
            }}
          >
            <StatCard
              icon={<SearchOutlined />}
              label={t('operations.searchCount') || '搜索量'}
              value={metrics.search_count}
            />
            <StatCard
              icon={<MessageOutlined />}
              label={t('operations.chatCount') || '问答量'}
              value={metrics.chat_count}
            />
            <StatCard
              icon={<UserOutlined />}
              label={t('operations.activeUsers') || '活跃用户'}
              value={metrics.active_users}
            />
            <StatCard
              icon={<LikeOutlined />}
              label={t('operations.positiveFeedback') || '好评'}
              value={metrics.feedback_summary.positive}
            />
            <StatCard
              icon={<DislikeOutlined />}
              label={t('operations.negativeFeedback') || '差评'}
              value={metrics.feedback_summary.negative}
            />
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
              gap: spacing.lg,
            }}
          >
            <DataCard
              title={t('operations.topKbs') || 'Top 知识库'}
              style={{ minHeight: 360 }}
            >
              <Table
                dataSource={metrics.top_kbs}
                columns={columns}
                rowKey="kb_id"
                pagination={false}
                size="small"
                locale={{ emptyText: t('operations.noData') || '暂无数据' }}
              />
            </DataCard>

            <DataCard
              title={t('operations.dailyTrend') || '日趋势'}
              style={{ minHeight: 360 }}
            >
              <SimpleLineChart data={metrics.daily_trend} />
            </DataCard>
          </div>
        </>
      )}
    </div>
  )
}

export default OperationsDashboard
