import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Tag, Space, Typography, message } from 'antd'
import { PlusOutlined, EyeOutlined, DownloadOutlined, FileOutlined } from '@ant-design/icons'
import api from '@/services/api'
import PageHeader from '@/components/ui/PageHeader'
import DataCard from '@/components/ui/DataCard'
import LoadingState from '@/components/ui/LoadingState'
import EmptyState from '@/components/ui/EmptyState'
import ErrorState from '@/components/ui/ErrorState'
import { downloadFile, formatFileSize, openPreview } from '@/utils/fileDownload'
import { useTranslation } from '@/i18n'
import { colors, radius } from '@/styles/theme'

interface KnowledgeBaseItem {
  id: string
  name: string
  description?: string
  status: string
  created_at: string
}

interface DocumentItem {
  id: string
  filename: string
  file_type: string
  file_size: number
  mime_type: string
  status: string
  created_at: string
}

const KnowledgeBase = () => {
  const { t } = useTranslation()
  const [data, setData] = useState<KnowledgeBaseItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [form] = Form.useForm()

  const [selectedKb, setSelectedKb] = useState<KnowledgeBaseItem | null>(null)
  const [docsVisible, setDocsVisible] = useState(false)
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [docsLoading, setDocsLoading] = useState(false)

  const statusMap: Record<string, { label: string; color: string }> = {
    active: { label: t('knowledgeBase.active'), color: colors.success },
    processing: { label: t('knowledgeBase.processing'), color: colors.warning },
    error: { label: t('knowledgeBase.error'), color: colors.error },
    inactive: { label: t('knowledgeBase.inactive'), color: colors.textMuted },
    pending: { label: t('knowledgeBase.pending'), color: colors.warning },
    indexed: { label: t('knowledgeBase.indexed'), color: colors.success },
  }

  const fetchData = async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await api.get('/v1/knowledge-bases')
      setData(res.data)
    } catch (e) {
      setError(true)
      message.error(t('knowledgeBase.loadDocsFailed'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const handleCreate = async (values: { name: string; description: string }) => {
    try {
      await api.post('/v1/knowledge-bases', values)
      message.success(t('knowledgeBase.createSuccess'))
      setModalVisible(false)
      form.resetFields()
      fetchData()
    } catch (e) {
      message.error(t('knowledgeBase.createFailed'))
    }
  }

  const openDocuments = async (kb: KnowledgeBaseItem) => {
    setSelectedKb(kb)
    setDocsVisible(true)
    setDocsLoading(true)
    try {
      const res = await api.get(`/v1/documents/${kb.id}`)
      setDocs(res.data.items || [])
    } catch (e) {
      message.error(t('knowledgeBase.loadDocsFailed'))
      setDocs([])
    } finally {
      setDocsLoading(false)
    }
  }

  const handlePreview = async (doc: DocumentItem) => {
    try {
      await openPreview(`/api/v1/documents/detail/${doc.id}/preview`)
    } catch (e) {
      message.error(t('knowledgeBase.previewFailed'))
    }
  }

  const handleDownload = async (doc: DocumentItem) => {
    try {
      await downloadFile(`/api/v1/documents/detail/${doc.id}/download`, doc.filename)
    } catch (e) {
      message.error(t('knowledgeBase.downloadFailed'))
    }
  }

  const columns = [
    { title: t('knowledgeBase.name'), dataIndex: 'name', key: 'name', width: 220, ellipsis: true },
    { title: t('knowledgeBase.description'), dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: t('knowledgeBase.status'),
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (v: string) => {
        const meta = statusMap[v] || { label: v, color: colors.textMuted }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: t('knowledgeBase.createdAt'),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      ellipsis: true,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: t('common.operations'),
      key: 'action',
      width: 140,
      render: (_: unknown, record: KnowledgeBaseItem) => (
        <Button
          type="link"
          icon={<FileOutlined />}
          onClick={() => openDocuments(record)}
        >
          {t('knowledgeBase.viewDocs')}
        </Button>
      ),
    },
  ]

  const docColumns = [
    {
      title: t('knowledgeBase.docName'),
      dataIndex: 'filename',
      key: 'filename',
      ellipsis: true,
      render: (v: string) => (
        <Space>
          <FileOutlined />
          <Typography.Text ellipsis style={{ maxWidth: '100%' }}>
            {v}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: t('knowledgeBase.status'),
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: string) => {
        const meta = statusMap[v] || { label: v, color: colors.textMuted }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: t('knowledgeBase.docSize'),
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (v: number) => formatFileSize(v),
    },
    {
      title: t('knowledgeBase.uploadTime'),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: t('common.operations'),
      key: 'action',
      width: 160,
      render: (_: unknown, record: DocumentItem) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handlePreview(record)}
          >
            {t('common.view')}
          </Button>
          <Button
            type="link"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => handleDownload(record)}
          >
            {t('common.download')}
          </Button>
        </Space>
      ),
    },
  ]

  if (loading && data.length === 0) return <LoadingState fullHeight tip={t('knowledgeBase.loading')} />
  if (error && data.length === 0) return <ErrorState title={t('knowledgeBase.loadError')} subTitle={t('knowledgeBase.loadErrorSub')} onRetry={fetchData} />

  return (
    <div className="responsive-page">
      <PageHeader
        title={t('knowledgeBase.title')}
        subtitle={t('knowledgeBase.subtitle')}
      />

      <DataCard
        title={
          <Space>
            <span>{t('knowledgeBase.listTitle')}</span>
            <Tag color={colors.accent}>{data.length}</Tag>
          </Space>
        }
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setModalVisible(true)}
            style={{ background: colors.accent, borderColor: colors.accent, borderRadius: radius.md }}
          >
            {t('knowledgeBase.create')}
          </Button>
        }
      >
        {data.length === 0 ? (
          <EmptyState
            description={t('knowledgeBase.empty')}
            subDescription={t('knowledgeBase.emptySub')}
          />
        ) : (
          <div className="responsive-table-scroll">
            <Table
              rowKey="id"
              loading={loading}
              dataSource={data}
              columns={columns}
              pagination={{ pageSize: 10, hideOnSinglePage: true }}
              scroll={{ x: 'max-content' }}
            />
          </div>
        )}
      </DataCard>

      <Modal
        title={t('knowledgeBase.create')}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={() => form.submit()}
        okButtonProps={{ style: { background: colors.accent, borderColor: colors.accent } }}
      >
        <Form form={form} layout="vertical" onFinish={handleCreate} className="responsive-form">
          <Form.Item
            name="name"
            label={t('knowledgeBase.name')}
            rules={[{ required: true, message: t('knowledgeBase.nameRequired') }]}
          >
            <Input placeholder={t('knowledgeBase.namePlaceholder')} />
          </Form.Item>
          <Form.Item name="description" label={t('knowledgeBase.description')}>
            <Input.TextArea rows={3} placeholder={t('knowledgeBase.descPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={
          selectedKb ? (
            <Typography.Text ellipsis style={{ maxWidth: 400 }}>
              {t('knowledgeBase.docListFor', { name: selectedKb.name })}
            </Typography.Text>
          ) : (
            t('knowledgeBase.docListTitle')
          )
        }
        open={docsVisible}
        onCancel={() => setDocsVisible(false)}
        footer={null}
        width={900}
      >
        <div className="responsive-table-scroll">
          <Table
            rowKey="id"
            loading={docsLoading}
            dataSource={docs}
            columns={docColumns}
            pagination={{ pageSize: 10, hideOnSinglePage: true }}
            locale={{ emptyText: t('knowledgeBase.docEmpty') }}
            scroll={{ x: 'max-content' }}
          />
        </div>
      </Modal>
    </div>
  )
}

export default KnowledgeBase
