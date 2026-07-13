import { useEffect, useState, useRef, useMemo } from 'react'
import {
  Input,
  Button,
  Select,
  Tag,
  List,
  Typography,
  Space,
  message,
  Checkbox,
  Spin,
  Tooltip,
  Popconfirm,
} from 'antd'
import {
  DeleteOutlined,
  LikeOutlined,
  DislikeOutlined,
  PlusOutlined,
  SendOutlined,
  MessageOutlined,
  SettingOutlined,
  BookOutlined,
} from '@ant-design/icons'
import api from '@/services/api'
import DataCard from '@/components/ui/DataCard'
import { useTranslation } from '@/i18n'
import { colors, radius, shadows, spacing, typography } from '@/styles/theme'

const { TextArea } = Input
const { Option } = Select
const { Text, Paragraph } = Typography

interface KnowledgeBase {
  id: string
  name: string
}

interface Source {
  doc_id: string
  chunk_id: string
  content: string
  score: number
  modality: string
}

interface ChatMessage {
  id?: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  intercepted?: boolean
  strategy?: {
    strategy: string
    max_level: number
    reason: string
  }
  feedback_rating?: number
  feedback_comment?: string
}

interface Conversation {
  id: string
  title: string
  kb_ids: string[]
  created_at: string
  updated_at: string
}

const SearchConsole = () => {
  const { t } = useTranslation()
  const [kbList, setKbList] = useState<KnowledgeBase[]>([])
  const [selectedKbs, setSelectedKbs] = useState<string[]>([])
  const [modalities, setModalities] = useState<string[]>(['text', 'table', 'link'])
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const chatAbortRef = useRef<AbortController | null>(null)

  const modalityOptions = useMemo(
    () => [
      { label: t('searchConsole.text'), value: 'text' },
      { label: t('searchConsole.table'), value: 'table' },
      { label: t('searchConsole.image'), value: 'image' },
      { label: t('searchConsole.link'), value: 'link' },
    ],
    [t]
  )

  useEffect(() => {
    api
      .get('/v1/knowledge-bases')
      .then((res) => setKbList(res.data))
      .catch(() => message.error(t('searchConsole.loadKbFailed')))
    loadConversations()
  }, [t])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden && chatAbortRef.current) {
        chatAbortRef.current.abort()
        chatAbortRef.current = null
        setLoading(false)
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      if (chatAbortRef.current) {
        chatAbortRef.current.abort()
      }
    }
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const loadConversations = async () => {
    try {
      const res = await api.get('/v1/chat/conversations')
      setConversations(res.data)
    } catch {
      // silent
    }
  }

  const loadMessages = async (conversationId: string) => {
    try {
      const res = await api.get(`/v1/chat/conversations/${conversationId}/messages`)
      const loaded: ChatMessage[] = res.data.map((m: { id: string; role: 'user' | 'assistant'; content: string; sources?: Source[]; feedback_rating?: number; feedback_comment?: string }) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        sources: m.sources || [],
        feedback_rating: m.feedback_rating,
        feedback_comment: m.feedback_comment,
      }))
      setMessages(loaded)
    } catch {
      message.error(t('searchConsole.loadHistoryFailed'))
    }
  }

  const createConversation = async (): Promise<Conversation | null> => {
    if (selectedKbs.length === 0) {
      message.warning(t('searchConsole.selectKbWarning'))
      return null
    }
    try {
      const res = await api.post('/v1/chat/conversations', {
        title: query.trim() || t('searchConsole.newConversationTitle'),
        kb_ids: selectedKbs,
      })
      const conversation: Conversation = res.data
      setConversations((prev) => [conversation, ...prev])
      setCurrentConversationId(conversation.id)
      setMessages([])
      return conversation
    } catch {
      message.error(t('searchConsole.createConvFailed'))
      return null
    }
  }

  const selectConversation = (conversation: Conversation) => {
    setCurrentConversationId(conversation.id)
    setSelectedKbs(conversation.kb_ids || [])
    loadMessages(conversation.id)
  }

  const deleteConversation = async (conversationId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await api.delete(`/v1/chat/conversations/${conversationId}`)
      setConversations((prev) => prev.filter((c) => c.id !== conversationId))
      if (currentConversationId === conversationId) {
        setCurrentConversationId(null)
        setMessages([])
      }
    } catch {
      message.error(t('searchConsole.deleteConvFailed'))
    }
  }

  const sendFeedback = async (messageId: string, rating: number) => {
    try {
      await api.post(`/v1/chat/messages/${messageId}/feedback`, {
        rating,
        comment: '',
      })
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, feedback_rating: rating } : m))
      )
      message.success(t('searchConsole.feedbackSuccess'))
    } catch {
      message.error(t('searchConsole.feedbackFailed'))
    }
  }

  const handleSend = async () => {
    if (!query.trim()) return
    if (selectedKbs.length === 0) {
      message.warning(t('searchConsole.selectKbWarning'))
      return
    }

    let conversationId = currentConversationId
    if (!conversationId) {
      const conversation = await createConversation()
      if (!conversation) return
      conversationId = conversation.id
    }

    const userMsg: ChatMessage = { role: 'user', content: query }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)
    const currentQuery = query
    setQuery('')

    if (chatAbortRef.current) {
      chatAbortRef.current.abort()
    }
    const controller = new AbortController()
    chatAbortRef.current = controller

    try {
      const res = await api.post(
        '/v1/chat',
        {
          query: currentQuery,
          kb_ids: selectedKbs,
          conversation_id: conversationId,
          modalities,
          top_k: 10,
          rerank_top_k: 5,
        },
        { signal: controller.signal }
      )
      const data = res.data
      setMessages((prev) => [
        ...prev,
        { 
          // id:crypto.randomUUID(),
          // 把 crypto.randomUUID() 换成了手写的 UUID 生成器，因为 crypto.randomUUID() 在非 HTTPS、非 localhost 的环境下不可用。
          id: 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16); }),
          role: 'assistant',
          content: data.answer,
          sources: data.sources,
          intercepted: data.intercepted,
          strategy: data.strategy,
        },
      ])
      loadConversations()
    } catch (e) {
      if ((e as Error).name === 'CanceledError' || (e as Error).name === 'AbortError') {
        // User left the page/tab; do not show an error toast.
        setMessages((prev) => prev.filter((m) => m !== userMsg))
      } else {
        message.error(t('searchConsole.requestFailed'))
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: t('searchConsole.requestFailedReply'),
          },
        ])
      }
    } finally {
      setLoading(false)
      if (chatAbortRef.current === controller) {
        chatAbortRef.current = null
      }
    }
  }

  return (
    <div className="responsive-page" style={{ display: 'flex', gap: spacing.lg, height: 'calc(100vh - 180px)', minWidth: 0, overflow: 'hidden' }}>
      {/* Conversation List */}
      <DataCard
        title={
          <Space>
            <MessageOutlined style={{ color: colors.accent }} />
            <span>{t('searchConsole.sessionList')}</span>
          </Space>
        }
        style={{ width: 260, flexShrink: 0, display: 'flex', flexDirection: 'column', minWidth: 0 }}
        bodyStyle={{ padding: spacing.md, flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
      >
        <Button
          type="dashed"
          icon={<PlusOutlined />}
          block
          style={{ marginBottom: spacing.md, borderRadius: radius.md }}
          onClick={() => {
            setCurrentConversationId(null)
            setMessages([])
          }}
        >
          {t('searchConsole.newSession')}
        </Button>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <List
            dataSource={conversations}
            renderItem={(conv) => (
              <List.Item
                key={conv.id}
                style={{
                  padding: `${spacing.sm}px ${spacing.md}px`,
                  cursor: 'pointer',
                  background: currentConversationId === conv.id ? colors.accentLight : 'transparent',
                  borderRadius: radius.md,
                  marginBottom: spacing.xs,
                  transition: 'background 200ms',
                }}
                onClick={() => selectConversation(conv)}
                actions={[
                  <Popconfirm
                    key="delete"
                    title={t('searchConsole.deleteConfirm')}
                    onConfirm={(e) => deleteConversation(conv.id, e as React.MouseEvent<HTMLElement>)}
                  >
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>,
                ]}
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div
                    style={{
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      color: currentConversationId === conv.id ? colors.accent : colors.textPrimary,
                      fontWeight: currentConversationId === conv.id ? typography.weights.medium : typography.weights.normal,
                    }}
                  >
                    {conv.title}
                  </div>
                </div>
              </List.Item>
            )}
          />
        </div>
      </DataCard>

      {/* Config Panel */}
      <DataCard
        title={
          <Space>
            <SettingOutlined style={{ color: colors.accent }} />
            <span>{t('searchConsole.searchConfig')}</span>
          </Space>
        }
        style={{ width: 300, flexShrink: 0, display: 'flex', flexDirection: 'column', minWidth: 0 }}
        bodyStyle={{ padding: spacing.md }}
      >
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div>
            <Text strong style={{ color: colors.textPrimary }}>{t('searchConsole.knowledgeBase')}</Text>
            <Select
              mode="multiple"
              style={{ width: '100%', marginTop: spacing.sm }}
              placeholder={t('searchConsole.selectKb')}
              value={selectedKbs}
              onChange={setSelectedKbs}
              maxTagCount="responsive"
              maxTagPlaceholder={(omitted) => `+${omitted.length}`}
            >
              {kbList.map((kb) => (
                <Option key={kb.id} value={kb.id}>
                  {kb.name}
                </Option>
              ))}
            </Select>
          </div>
          <div>
            <Text strong style={{ color: colors.textPrimary }}>{t('searchConsole.modality')}</Text>
            <Checkbox.Group
              style={{ marginTop: spacing.sm, display: 'block' }}
              options={modalityOptions}
              value={modalities}
              onChange={(vals) => setModalities(vals as string[])}
            />
          </div>
          <div style={{ padding: spacing.md, background: colors.surfaceAlt, borderRadius: radius.md }}>
            <Text type="secondary" style={{ fontSize: typography.sizes.sm }}>
              {t('searchConsole.selectedSummary', { kbCount: selectedKbs.length, modalityCount: modalities.length })}
            </Text>
          </div>
        </Space>
      </DataCard>

      {/* Chat Area */}
      <DataCard
        title={
          <Space>
            <BookOutlined style={{ color: colors.accent }} />
            <span>{t('searchConsole.chatTitle')}</span>
          </Space>
        }
        style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}
        bodyStyle={{ padding: 0, flex: 1, display: 'flex', flexDirection: 'column' }}
      >
        <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', minWidth: 0, padding: spacing.lg }}>
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', marginTop: 100 }}>
              <div
                style={{
                  width: 64,
                  height: 64,
                  borderRadius: radius.full,
                  background: colors.accentLight,
                  color: colors.accent,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 28,
                  margin: '0 auto',
                  marginBottom: spacing.lg,
                }}
              >
                <MessageOutlined />
              </div>
              <Text style={{ color: colors.textMuted, fontSize: typography.sizes.md }}>
                {t('searchConsole.placeholder')}
              </Text>
            </div>
          )}
          <List
            dataSource={messages}
            renderItem={(msg, idx) => (
              <List.Item
                key={idx}
                style={{
                  justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  padding: `${spacing.sm}px 0`,
                  borderBottom: 'none',
                }}
              >
                <div
                  style={{
                    maxWidth: '80%',
                    background: msg.role === 'user' ? colors.brand : colors.surfaceAlt,
                    color: msg.role === 'user' ? colors.white : colors.textPrimary,
                    padding: spacing.md,
                    borderRadius: radius.lg,
                    border: msg.role === 'user' ? 'none' : `1px solid ${colors.border}`,
                    boxShadow: shadows.sm,
                    wordBreak: 'break-word',
                    overflowWrap: 'break-word',
                  }}
                >
                  <Paragraph style={{ margin: 0, color: 'inherit', lineHeight: typography.lineHeights.relaxed, wordBreak: 'break-word', overflowWrap: 'break-word', whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                  </Paragraph>
                  {msg.intercepted && (
                    <Tag color="error" style={{ marginTop: spacing.sm }}>
                      {t('searchConsole.intercepted')}
                    </Tag>
                  )}
                  {msg.strategy && (
                    <Tag
                      color="processing"
                      style={{ marginTop: spacing.sm, maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    >
                      {t(`searchConsole.modes.${msg.strategy.strategy}`)}: {msg.strategy.reason}
                    </Tag>
                  )}
                  {msg.sources && msg.sources.length > 0 && (
                    <div style={{ marginTop: spacing.md, paddingTop: spacing.sm, borderTop: `1px solid ${msg.role === 'user' ? 'rgba(255,255,255,0.2)' : colors.border}` }}>
                      <Text strong style={{ color: 'inherit', fontSize: typography.sizes.sm }}>
                        {t('searchConsole.sources')}
                      </Text>
                      <div style={{ marginTop: spacing.xs, display: 'flex', flexWrap: 'wrap', gap: spacing.xs }}>
                        {msg.sources.map((s, i) => (
                          <Tooltip key={i} title={s.content}>
                            <Tag color="default" style={{ cursor: 'help', maxWidth: '100%' }}>
                              {s.modality} [{s.score.toFixed(2)}]
                            </Tag>
                          </Tooltip>
                        ))}
                      </div>
                    </div>
                  )}
                  {msg.role === 'assistant' && msg.id && (
                    <div style={{ marginTop: spacing.sm, textAlign: 'right' }}>
                      <Tooltip title={t('searchConsole.helpful')}>
                        <Button
                          type="text"
                          size="small"
                          icon={<LikeOutlined />}
                          style={{ color: msg.feedback_rating === 1 ? colors.success : colors.textMuted }}
                          onClick={() => sendFeedback(msg.id!, 1)}
                        />
                      </Tooltip>
                      <Tooltip title={t('searchConsole.notHelpful')}>
                        <Button
                          type="text"
                          size="small"
                          icon={<DislikeOutlined />}
                          style={{ color: msg.feedback_rating === -1 ? colors.error : colors.textMuted }}
                          onClick={() => sendFeedback(msg.id!, -1)}
                        />
                      </Tooltip>
                    </div>
                  )}
                </div>
              </List.Item>
            )}
          />
          {loading && (
            <div style={{ textAlign: 'center', padding: spacing.lg }}>
              <Spin tip={t('searchConsole.loading')} />
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div style={{ padding: spacing.lg, borderTop: `1px solid ${colors.borderLight}` }}>
          <Space.Compact style={{ width: '100%' }}>
            <TextArea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('searchConsole.inputPlaceholder')}
              autoSize={{ minRows: 2, maxRows: 6 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              style={{ borderRadius: `${radius.md}px 0 0 ${radius.md}px` }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={loading}
              style={{
                height: 'auto',
                borderRadius: `0 ${radius.md}px ${radius.md}px 0`,
                background: colors.accent,
                borderColor: colors.accent,
              }}
            >
              {t('searchConsole.send')}
            </Button>
          </Space.Compact>
        </div>
      </DataCard>
    </div>
  )
}

export default SearchConsole
