import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Card,
  Checkbox,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  KeyOutlined,
  CopyOutlined,
  DeleteOutlined,
  PlusOutlined,
  EyeInvisibleOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import api from '@/services/api'
import { useTranslation } from '@/i18n'
import { colors, spacing, radius, shadows, typography } from '@/styles/theme'

const { Title, Text, Paragraph } = Typography

interface ApiKey {
  id: string
  owner_id: string
  name: string
  key_prefix: string
  scopes: string[]
  rate_limit_rpm: number
  expires_at: string | null
  last_used_at: string | null
  is_active: boolean
  created_at: string
}

interface ApiKeyCreateResponse extends ApiKey {
  plain_key: string
}

interface ScopesResponse {
  allowed_scopes: string[]
  all_scopes: string[]
}

const SCOPE_COLORS: Record<string, string> = {
  'kb:read': colors.info,
  'kb:write': colors.warning,
  search: colors.success,
  chat: '#6654d9',
  'doc:write': colors.accent,
  'user:read': colors.textMuted,
  'apikey:admin': colors.error,
  '*': colors.error,
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return '-'
  return dayjs(iso).format('YYYY-MM-DD HH:mm')
}

export default function ApiKeysPage() {
  const { t } = useTranslation()
  const [keys, setKeys] = useState<ApiKey[]>([])
  const [scopes, setScopes] = useState<ScopesResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [createdKey, setCreatedKey] = useState<ApiKeyCreateResponse | null>(null)
  const [form] = Form.useForm()

  const scopeLabels: Record<string, string> = {
    'kb:read': t('apiKeys.scope_kb_read'),
    'kb:write': t('apiKeys.scope_kb_write'),
    search: t('apiKeys.scope_search'),
    chat: t('apiKeys.scope_chat'),
    'doc:write': t('apiKeys.scope_doc_write'),
    'user:read': t('apiKeys.scope_user_read'),
    'apikey:admin': t('apiKeys.scope_apikey_admin'),
    '*': t('apiKeys.scope_all'),
  }

  const fetchKeys = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get<ApiKey[]>('/v1/api-keys')
      setKeys(res.data)
    } catch {
      message.error(t('apiKeys.fetchFailed'))
    } finally {
      setLoading(false)
    }
  }, [t])

  const fetchScopes = useCallback(async () => {
    try {
      const res = await api.get<ScopesResponse>('/v1/api-keys/scopes')
      setScopes(res.data)
    } catch {
      message.error(t('apiKeys.scopesFetchFailed'))
    }
  }, [t])

  useEffect(() => {
    fetchKeys()
    fetchScopes()
  }, [fetchKeys, fetchScopes])

  const handleCreate = async (values: {
    name: string
    scopes: string[]
    rate_limit_rpm: number
    expires_at?: dayjs.Dayjs
  }) => {
    setIsSubmitting(true)
    try {
      const payload = {
        name: values.name,
        scopes: values.scopes,
        rate_limit_rpm: values.rate_limit_rpm,
        expires_at: values.expires_at ? values.expires_at.toISOString() : null,
      }
      const res = await api.post<ApiKeyCreateResponse>('/v1/api-keys', payload)
      setCreatedKey(res.data)
      message.success(t('apiKeys.createSuccess'))
      setIsModalOpen(false)
      form.resetFields()
      fetchKeys()
    } catch {
      message.error(t('apiKeys.createFailed'))
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleRevoke = async (key: ApiKey) => {
    Modal.confirm({
      title: t('apiKeys.revokeConfirm'),
      content: t('apiKeys.revokeContent', { name: key.name }),
      okText: t('apiKeys.revoke'),
      okType: 'danger',
      cancelText: t('common.cancel'),
      onOk: async () => {
        try {
          await api.delete(`/v1/api-keys/${key.id}`)
          message.success(t('apiKeys.revokeSuccess'))
          fetchKeys()
        } catch {
          message.error(t('apiKeys.revokeFailed'))
        }
      },
    })
  }

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      message.success(t('apiKeys.copySuccess'))
    } catch {
      message.error(t('apiKeys.copyFailed'))
    }
  }

  const columns: ColumnsType<ApiKey> = [
    {
      title: t('apiKeys.name'),
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record) => (
        <Space direction="vertical" size={spacing.xs}>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: typography.sizes.xs }}>
            {t('apiKeys.prefix')}: {record.key_prefix}***
          </Text>
        </Space>
      ),
    },
    {
      title: t('apiKeys.scopes'),
      dataIndex: 'scopes',
      key: 'scopes',
      render: (scopes: string[]) => (
        <Space size={spacing.xs} wrap>
          {scopes.map((s) => (
            <Tag key={s} color={SCOPE_COLORS[s] || colors.textMuted}>
              {scopeLabels[s] || s}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: t('apiKeys.rateLimit'),
      dataIndex: 'rate_limit_rpm',
      key: 'rate_limit_rpm',
      width: 120,
    },
    {
      title: t('apiKeys.expiresAtColumn'),
      dataIndex: 'expires_at',
      key: 'expires_at',
      render: formatDate,
      width: 160,
    },
    {
      title: t('apiKeys.lastUsedAt'),
      dataIndex: 'last_used_at',
      key: 'last_used_at',
      render: formatDate,
      width: 160,
    },
    {
      title: t('common.status'),
      dataIndex: 'is_active',
      key: 'is_active',
      width: 90,
      render: (isActive: boolean) =>
        isActive ? <Tag color="success">{t('apiKeys.active')}</Tag> : <Tag>{t('apiKeys.revoked')}</Tag>,
    },
    {
      title: t('common.operations'),
      key: 'action',
      width: 90,
      render: (_, record) =>
        record.is_active ? (
          <Tooltip title={t('apiKeys.revoke')}>
            <Button
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={() => handleRevoke(record)}
            />
          </Tooltip>
        ) : null,
    },
  ]

  const initialScopes = (() => {
    if (!scopes) return []
    if (scopes.allowed_scopes.includes('*')) return ['*']
    return scopes.allowed_scopes.length > 0 ? [scopes.allowed_scopes[0]] : []
  })()

  return (
    <div className="responsive-page">
      <Title level={4} style={{ margin: 0, marginBottom: spacing.lg, color: colors.textPrimary }}>
        {t('apiKeys.title')}
      </Title>
      <Paragraph style={{ color: colors.textSecondary, marginBottom: spacing.lg }}>
        {t('apiKeys.description', {
          apiKeyHeader: 'X-API-Key',
          authHeader: 'Authorization: Bearer <key>',
        })}
      </Paragraph>

      <Card
        style={{
          marginBottom: spacing.lg,
          borderRadius: radius.lg,
          boxShadow: shadows.sm,
        }}
        bodyStyle={{ padding: spacing.lg }}
      >
        <Space style={{ marginBottom: spacing.lg }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setIsModalOpen(true)}
            style={{ background: colors.accent, borderColor: colors.accent }}
          >
            {t('apiKeys.newKey')}
          </Button>
        </Space>

        <div className="responsive-table-scroll">
          <Table
            rowKey="id"
            columns={columns}
            dataSource={keys}
            loading={loading}
            pagination={{ pageSize: 10 }}
            size="middle"
            bordered
          />
        </div>
      </Card>

      <Modal
        title={t('apiKeys.newKey')}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false)
          form.resetFields()
        }}
        footer={null}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleCreate}
          initialValues={{
            rate_limit_rpm: 60,
            scopes: initialScopes,
          }}
        >
          <Form.Item
            name="name"
            label={t('apiKeys.name')}
            rules={[{ required: true, message: t('apiKeys.nameRequired') }]}
          >
            <Input placeholder={t('apiKeys.namePlaceholder')} maxLength={128} />
          </Form.Item>

          <Form.Item
            name="scopes"
            label={t('apiKeys.scopes')}
            rules={[{ required: true, message: t('apiKeys.scopesRequired') }]}
          >
            <Checkbox.Group style={{ width: '100%' }}>
              <Space direction="vertical">
                {scopes?.allowed_scopes.map((s) => (
                  <Checkbox key={s} value={s}>
                    <Tag color={SCOPE_COLORS[s] || colors.textMuted}>
                      {scopeLabels[s] || s}
                    </Tag>
                  </Checkbox>
                ))}
              </Space>
            </Checkbox.Group>
          </Form.Item>

          <Form.Item
            name="rate_limit_rpm"
            label={t('apiKeys.rateLimit')}
            rules={[{ required: true, message: t('apiKeys.rateLimitRequired') }]}
          >
            <InputNumber min={1} max={10000} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item name="expires_at" label={t('apiKeys.expiresAt')}>
            <DatePicker
              showTime
              style={{ width: '100%' }}
              placeholder={t('apiKeys.expiresAtPlaceholder')}
              disabledDate={(current) => current && current < dayjs().startOf('day')}
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, marginTop: spacing.lg }}>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => setIsModalOpen(false)}>{t('common.cancel')}</Button>
              <Button type="primary" htmlType="submit" loading={isSubmitting}>
                {t('common.create')}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={
          <Space>
            <KeyOutlined style={{ color: colors.accent }} />
            <span>{t('apiKeys.createdTitle')}</span>
          </Space>
        }
        open={!!createdKey}
        onCancel={() => setCreatedKey(null)}
        footer={[
          <Button key="close" type="primary" onClick={() => setCreatedKey(null)}>
            {t('apiKeys.saved')}
          </Button>,
        ]}
        closable={false}
        maskClosable={false}
      >
        <Paragraph>{t('apiKeys.plainKeyHint')}</Paragraph>
        <Input.TextArea
          value={createdKey?.plain_key || ''}
          readOnly
          autoSize={{ minRows: 2, maxRows: 4 }}
          style={{
            fontFamily: typography.mono,
            marginBottom: spacing.md,
            background: colors.codeBg,
            color: colors.codeText,
          }}
        />
        <Button
          type="primary"
          icon={<CopyOutlined />}
          onClick={() => createdKey && copyToClipboard(createdKey.plain_key)}
          block
          style={{ marginBottom: spacing.md }}
        >
          {t('apiKeys.copyKey')}
        </Button>
        <Paragraph type="secondary" style={{ fontSize: typography.sizes.xs }}>
          <EyeInvisibleOutlined /> {t('apiKeys.closeHint')}
        </Paragraph>
      </Modal>
    </div>
  )
}
