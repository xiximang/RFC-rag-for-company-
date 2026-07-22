import { useState } from 'react'
import { Tag, Button, Tooltip, Rate, Space, Typography, message } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined, CheckOutlined } from '@ant-design/icons'
import { colors, spacing, typography } from '@/styles/theme'

const { Text, Paragraph } = Typography

export interface Candidate {
  rank: number
  chunk_id?: string
  doc_id?: string
  content: string
  rerank_score?: number
  max_keyword_level?: string
  filtered?: boolean
}

interface CandidatePanelProps {
  candidates: Candidate[]
  messageId?: string
  onSubmitFeedback?: (payload: {
    ranking: number[]
    ratings: Record<number, number>
    chosen_rank: number
  }) => Promise<void> | void
  submitted?: boolean
}

/**
 * Rerank 候选展示与工程师交互面板。
 *
 * 五级兼容（前端侧）：
 * - content 直接展示后端给的降级值，filtered 候选标「已降级」且不提供查看原文入口；
 * - 前端不做任何权限判断，完全信任后端穿透结果。
 *
 * 工程师可上下移动候选调整排序、对每个候选打分（1-5 星），并提交排序反馈。
 */
const CandidatePanel = ({
  candidates,
  onSubmitFeedback,
  submitted = false,
}: CandidatePanelProps) => {
  // ranking 为候选 rank 的有序数组（首位=工程师认为最优）
  const [ranking, setRanking] = useState<number[]>(
    candidates.map((c) => c.rank)
  )
  const [ratings, setRatings] = useState<Record<number, number>>({})
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(submitted)

  if (!candidates || candidates.length === 0) return null

  const move = (index: number, dir: -1 | 1) => {
    const next = [...ranking]
    const target = index + dir
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    setRanking(next)
  }

  const byRank = new Map<number, Candidate>(candidates.map((c) => [c.rank, c]))

  const handleSubmit = async () => {
    if (!onSubmitFeedback) return
    setSubmitting(true)
    try {
      await onSubmitFeedback({
        ranking,
        ratings,
        chosen_rank: ranking[0],
      })
      setDone(true)
    } catch {
      message.error('候选反馈提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        marginTop: spacing.md,
        paddingTop: spacing.sm,
        borderTop: `1px solid ${colors.border}`,
      }}
    >
      <Text strong style={{ fontSize: typography.sizes.sm, color: 'inherit' }}>
        检索候选（工程师可参与排序）
      </Text>
      <div style={{ marginTop: spacing.xs, display: 'flex', flexDirection: 'column', gap: spacing.xs }}>
        {ranking.map((rank, index) => {
          const c = byRank.get(rank)
          if (!c) return null
          const filtered = !!c.filtered
          return (
            <div
              key={rank}
              style={{
                border: `1px solid ${colors.borderLight}`,
                borderRadius: 4,
                padding: spacing.xs,
                background: filtered ? 'rgba(255,77,79,0.06)' : 'transparent',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Space size={4}>
                  <Tag color={index === 0 ? 'success' : 'default'}>#{index + 1}</Tag>
                  <Text type="secondary" style={{ fontSize: typography.sizes.xs }}>
                    rank {c.rank} · rerank {c.rerank_score?.toFixed(2) ?? '-'}
                  </Text>
                  {filtered && (
                    <Tag color="error" style={{ marginLeft: 4 }}>
                      已降级
                    </Tag>
                  )}
                </Space>
                <Space size={2}>
                  <Button
                    type="text"
                    size="small"
                    icon={<ArrowUpOutlined />}
                    disabled={index === 0 || done}
                    onClick={() => move(index, -1)}
                  />
                  <Button
                    type="text"
                    size="small"
                    icon={<ArrowDownOutlined />}
                    disabled={index === ranking.length - 1 || done}
                    onClick={() => move(index, 1)}
                  />
                </Space>
              </div>
              <Tooltip title={filtered ? '内容涉及更高敏感级别，已过滤' : c.content} placement="topLeft">
                <Paragraph
                  style={{
                    margin: `${spacing.xs} 0 0`,
                    fontSize: typography.sizes.xs,
                    color: filtered ? colors.textMuted : 'inherit',
                  }}
                  ellipsis={{ rows: 2 }}
                >
                  {c.content}
                </Paragraph>
              </Tooltip>
              {!filtered && (
                <div style={{ marginTop: 4 }}>
                  <Rate
                    count={5}
                    value={ratings[rank] ?? 0}
                    onChange={(v) => setRatings((prev) => ({ ...prev, [rank]: v }))}
                    disabled={done}
                    style={{ fontSize: 12 }}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
      {onSubmitFeedback && (
        <div style={{ marginTop: spacing.xs, textAlign: 'right' }}>
          <Button
            type="primary"
            size="small"
            icon={<CheckOutlined />}
            loading={submitting}
            disabled={done}
            onClick={handleSubmit}
          >
            {done ? '已反馈' : '提交排序反馈'}
          </Button>
        </div>
      )}
    </div>
  )
}

export default CandidatePanel
