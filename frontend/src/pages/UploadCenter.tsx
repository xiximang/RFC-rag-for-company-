import { useEffect, useState } from 'react'
import {
  Upload,
  Button,
  Form,
  Input,
  Select,
  message,
  Tag,
  Space,
  Tabs,
  Table,
  Typography,
} from 'antd'
import {
  InboxOutlined,
  LinkOutlined,
  FilePdfOutlined,
  FileExcelOutlined,
  FileImageOutlined,
  FileTextOutlined,
  VideoCameraOutlined,
  AudioOutlined,
  CloudUploadOutlined,
} from '@ant-design/icons'
import type { UploadFile, UploadProps } from 'antd/es/upload'
import api from '@/services/api'
import PageHeader from '@/components/ui/PageHeader'
import DataCard from '@/components/ui/DataCard'
import EmptyState from '@/components/ui/EmptyState'
import { useTranslation } from '@/i18n'
import { colors, radius, spacing, typography } from '@/styles/theme'

const { Dragger } = Upload
const { Option } = Select

interface KnowledgeBase {
  id: string
  name: string
}

interface DocumentItem {
  id: string
  filename: string
  file_type: string
  status: string
  created_at: string
}

const UploadCenter = () => {
  const { t } = useTranslation()
  const [kbList, setKbList] = useState<KnowledgeBase[]>([])
  const [selectedKb, setSelectedKb] = useState<string>()
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [docsLoading, setDocsLoading] = useState(false)
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [linkForm] = Form.useForm()

  const FILE_ICONS: Record<string, React.ReactNode> = {
    pdf: <FilePdfOutlined style={{ color: colors.error }} />,
    excel: <FileExcelOutlined style={{ color: colors.success }} />,
    image: <FileImageOutlined style={{ color: colors.info }} />,
    video: <VideoCameraOutlined style={{ color: colors.warning }} />,
    audio: <AudioOutlined style={{ color: colors.accent }} />,
    document: <FileTextOutlined style={{ color: colors.textSecondary }} />,
  }

  const statusMap: Record<string, { label: string; color: string }> = {
    indexed: { label: t('uploadCenter.indexed'), color: colors.success },
    active: { label: t('uploadCenter.active'), color: colors.success },
    processing: { label: t('uploadCenter.processing'), color: colors.warning },
    failed: { label: t('uploadCenter.failed'), color: colors.error },
    pending: { label: t('uploadCenter.pending'), color: colors.info },
  }

  const fetchKBs = async () => {
    try {
      const res = await api.get('/v1/knowledge-bases')
      setKbList(res.data)
      if (res.data.length > 0 && !selectedKb) {
        setSelectedKb(res.data[0].id)
      }
    } catch (e) {
      message.error(t('uploadCenter.loadKbsFailed'))
    }
  }

  const fetchDocs = async () => {
    if (!selectedKb) return
    setDocsLoading(true)
    try {
      const res = await api.get(`/v1/documents/${selectedKb}`)
      setDocs(res.data.items || [])
    } catch (e) {
      message.error(t('uploadCenter.loadDocsFailed'))
    } finally {
      setDocsLoading(false)
    }
  }

  useEffect(() => {
    fetchKBs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    fetchDocs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKb])

  const customUpload: UploadProps['customRequest'] = async (options) => {
    const { file, onSuccess, onError } = options
    if (!selectedKb) {
      message.error(t('uploadCenter.selectKbFirst'))
      onError?.(new Error('No KB selected'))
      return
    }

    const formData = new FormData()
    formData.append('file', file)
    formData.append('kb_id', selectedKb)
    formData.append('title', (file as File).name)

    try {
      await api.post('/v1/documents', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      onSuccess?.('ok')
      message.success(t('uploadCenter.uploadSuccess', { name: (file as File).name }))
      fetchDocs()
    } catch (e) {
      onError?.(new Error('Upload failed'))
      message.error(t('uploadCenter.uploadFailed', { name: (file as File).name }))
    }
  }

  const handleLinkSubmit = async (values: { url: string; tags?: string }) => {
    if (!selectedKb) {
      message.error(t('uploadCenter.selectKbFirst'))
      return
    }
    try {
      await api.post(
        '/v1/documents/link',
        {
          ...values,
          metadata: { title: values.url },
        },
        {
          params: new URLSearchParams({ kb_id: selectedKb }),
        }
      )
      message.success(t('uploadCenter.linkSubmitSuccess'))
      linkForm.resetFields()
      fetchDocs()
    } catch (e) {
      message.error(t('uploadCenter.linkSubmitFailed'))
    }
  }

  const docColumns = [
    {
      title: t('uploadCenter.filename'),
      dataIndex: 'filename',
      key: 'filename',
      ellipsis: true,
      width: 360,
      render: (v: string, record: DocumentItem) => (
        <Space>
          {FILE_ICONS[record.file_type] || <FileTextOutlined style={{ color: colors.textSecondary }} />}
          <Typography.Text ellipsis style={{ maxWidth: '100%' }}>
            {v}
          </Typography.Text>
        </Space>
      ),
    },
    { title: t('uploadCenter.fileType'), dataIndex: 'file_type', key: 'file_type', width: 100 },
    {
      title: t('uploadCenter.status'),
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (v: string) => {
        const meta = statusMap[v] || { label: v, color: colors.textMuted }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: t('uploadCenter.createdAt'),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (v: string) => new Date(v).toLocaleString(),
    },
  ]

  const tabItems = [
    {
      key: 'file',
      label: (
        <Space>
          <CloudUploadOutlined />
          <span>{t('uploadCenter.fileUpload')}</span>
        </Space>
      ),
      children: (
        <Dragger
          customRequest={customUpload}
          fileList={fileList}
          onChange={({ fileList: next }) => setFileList(next)}
          multiple
          accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg,.gif,.mp4,.avi,.mov,.mp3,.wav,.txt,.md"
          style={{
            padding: spacing.xl,
            borderRadius: radius.lg,
            background: colors.surfaceAlt,
            border: `1px dashed ${colors.border}`,
            overflow: 'hidden',
          }}
        >
          <p style={{ fontSize: 40, color: colors.accent, marginBottom: spacing.md }}>
            <InboxOutlined />
          </p>
          <p style={{ fontSize: typography.sizes.md, color: colors.textPrimary, marginBottom: spacing.sm }}>
            {t('uploadCenter.dragText')}
          </p>
          <p style={{ color: colors.textMuted, fontSize: typography.sizes.sm }}>
            {t('uploadCenter.supportedTypes')}
          </p>
        </Dragger>
      ),
    },
    {
      key: 'link',
      label: (
        <Space>
          <LinkOutlined />
          <span>{t('uploadCenter.linkUpload')}</span>
        </Space>
      ),
      children: (
        <Form form={linkForm} layout="vertical" onFinish={handleLinkSubmit} className="responsive-form">
          <Form.Item
            name="url"
            label={t('uploadCenter.linkUrl')}
            rules={[{ required: true, type: 'url', message: t('uploadCenter.urlRequired') }]}
          >
            <Input prefix={<LinkOutlined />} placeholder={t('uploadCenter.urlPlaceholder')} />
          </Form.Item>
          <Form.Item name="tags" label={t('uploadCenter.tags')}>
            <Input placeholder={t('uploadCenter.tagsPlaceholder')} />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              style={{ background: colors.accent, borderColor: colors.accent, borderRadius: radius.md }}
            >
              {t('uploadCenter.submitLink')}
            </Button>
          </Form.Item>
        </Form>
      ),
    },
  ]

  return (
    <div className="responsive-page">
      <PageHeader
        title={t('uploadCenter.title')}
        subtitle={t('uploadCenter.subtitle')}
      />

      <DataCard
        title={t('uploadCenter.fileUpload')}
        extra={
          <Space>
            <span style={{ color: colors.textSecondary, fontSize: typography.sizes.sm }}>{t('uploadCenter.targetKb')}</span>
            <Select
              style={{ width: 240, maxWidth: '50vw' }}
              value={selectedKb}
              onChange={setSelectedKb}
              placeholder={t('uploadCenter.selectKb')}
            >
              {kbList.map((kb) => (
                <Option key={kb.id} value={kb.id}>
                  {kb.name}
                </Option>
              ))}
            </Select>
          </Space>
        }
        style={{ marginBottom: spacing.lg }}
      >
        <Tabs defaultActiveKey="file" items={tabItems} />
      </DataCard>

      <DataCard
        title={
          <Space>
            <span>{t('uploadCenter.docList')}</span>
            <Tag color={colors.accent}>{docs.length}</Tag>
          </Space>
        }
      >
        {docs.length === 0 && !docsLoading ? (
          <EmptyState
            description={t('uploadCenter.empty')}
            subDescription={t('uploadCenter.emptySub')}
          />
        ) : (
          <div className="responsive-table-scroll">
            <Table
              rowKey="id"
              dataSource={docs}
              columns={docColumns}
              loading={docsLoading}
              pagination={{ pageSize: 10, hideOnSinglePage: true }}
              scroll={{ x: 'max-content' }}
            />
          </div>
        )}
      </DataCard>
    </div>
  )
}

export default UploadCenter
