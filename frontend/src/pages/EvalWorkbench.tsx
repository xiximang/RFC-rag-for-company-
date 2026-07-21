import { useEffect, useState } from 'react'
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Tabs,
  Tag,
  Space,
  message,
  Descriptions,
  Typography,
  Alert,
  Upload,
  Statistic,
  Row,
  Col,
  Dropdown,
  Tooltip,
  Divider,
} from 'antd'
import type { UploadFile, UploadProps } from 'antd'
import {
  PlusOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  InboxOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  DownloadOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'
import api from '@/services/api'
import PageHeader from '@/components/ui/PageHeader'
import DataCard from '@/components/ui/DataCard'
import { colors, radius, typography } from '@/styles/theme'

const { TextArea } = Input
const { Option } = Select
const { Text } = Typography
const { Dragger } = Upload

interface KnowledgeBase {
  id: string
  name: string
}

interface EvaluationDataset {
  id: string
  kb_id: string
  name: string
  questions: string[]
  ground_truths: Record<string, unknown>[]
  created_at: string
}

interface EvaluationTask {
  id: string
  dataset_id: string
  kb_id: string
  status: string
  metrics: string[]
  results: Record<string, unknown>
  created_at: string
  completed_at?: string
}

interface QuestionRun {
  id: string
  task_id: string
  question_index: number
  question: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'paused'
  retrieved_chunk_ids: string[]
  generated_answer?: string
  metrics: Record<string, number>
  error?: string
  attempts: number
  started_at?: string
  completed_at?: string
}

interface DatasetPreviewItem {
  question: string
  ground_truth: {
    chunk_ids?: string[]
    answer?: string
  }
  metadata?: Record<string, unknown>
}

interface DatasetValidateResponse {
  valid: boolean
  name?: string
  kb_id?: string
  item_count: number
  items: DatasetPreviewItem[]
  errors: string[]
  warnings: string[]
}

// 评测指标中文说明（用于 UI Tooltip 与文档）
const METRIC_DEFINITIONS: Record<string, { name: string; short: string; desc: string; range: string; category: 'retrieval' | 'generation' }> = {
  'recall@3': { name: 'Recall@3', short: '召回率', desc: '前 3 个 chunk 中包含相关 chunk 的问题占比。', range: '0~1', category: 'retrieval' },
  'recall@5': { name: 'Recall@5', short: '召回率(5)', desc: '前 5 个 chunk 中包含相关 chunk 的占比。', range: '0~1', category: 'retrieval' },
  'recall@10': { name: 'Recall@10', short: '召回率(10)', desc: '前 10 个 chunk 中包含相关 chunk 的占比。', range: '0~1', category: 'retrieval' },
  mrr: { name: 'MRR', short: '平均倒数排名', desc: '首个相关 chunk 的排名倒数（1/排名），平均。', range: '0~1', category: 'retrieval' },
  'ndcg@3': { name: 'NDCG@3', short: '归一化折损累积增益', desc: '前 3 个 chunk 的相关性与排名的综合评分。', range: '0~1', category: 'retrieval' },
  'ndcg@5': { name: 'NDCG@5', short: 'NDCG(5)', desc: '前 5 个 chunk 的 NDCG。', range: '0~1', category: 'retrieval' },
  faithfulness: { name: 'Faithfulness', short: '忠实度', desc: '答案是否严格依据检索内容（不编造），由 LLM 评分。', range: '0~1', category: 'generation' },
  relevance: { name: 'Relevance', short: '相关性', desc: '答案与用户问题的相关程度（是否答非所问），由 LLM 评分。', range: '0~1', category: 'generation' },
  coherence: { name: 'Coherence', short: '连贯性', desc: '答案的逻辑与语言是否通顺、条理清晰，由 LLM 评分。', range: '0~1', category: 'generation' },
  completeness: { name: 'Completeness', short: '完整性', desc: '答案是否完整覆盖 ground_truth.answer 中的要点。', range: '0~1', category: 'generation' },
  correctness: { name: 'Correctness', short: '正确性', desc: '答案的事实是否正确（与 ground_truth.answer 一致的程度）。', range: '0~1', category: 'generation' },
}
const CATEGORY_COLORS = { retrieval: '#722ed1', generation: '#13c2c2' }

const STATUS_COLORS: Record<string, string> = {
  pending: colors.info,
  running: colors.warning,
  completed: colors.success,
  failed: colors.error,
}

const EVAL_DATASET_TEMPLATE = `支持三种 JSON 格式（任选其一）：

1) 直接数组（最简单）：
[
  {
    "question": "iBattery 3.0 主要功能是什么？",
    "ground_truth": { "answer": "电池监控与管理", "chunk_ids": ["可选"] }
  }
]

2) 包装格式（推荐，可带 name / kb_id）：
{
  "name": "我的评测集",
  "kb_id": "可选，知识库 UUID",
  "questions": [
    { "question": "...", "ground_truth": { "answer": "...", "chunk_ids": ["..."] } }
  ]
}

3) 旧式兼容：
{
  "questions": ["问题1", "问题2"],
  "ground_truths": [{"answer":"..."}, {"chunk_ids":["..."]}]
}

字段说明：
- question (string, 必填)：问题文本
- ground_truth.chunk_ids (string[], 可选)：相关 chunk id 列表，用于 recall/mrr/ndcg
- ground_truth.answer (string, 可选)：标准答案，用于 faithfulness/relevance/coherence
  至少需要 chunk_ids 或 answer 之一。`

// 三个可直接下载的样例文件
const SAMPLE_TEMPLATE_ARRAY = JSON.stringify(
  [
    {
      question: 'iBattery 3.0 主要功能是什么？',
      ground_truth: {
        answer: '电池监控与管理、远程告警、健康度评估',
        chunk_ids: ['chunk-001', 'chunk-002'],
      },
    },
    {
      question: 'UPS5000 安装注意事项有哪些？',
      ground_truth: {
        answer: '确保接地良好，避免阳光直射，保持通风',
        chunk_ids: ['chunk-010'],
      },
    },
    {
      question: '如何登录 iBOX Web 界面？',
      ground_truth: {
        chunk_ids: ['chunk-020'],
      },
    },
    {
      question: 'SmartLi 电池组与 UPS5000 配合使用的优势？',
      ground_truth: {
        answer: '高能量密度、长循环寿命、智能均压',
      },
    },
  ],
  null,
  2,
)

const SAMPLE_TEMPLATE_WRAPPED = JSON.stringify(
  {
    name: 'iBattery&UPS 综合评测集',
    kb_id: '请替换为目标知识库的 UUID（可选）',
    questions: [
      {
        question: 'iBattery 3.0 主要功能是什么？',
        ground_truth: {
          answer: '电池监控与管理、远程告警、健康度评估',
          chunk_ids: ['chunk-001', 'chunk-002'],
        },
        metadata: { source: 'user_manual', difficulty: 'easy' },
      },
      {
        question: 'UPS5000 安装注意事项有哪些？',
        ground_truth: {
          answer: '确保接地良好，避免阳光直射，保持通风',
          chunk_ids: ['chunk-010'],
        },
        metadata: { source: 'safety_guide', difficulty: 'medium' },
      },
      {
        question: '如何登录 iBOX Web 界面？',
        ground_truth: {
          chunk_ids: ['chunk-020'],
        },
      },
    ],
  },
  null,
  2,
)

const SAMPLE_TEMPLATE_LEGACY = JSON.stringify(
  {
    questions: [
      'iBattery 3.0 主要功能是什么？',
      'UPS5000 安装注意事项有哪些？',
      '如何登录 iBOX Web 界面？',
    ],
    ground_truths: [
      {
        answer: '电池监控与管理、远程告警、健康度评估',
        chunk_ids: ['chunk-001', 'chunk-002'],
      },
      {
        answer: '确保接地良好，避免阳光直射，保持通风',
        chunk_ids: ['chunk-010'],
      },
      {
        chunk_ids: ['chunk-020'],
      },
    ],
  },
  null,
  2,
)

const SAMPLE_TEMPLATES: Array<{ key: string; label: string; description: string; content: string; filename: string }> = [
  {
    key: 'array',
    label: '格式 A：直接数组',
    description: '最简洁，仅包含 question 与 ground_truth 列表',
    content: SAMPLE_TEMPLATE_ARRAY,
    filename: 'eval_dataset_sample_array.json',
  },
  {
    key: 'wrapped',
    label: '格式 B：包装格式（推荐）',
    description: '可附带 name / kb_id / metadata，字段透传保留',
    content: SAMPLE_TEMPLATE_WRAPPED,
    filename: 'eval_dataset_sample_wrapped.json',
  },
  {
    key: 'legacy',
    label: '格式 C：旧式 questions/ground_truths',
    description: '兼容旧版本字段（questions 字符串 + ground_truths 字典）',
    content: SAMPLE_TEMPLATE_LEGACY,
    filename: 'eval_dataset_sample_legacy.json',
  },
]

const EvalWorkbench = () => {
  const [kbList, setKbList] = useState<KnowledgeBase[]>([])
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([])
  const [tasks, setTasks] = useState<EvaluationTask[]>([])
  const [loadingDatasets, setLoadingDatasets] = useState(false)
  const [loadingTasks, setLoadingTasks] = useState(false)
  const [datasetModalVisible, setDatasetModalVisible] = useState(false)
  const [taskModalVisible, setTaskModalVisible] = useState(false)
  const [selectedTask, setSelectedTask] = useState<EvaluationTask | null>(null)
  // Live status panel: 实时监控 task 中的所有问题进度
  const [liveTaskId, setLiveTaskId] = useState<string | null>(null)
  const [liveQuestionRuns, setLiveQuestionRuns] = useState<QuestionRun[]>([])
  const [livePolling, setLivePolling] = useState(false)
  const [datasetForm] = Form.useForm()
  const [taskForm] = Form.useForm()

  // 上传 JSON 文件相关 state
  const [uploadFile, setUploadFile] = useState<UploadFile | null>(null)
  const [preview, setPreview] = useState<DatasetValidateResponse | null>(null)
  const [validating, setValidating] = useState(false)
  const [uploading, setUploading] = useState(false)

  const downloadTemplate = (key: string) => {
    const tpl = SAMPLE_TEMPLATES.find((t) => t.key === key)
    if (!tpl) {
      message.error('未找到对应样例模板')
      return
    }
    try {
      const blob = new Blob([tpl.content], { type: 'application/json;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = tpl.filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success(`已下载：${tpl.filename}`)
    } catch {
      message.error('下载失败，请重试')
    }
  }

  // v2 架构对齐模板下载：从后端拉真实校准过的 v2 JSON（含 kb_id / _dataset_meta）
  const downloadV2Template = async (version: 'v1' | 'v2') => {
    try {
      const res = await api.get(`/v1/evaluation/templates/dataset?version=${version}`)
      const { filename, content } = res.data
      const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success(`已下载 v2 模板：${filename}`)
    } catch (err) {
      message.error(`下载 v${version} 模板失败：${(err as Error).message}`)
    }
  }

  const fetchKnowledgeBases = async () => {
    try {
      const res = await api.get('/v1/knowledge-bases')
      setKbList(res.data)
    } catch {
      message.error('加载知识库失败')
    }
  }

  const fetchDatasets = async () => {
    setLoadingDatasets(true)
    try {
      const res = await api.get('/v1/evaluation/datasets')
      setDatasets(res.data)
    } catch {
      message.error('加载评测数据集失败')
    } finally {
      setLoadingDatasets(false)
    }
  }

  const fetchTasks = async () => {
    setLoadingTasks(true)
    try {
      const res = await api.get('/v1/evaluation/tasks')
      setTasks(res.data)
    } catch {
      message.error('加载评测任务失败')
    } finally {
      setLoadingTasks(false)
    }
  }

  useEffect(() => {
    fetchKnowledgeBases()
    fetchDatasets()
    fetchTasks()
  }, [])

  // 自动轮询：每 3 秒刷新一次任务列表，直到所有任务 completed/failed
  useEffect(() => {
    const hasRunning = tasks.some(
      (t) => t.status === 'pending' || t.status === 'running' || t.status === 'paused',
    )
    if (!hasRunning) return
    const timer = setInterval(() => {
      fetchTasks()
    }, 3000)
    return () => clearInterval(timer)
  }, [tasks])

  // 实时状态栏 Modal 的轮询
  useEffect(() => {
    if (!liveTaskId || !livePolling) return
    let cancelled = false
    const fetchRuns = async () => {
      try {
        const res = await api.get(`/v1/evaluation/tasks/${liveTaskId}/questions`)
        if (cancelled) return
        setLiveQuestionRuns(res.data as QuestionRun[])
      } catch {
        // ignore
      }
    }
    void fetchRuns()
    const timer = setInterval(fetchRuns, 2000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [liveTaskId, livePolling])

  // 上传文件前，先做前端预校验（仅检查文件名/大小），不阻塞
  const handleBeforeUpload: UploadProps['beforeUpload'] = (file) => {
    const isJson =
      file.name.toLowerCase().endsWith('.json') ||
      (file.type || '').includes('json')
    if (!isJson) {
      message.error('仅支持 .json 文件')
      return Upload.LIST_IGNORE
    }
    const isLt10M = file.size / 1024 / 1024 < 10
    if (!isLt10M) {
      message.error('文件大小不能超过 10MB')
      return Upload.LIST_IGNORE
    }
    setUploadFile(file)
    // 自动触发校验
    void runValidate(file)
    return false // 阻止 antd 自动上传
  }

  const runValidate = async (file: UploadFile) => {
    setValidating(true)
    setPreview(null)
    try {
      const form = new FormData()
      form.append('file', file as unknown as Blob)
      const res = await api.post<DatasetValidateResponse>(
        '/v1/evaluation/datasets/validate',
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      setPreview(res.data)
      if (res.data.valid) {
        message.success(`校验通过：${res.data.item_count} 条问题`)
        // 自动填充 name（如果用户没填且后端返回了 name）
        if (res.data.name && !datasetForm.getFieldValue('name')) {
          datasetForm.setFieldsValue({ name: res.data.name })
        }
      } else {
        message.error('文件格式校验未通过，请查看下方错误')
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail || '校验请求失败')
      setPreview({
        valid: false,
        item_count: 0,
        items: [],
        errors: [detail || '后端校验请求失败'],
        warnings: [],
      })
    } finally {
      setValidating(false)
    }
  }

  const handleUploadSubmit = async () => {
    if (!uploadFile) {
      message.warning('请先选择 JSON 文件')
      return
    }
    if (!preview || !preview.valid) {
      message.warning('请先通过格式校验')
      return
    }
    try {
      const values = await datasetForm.validateFields()
      if (!values.kb_id) {
        message.error('请选择知识库')
        return
      }
      setUploading(true)
      const form = new FormData()
      form.append('file', uploadFile as unknown as Blob)
      form.append('kb_id', values.kb_id)
      if (values.name) form.append('name', values.name)

      await api.post('/v1/evaluation/datasets/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      message.success('数据集创建成功')
      handleCloseDatasetModal()
      fetchDatasets()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handleCloseDatasetModal = () => {
    setDatasetModalVisible(false)
    setUploadFile(null)
    setPreview(null)
    datasetForm.resetFields()
  }

  // 旧式 JSON 文本提交（兼容原表单）
  const handleCreateDatasetByText = async (values: {
    kb_id: string
    name: string
    questions: string
    ground_truths: string
  }) => {
    try {
      const questions = values.questions
        .split('\n')
        .map((q) => q.trim())
        .filter(Boolean)
      const groundTruths = values.ground_truths
        ? JSON.parse(values.ground_truths)
        : []
      await api.post('/v1/evaluation/datasets', {
        kb_id: values.kb_id,
        name: values.name,
        questions,
        ground_truths: groundTruths,
      })
      message.success('数据集创建成功')
      handleCloseDatasetModal()
      fetchDatasets()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail || '数据集创建失败')
    }
  }

  // 任务控制：暂停 / 恢复 / 重试 全部
  const handlePauseTask = async (taskId: string) => {
    try {
      await api.post(`/v1/evaluation/tasks/${taskId}/pause`)
      message.success('已暂停任务')
      void fetchTasks()
    } catch {
      message.error('暂停失败')
    }
  }
  const handleResumeTask = async (taskId: string) => {
    try {
      await api.post(`/v1/evaluation/tasks/${taskId}/resume`)
      message.success('已恢复任务')
      void fetchTasks()
    } catch {
      message.error('恢复失败')
    }
  }
  const handleRetryTask = async (taskId: string, onlyFailed: boolean) => {
    try {
      const res = await api.post(
        `/v1/evaluation/tasks/${taskId}/retry?only_failed=${onlyFailed}`,
      )
      message.success(`已重新分发 ${res.data.re_dispatched} 题`)
      void fetchTasks()
    } catch {
      message.error('重试失败')
    }
  }
  const handleRetryQuestion = async (runId: string) => {
    try {
      await api.post(`/v1/evaluation/questions/${runId}/retry`)
      message.success('已重试该问题')
      if (liveTaskId) setLivePolling((v) => !v) // 触发重新拉取
      else void fetchTasks()
    } catch {
      message.error('重试失败')
    }
  }
  const handleSkipQuestion = async (runId: string) => {
    try {
      await api.post(`/v1/evaluation/questions/${runId}/skip`)
      message.success('已跳过该问题')
      if (liveTaskId) setLivePolling((v) => !v)
      else void fetchTasks()
    } catch {
      message.error('跳过失败')
    }
  }
  const handleOpenLive = (taskId: string) => {
    setLiveTaskId(taskId)
    setLiveQuestionRuns([])
    setLivePolling(true)
  }

  const handleCreateTask = async (values: {
    dataset_id: string
    kb_id: string
    metrics: string[]
  }) => {
    try {
      await api.post('/v1/evaluation/tasks', values)
      message.success('评测任务已创建并启动')
      setTaskModalVisible(false)
      taskForm.resetFields()
      fetchTasks()
    } catch {
      message.error('评测任务创建失败')
    }
  }

  const kbName = (id: string) => kbList.find((k) => k.id === id)?.name || id

  const datasetColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '知识库',
      dataIndex: 'kb_id',
      key: 'kb_id',
      render: (v: string) => kbName(v),
    },
    {
      title: '问题数',
      key: 'question_count',
      render: (_: string, record: EvaluationDataset) => record.questions.length,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (v: string) => new Date(v).toLocaleString(),
    },
  ]

  const taskColumns = [
    { title: 'ID', dataIndex: 'id', key: 'id', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (v: string) => <Tag color={STATUS_COLORS[v] || colors.textMuted}>{v}</Tag>,
    },
    {
      title: '知识库',
      dataIndex: 'kb_id',
      key: 'kb_id',
      render: (v: string) => kbName(v),
    },
    {
      title: '指标',
      dataIndex: 'metrics',
      key: 'metrics',
      render: (metrics: string[]) => (
        <Space wrap>
          {metrics.map((m) => (
            <Tag key={m}>{m}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: string, record: EvaluationTask) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => handleOpenLive(record.id)}>
            📊 监控
          </Button>
          <Button type="link" size="small" onClick={() => setSelectedTask(record)}>
            查看结果
          </Button>
        </Space>
      ),
    },
  ]

  const renderAggregatedResults = (task: EvaluationTask) => {
    const aggregated = (task.results?.aggregated || {}) as Record<string, unknown>
    const entries = Object.entries(aggregated).filter(([key]) => key !== 'samples')

    if (entries.length === 0) {
      const isRunning = task.status === 'running' || task.status === 'pending'
      return (
        <Alert
          type={isRunning ? 'info' : 'warning'}
          showIcon
          message={isRunning ? '任务正在运行…' : '暂无结果'}
          description={
            isRunning
              ? '评测任务由后台 Worker 执行，每条问题约需 15~30 秒（包含 embedding/retrieval/rerank/LLM-judge 共 4~6 次远程调用）。面板将每 3 秒自动刷新。'
              : '请确认评测指标与数据集无误，或重新运行一次评测。'
          }
        />
      )
    }

    const retrievalItems: Array<[string, unknown]> = []
    const generationItems: Array<[string, unknown]> = []
    entries.forEach(([k, v]) => {
      const def = METRIC_DEFINITIONS[k]
      if (def?.category === 'generation') generationItems.push([k, v])
      else retrievalItems.push([k, v])
    })

    const renderItem = (k: string, v: unknown) => {
      const def = METRIC_DEFINITIONS[k]
      const num = typeof v === 'number' ? v : Number(v)
      const isNum = !Number.isNaN(num)
      const color = isNum ? (num >= 0.8 ? '#52c41a' : num >= 0.5 ? '#faad14' : '#ff4d4f') : undefined
      return (
        <Descriptions.Item
          key={k}
          label={
            <Space size={4}>
              <Text strong style={{ color: def ? CATEGORY_COLORS[def.category] : undefined }}>
                {def ? def.name : k}
              </Text>
              {def && (
                <Tooltip
                  title={
                    <div>
                      <div>{def.desc}</div>
                      <div style={{ marginTop: 4, opacity: 0.7 }}>取值：{def.range}</div>
                    </div>
                  }
                >
                  <QuestionCircleOutlined style={{ color: '#999', fontSize: 12 }} />
                </Tooltip>
              )}
            </Space>
          }
        >
          {isNum ? (
            <span style={{ color, fontWeight: 600 }}>
              {num.toFixed(4)} {num >= 0.8 ? '✅' : num >= 0.5 ? '🟡' : '⚠️'}
            </span>
          ) : (
            String(v)
          )}
        </Descriptions.Item>
      )
    }

    return (
      <div>
        {retrievalItems.length > 0 && (
          <>
            <Text strong style={{ color: CATEGORY_COLORS.retrieval }}>🔍 检索质量指标</Text>
            <Descriptions bordered column={3} size="small" style={{ marginTop: 8, marginBottom: 16 }}>
              {retrievalItems.map(([k, v]) => renderItem(k, v))}
            </Descriptions>
          </>
        )}
        {generationItems.length > 0 && (
          <>
            <Text strong style={{ color: CATEGORY_COLORS.generation }}>✨ 生成质量指标</Text>
            <Descriptions bordered column={3} size="small" style={{ marginTop: 8 }}>
              {generationItems.map(([k, v]) => renderItem(k, v))}
            </Descriptions>
          </>
        )}
      </div>
    )
  }

  const renderPreviewPanel = () => {
    if (validating) return <Alert type="info" message="正在校验..." showIcon />
    if (!preview) return null
    return (
      <div style={{ marginTop: 8 }}>
        {preview.valid ? (
          <Alert
            type="success"
            showIcon
            icon={<CheckCircleOutlined />}
            message={`校验通过：${preview.item_count} 条问题`}
            description={
              preview.warnings.length ? (
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {preview.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              ) : null
            }
          />
        ) : (
          <Alert
            type="error"
            showIcon
            icon={<ExclamationCircleOutlined />}
            message="格式校验未通过"
            description={
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {preview.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            }
          />
        )}
        {preview.valid && preview.items.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic title="问题总数" value={preview.item_count} />
              </Col>
              <Col span={8}>
                <Statistic
                  title="含 chunk_ids"
                  value={preview.items.filter((i) => i.ground_truth.chunk_ids?.length).length}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="含 answer"
                  value={preview.items.filter((i) => i.ground_truth.answer).length}
                />
              </Col>
            </Row>
            <div
              style={{
                marginTop: 12,
                maxHeight: 220,
                overflow: 'auto',
                background: colors.codeBg,
                color: colors.codeText,
                padding: 12,
                borderRadius: radius.md,
                fontFamily: typography.mono,
                fontSize: 12,
              }}
            >
              <pre style={{ margin: 0 }}>
                {JSON.stringify(preview.items.slice(0, 5), null, 2)}
                {preview.items.length > 5 && `\n... 共 ${preview.items.length} 条`}
              </pre>
            </div>
          </div>
        )}
      </div>
    )
  }

  const tabItems = [
    {
      key: 'datasets',
      label: '评测数据集',
      children: (
        <DataCard
          title="评测数据集"
          extra={
            <Space>
              <Dropdown
                menu={{
                  items: SAMPLE_TEMPLATES.map((t) => ({
                    key: t.key,
                    label: (
                      <Space direction="vertical" size={0}>
                        <Text strong>{t.label}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {t.description}
                        </Text>
                      </Space>
                    ),
                  })),
                  onClick: ({ key }) => downloadTemplate(String(key)),
                }}
                placement="bottomRight"
              >
                <Button icon={<DownloadOutlined />}>下载样例模板</Button>
              </Dropdown>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setDatasetModalVisible(true)}
                style={{ background: colors.accent, borderColor: colors.accent }}
              >
                新建数据集
              </Button>
            </Space>
          }
        >
          <div
            style={{
              padding: 16,
              marginBottom: 16,
              background: colors.codeBg,
              borderRadius: radius.md,
              border: `1px solid ${colors.border}`,
            }}
          >
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Text strong>样例模板下载</Text>
              <Text type="secondary" style={{ fontSize: 13 }}>
                支持标准 JSON 格式（任选其一）。下载后修改问题与答案，再点击右上「新建数据集」上传即可。
              </Text>
              <Space wrap>
                {SAMPLE_TEMPLATES.map((t) => (
                  <Button
                    key={t.key}
                    icon={<DownloadOutlined />}
                    onClick={() => downloadTemplate(t.key)}
                    title={t.description}
                  >
                    {t.label}
                  </Button>
                ))}
              </Space>
              <Divider style={{ margin: '12px 0' }} />
              <Text strong style={{ color: colors.accent }}>
                🆕 v2 架构对齐模板（推荐）
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                含 kb_id / _dataset_meta / quality.max_allowed_distance，可量化向量化精准度。
              </Text>
              <Space wrap>
                <Button
                  type="primary"
                  icon={<DownloadOutlined />}
                  onClick={() => downloadV2Template('v2')}
                >
                  下载 v2 模板（架构对齐）
                </Button>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => downloadV2Template('v1')}
                >
                  下载 v1 JSONL
                </Button>
              </Space>
            </Space>
          </div>
          <Table
            rowKey="id"
            loading={loadingDatasets}
            dataSource={datasets}
            columns={datasetColumns}
          />
        </DataCard>
      ),
    },
    {
      key: 'tasks',
      label: '评测任务',
      children: (
        <DataCard
          title="评测任务"
          extra={
            <Space>
              <Button icon={<ReloadOutlined />} onClick={fetchTasks}>
                刷新
              </Button>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={() => setTaskModalVisible(true)}
                style={{ background: colors.accent, borderColor: colors.accent }}
              >
                运行评测
              </Button>
            </Space>
          }
        >
          <Table rowKey="id" loading={loadingTasks} dataSource={tasks} columns={taskColumns} />
        </DataCard>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        title="评测工作台"
        subtitle="构建评测数据集、运行评测任务并分析检索与生成质量"
      />

      <Tabs defaultActiveKey="datasets" items={tabItems} />

      {/* 新建数据集：上传 JSON 文件 + 预览校验 */}
      <Modal
        title="新建评测数据集"
        open={datasetModalVisible}
        onCancel={handleCloseDatasetModal}
        onOk={handleUploadSubmit}
        okButtonProps={{ loading: uploading, disabled: !preview?.valid }}
        okText="创建数据集"
        width={720}
      >
        <Form form={datasetForm} layout="vertical">
          <Form.Item
            name="kb_id"
            label="知识库"
            rules={[{ required: true, message: '请选择知识库' }]}
          >
            <Select placeholder="选择知识库">
              {kbList.map((kb) => (
                <Option key={kb.id} value={kb.id}>
                  {kb.name}
                </Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="name" label="数据集名称" rules={[{ required: true, message: '请输入数据集名称' }]}>
            <Input placeholder="不填则使用文件名（去掉 .json 后缀）" />
          </Form.Item>

          <Form.Item label="下载样例">
            <Space wrap>
              {SAMPLE_TEMPLATES.map((t) => (
                <Button
                  key={t.key}
                  size="small"
                  icon={<DownloadOutlined />}
                  onClick={() => downloadTemplate(t.key)}
                  title={t.description}
                >
                  {t.label}
                </Button>
              ))}
            </Space>
            <div style={{ marginTop: 4, fontSize: 12, color: colors.textMuted }}>
              点击下载标准 JSON 样例，修改后可直接拖入下方上传区
            </div>
          </Form.Item>

          <Form.Item label="上传 JSON 数据集" required>
            <Dragger
              name="file"
              multiple={false}
              maxCount={1}
              beforeUpload={handleBeforeUpload}
              onRemove={() => {
                setUploadFile(null)
                setPreview(null)
              }}
              fileList={uploadFile ? [uploadFile] : []}
              accept=".json,application/json"
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽 .json 文件到此处</p>
              <p className="ant-upload-hint">支持标准格式的评测数据集（≤10MB）</p>
            </Dragger>
          </Form.Item>

          {renderPreviewPanel()}

          <details style={{ marginTop: 16 }}>
            <summary style={{ cursor: 'pointer', color: colors.textMuted }}>
              查看 JSON 格式说明
            </summary>
            <pre
              style={{
                marginTop: 8,
                background: colors.codeBg,
                color: colors.codeText,
                padding: 12,
                borderRadius: radius.md,
                fontFamily: typography.mono,
                fontSize: 12,
                maxHeight: 240,
                overflow: 'auto',
              }}
            >
              {EVAL_DATASET_TEMPLATE}
            </pre>
          </details>

          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', color: colors.textMuted }}>
              或使用旧式文本输入（手动填写）
            </summary>
            <div style={{ marginTop: 8 }}>
              <Form.Item
                name="questions"
                label="问题列表（每行一个）"
                style={{ marginBottom: 8 }}
              >
                <TextArea rows={3} placeholder="每行一个问题" />
              </Form.Item>
              <Form.Item name="ground_truths" label="Ground Truth (JSON 数组)" style={{ marginBottom: 0 }}>
                <TextArea
                  rows={3}
                  placeholder='例如：[{"chunk_ids": ["id1"], "answer": "答案"}]'
                />
              </Form.Item>
            </div>
          </details>

          {/* 隐藏的 submit：保留旧 form 提交路径 */}
          <Form.Item style={{ display: 'none' }}>
            <Button htmlType="button" onClick={() => datasetForm.submit()} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 旧式 JSON 文本提交监听（保留兼容性） */}
      <Form form={datasetForm} onFinish={handleCreateDatasetByText} style={{ display: 'none' }} />

      <Modal
        title="运行评测"
        open={taskModalVisible}
        onCancel={() => setTaskModalVisible(false)}
        onOk={() => taskForm.submit()}
      >
        <Form form={taskForm} layout="vertical" onFinish={handleCreateTask}>
          <Form.Item
            name="dataset_id"
            label="数据集"
            rules={[{ required: true, message: '请选择数据集' }]}
          >
            <Select placeholder="选择数据集">
              {datasets.map((ds) => (
                <Option key={ds.id} value={ds.id}>
                  {ds.name} ({ds.questions.length} 题)
                </Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item
            name="kb_id"
            label="目标知识库"
            rules={[{ required: true, message: '请选择知识库' }]}
          >
            <Select placeholder="选择知识库">
              {kbList.map((kb) => (
                <Option key={kb.id} value={kb.id}>
                  {kb.name}
                </Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item
              name="metrics"
              label={
                <Space size={4}>
                  <span>评测指标</span>
                  <Tooltip
                    title={
                      <div style={{ maxWidth: 360 }}>
                        <div><b style={{ color: CATEGORY_COLORS.retrieval }}>🔍 检索类指标</b>：评估 chunk 检索质量</div>
                        <ul style={{ margin: '4px 0', paddingLeft: 20, fontSize: 12 }}>
                          {Object.entries(METRIC_DEFINITIONS)
                            .filter(([, d]) => d.category === 'retrieval')
                            .map(([k, d]) => (
                              <li key={k}><b>{d.name}</b>（{d.short}）：{d.desc}</li>
                            ))}
                        </ul>
                        <div><b style={{ color: CATEGORY_COLORS.generation }}>✨ 生成类指标</b>：由 LLM 评判（更慢、更贵）</div>
                        <ul style={{ margin: '4px 0', paddingLeft: 20, fontSize: 12 }}>
                          {Object.entries(METRIC_DEFINITIONS)
                            .filter(([, d]) => d.category === 'generation')
                            .map(([k, d]) => (
                              <li key={k}><b>{d.name}</b>（{d.short}）：{d.desc}</li>
                            ))}
                        </ul>
                      </div>
                    }
                  >
                    <QuestionCircleOutlined style={{ color: '#999' }} />
                  </Tooltip>
                </Space>
              }
              initialValue={[
                'recall@3',
                'mrr',
                'ndcg@3',
                'faithfulness',
                'relevance',
                'coherence',
              ]}
              extra={
                <Text type="secondary" style={{ fontSize: 12 }}>
                  光标悬停指标名查看详细说明；如只需快速评估检索质量，可取消生成类指标
                </Text>
              }
            >
              <Select mode="multiple" placeholder="选择指标">
                <Select.OptGroup label="🔍 检索质量指标">
                  <Option value="recall@3">Recall@3（召回率）</Option>
                  <Option value="mrr">MRR（平均倒数排名）</Option>
                  <Option value="ndcg@3">NDCG@3（归一化折损增益）</Option>
                </Select.OptGroup>
                <Select.OptGroup label="✨ 生成质量指标（LLM 评分）">
                  <Option value="faithfulness">Faithfulness（忠实度）</Option>
                  <Option value="relevance">Relevance（相关性）</Option>
                  <Option value="coherence">Coherence（连贯性）</Option>
                </Select.OptGroup>
              </Select>
            </Form.Item>
        </Form>
      </Modal>

      {/* ============ 实时监控 Modal ============ */}
      <Modal
        title={
          liveTaskId
            ? `任务实时监控 (${liveQuestionRuns.length} 题)`
            : '任务实时监控'
        }
        open={!!liveTaskId}
        onCancel={() => {
          setLiveTaskId(null)
          setLiveQuestionRuns([])
          setLivePolling(false)
        }}
        footer={null}
        width={900}
      >
        {liveTaskId && (
          <div>
            <Space style={{ marginBottom: 12 }} wrap>
              <Button
                size="small"
                onClick={async () => {
                  await handlePauseTask(liveTaskId)
                  setLivePolling(false)
                  setTimeout(() => setLivePolling(true), 100)
                }}
              >
                ⏸ 暂停全部
              </Button>
              <Button
                size="small"
                type="primary"
                onClick={async () => {
                  await handleResumeTask(liveTaskId)
                  setLivePolling(false)
                  setTimeout(() => setLivePolling(true), 100)
                }}
              >
                ▶ 恢复全部
              </Button>
              <Button
                size="small"
                danger
                onClick={() => handleRetryTask(liveTaskId, true)}
              >
                ↻ 重试全部失败题
              </Button>
              <Button
                size="small"
                onClick={() => handleRetryTask(liveTaskId, false)}
              >
                ↻ 重试全部未完成题
              </Button>
            </Space>

            {/* 进度条 + 统计 */}
            {(() => {
              const total = liveQuestionRuns.length
              const counts = {
                completed: liveQuestionRuns.filter((r) => r.status === 'completed').length,
                failed: liveQuestionRuns.filter((r) => r.status === 'failed').length,
                running: liveQuestionRuns.filter((r) => r.status === 'running').length,
                pending: liveQuestionRuns.filter((r) => r.status === 'pending').length,
                skipped: liveQuestionRuns.filter((r) => r.status === 'skipped').length,
                paused: liveQuestionRuns.filter((r) => r.status === 'paused').length,
              }
              const done = counts.completed + counts.failed + counts.skipped
              const pct = total > 0 ? Math.round((done / total) * 100) : 0
              return (
                <div style={{ marginBottom: 16 }}>
                  <Text strong style={{ fontSize: 13 }}>
                    整体进度: {done} / {total} ({pct}%)
                  </Text>
                  <div
                    style={{
                      display: 'flex',
                      height: 8,
                      borderRadius: 4,
                      overflow: 'hidden',
                      background: colors.codeBg,
                      marginTop: 4,
                    }}
                  >
                    {counts.completed > 0 && (
                      <div style={{ width: `${(counts.completed / total) * 100}%`, background: '#52c41a' }} />
                    )}
                    {counts.failed > 0 && (
                      <div style={{ width: `${(counts.failed / total) * 100}%`, background: '#ff4d4f' }} />
                    )}
                    {counts.skipped > 0 && (
                      <div style={{ width: `${(counts.skipped / total) * 100}%`, background: '#bfbfbf' }} />
                    )}
                    {counts.running > 0 && (
                      <div style={{ width: `${(counts.running / total) * 100}%`, background: '#1890ff', animation: 'pulse 1.5s infinite' }} />
                    )}
                    {counts.pending > 0 && (
                      <div style={{ width: `${(counts.pending / total) * 100}%`, background: '#d9d9d9' }} />
                    )}
                  </div>
                  <Space style={{ marginTop: 8 }} wrap>
                    <Tag color="green">✅ 完成 {counts.completed}</Tag>
                    <Tag color="red">❌ 失败 {counts.failed}</Tag>
                    <Tag color="blue">⏳ 运行中 {counts.running}</Tag>
                    <Tag>⏸ 队列 {counts.pending}</Tag>
                    <Tag color="default">⊘ 跳过 {counts.skipped}</Tag>
                    <Tag color="orange">⏸ 暂停 {counts.paused}</Tag>
                  </Space>
                </div>
              )
            })()}

            <Table
              rowKey="id"
              size="small"
              pagination={{
                pageSize: 10,
                pageSizeOptions: [10, 20, 50, 100],
                showSizeChanger: true,
                showTotal: (total) => `共 ${total} 题`,
              }}
              dataSource={liveQuestionRuns}
              columns={[
                {
                  title: '#',
                  dataIndex: 'question_index',
                  width: 40,
                  render: (v: number) => <Tag>{`#${v}`}</Tag>,
                },
                {
                  title: '状态',
                  dataIndex: 'status',
                  width: 100,
                  render: (s: string) => {
                    const map: Record<string, { color: string; txt: string }> = {
                      completed: { color: 'green', txt: '✅ 完成' },
                      failed: { color: 'red', txt: '❌ 失败' },
                      running: { color: 'blue', txt: '⏳ 运行中' },
                      pending: { color: 'default', txt: '⏸ 队列中' },
                      skipped: { color: 'default', txt: '⊘ 跳过' },
                      paused: { color: 'orange', txt: '⏸ 暂停' },
                    }
                    const m = map[s] || { color: 'default', txt: s }
                    return <Tag color={m.color}>{m.txt}</Tag>
                  },
                },
                {
                  title: '问题',
                  dataIndex: 'question',
                  ellipsis: true,
                },
                {
                  title: '尝试',
                  dataIndex: 'attempts',
                  width: 60,
                  render: (v: number) => (v > 0 ? `${v}次` : '—'),
                },
                {
                  title: '操作',
                  key: 'action',
                  width: 200,
                  render: (_: string, record: QuestionRun) => {
                    const canRetry = ['failed', 'paused', 'skipped'].includes(record.status)
                    const canSkip = ['pending', 'paused', 'failed', 'running'].includes(record.status)
                    return (
                      <Space size={4}>
                        {canRetry && (
                          <Button size="small" type="link" onClick={() => handleRetryQuestion(record.id)}>
                            ↻ 重试
                          </Button>
                        )}
                        {canSkip && (
                          <Button size="small" type="link" danger onClick={() => handleSkipQuestion(record.id)}>
                            ⊘ 跳过
                          </Button>
                        )}
                      </Space>
                    )
                  },
                },
              ]}
            />
          </div>
        )}
      </Modal>

      <Modal
        title="评测结果"
        open={!!selectedTask}
        onCancel={() => setSelectedTask(null)}
        footer={null}
        width={800}
      >
        {selectedTask && (
          <div>
            <Descriptions size="small" column={2}>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_COLORS[selectedTask.status] || colors.textMuted}>
                  {selectedTask.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="指标">
                {selectedTask.metrics.join(', ')}
              </Descriptions.Item>
            </Descriptions>
            <div style={{ marginTop: 16 }}>
              <Text strong>聚合指标</Text>
              {renderAggregatedResults(selectedTask)}
            </div>
            {Boolean((selectedTask.results?.aggregated as Record<string, unknown> | undefined)?.samples) && (
              <div style={{ marginTop: 16 }}>
                <Text strong>样本详情</Text>
                <pre
                  style={{
                    maxHeight: 300,
                    overflow: 'auto',
                    background: colors.codeBg,
                    color: colors.codeText,
                    padding: 12,
                    borderRadius: radius.md,
                    fontFamily: typography.mono,
                  }}
                >
                  {JSON.stringify(
                    (selectedTask.results?.aggregated as Record<string, unknown> | undefined)?.samples,
                    null,
                    2,
                  )}
                </pre>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}

export default EvalWorkbench
