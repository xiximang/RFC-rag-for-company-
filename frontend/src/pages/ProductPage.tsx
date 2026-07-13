import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Typography,
  Card,
  Row,
  Col,
  Tabs,
  Steps,
  Descriptions,
  Alert,
  Space,
  Tag,
  Divider,
  Button,
  Collapse,
} from 'antd'
import {
  LockOutlined,
  SafetyOutlined,
  ApiOutlined,
  CloudServerOutlined,
  SearchOutlined,
  FileTextOutlined,
  TeamOutlined,
  KeyOutlined,
  GlobalOutlined,
  ArrowRightOutlined,
  DatabaseOutlined,
  BranchesOutlined,
  EyeOutlined,
  MessageOutlined,
} from '@ant-design/icons'

const { Title, Paragraph, Text } = Typography
const { Step } = Steps
const { Panel } = Collapse

const brandColor = '#1a1a1a'
const accentColor = '#e57035'
const mutedColor = '#6b7280'
const surfaceColor = '#fafafa'

interface AnimatedSectionProps {
  children: React.ReactNode
  delay?: number
}

const AnimatedSection: React.FC<AnimatedSectionProps> = ({ children, delay = 0 }) => {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTimeout(() => setVisible(true), delay)
          observer.disconnect()
        }
      },
      { threshold: 0.1 }
    )
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [delay])

  return (
    <div
      ref={ref}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(24px)',
        transition: 'opacity 600ms cubic-bezier(0.16, 1, 0.3, 1), transform 600ms cubic-bezier(0.16, 1, 0.3, 1)',
      }}
    >
      {children}
    </div>
  )
}

/**
 * Flow diagram card: shows a horizontal pipeline of nodes with arrow connectors.
 * Used in the Quick Start section to visualise data / query / permission / integration flows.
 */
interface FlowStep {
  node: string
  icon: string
  color: string
  hint: string
}

interface FlowDiagramCardProps {
  title: string
  subtitle: string
  steps: FlowStep[]
  gradient: string
}

const FlowDiagramCard: React.FC<FlowDiagramCardProps> = ({ title, subtitle, steps, gradient }) => {
  return (
    <Col xs={24} lg={12}>
      <Card
        style={{ borderRadius: 16, border: '1px solid #e5e7eb', height: '100%' }}
        bodyStyle={{ padding: '24px 22px 28px' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <div
            style={{
              width: 4,
              height: 22,
              background: gradient,
              borderRadius: 2,
            }}
          />
          <Title level={5} style={{ margin: 0, color: brandColor }}>
            {title}
          </Title>
        </div>
        <Text style={{ color: mutedColor, fontSize: 12, display: 'block', marginBottom: 20 }}>
          {subtitle}
        </Text>

        {/* Flow nodes */}
        <div
          style={{
            display: 'flex',
            alignItems: 'stretch',
            gap: 0,
            overflowX: 'auto',
            paddingBottom: 4,
          }}
        >
          {steps.map((s, idx) => (
            <div
              key={idx}
              style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}
            >
              {/* Node */}
              <div
                style={{
                  minWidth: 92,
                  maxWidth: 110,
                  padding: '12px 8px',
                  borderRadius: 10,
                  background: `linear-gradient(135deg, ${s.color}15 0%, ${s.color}08 100%)`,
                  border: `1px solid ${s.color}40`,
                  textAlign: 'center',
                  position: 'relative',
                }}
                title={s.hint}
              >
                <div style={{ fontSize: 22, marginBottom: 4 }}>{s.icon}</div>
                <div
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: brandColor,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {s.node}
                </div>
                <div
                  style={{
                    position: 'absolute',
                    top: -8,
                    right: -8,
                    width: 18,
                    height: 18,
                    borderRadius: '50%',
                    background: s.color,
                    color: '#fff',
                    fontSize: 10,
                    fontWeight: 700,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    boxShadow: `0 2px 6px ${s.color}55`,
                  }}
                >
                  {idx + 1}
                </div>
              </div>
              {/* Arrow connector */}
              {idx < steps.length - 1 && (
                <div
                  style={{
                    width: 24,
                    height: 2,
                    background: `linear-gradient(90deg, ${s.color} 0%, ${steps[idx + 1].color} 100%)`,
                    position: 'relative',
                    flexShrink: 0,
                    margin: '0 2px',
                  }}
                >
                  <div
                    style={{
                      position: 'absolute',
                      right: -1,
                      top: -4,
                      width: 0,
                      height: 0,
                      borderLeft: `6px solid ${steps[idx + 1].color}`,
                      borderTop: '5px solid transparent',
                      borderBottom: '5px solid transparent',
                    }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Hints list */}
        <div style={{ marginTop: 18, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {steps.map((s, idx) => (
            <div
              key={idx}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 11,
                color: mutedColor,
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: s.color,
                  flexShrink: 0,
                }}
              />
              <span style={{ fontWeight: 600, color: '#374151' }}>{s.node}:</span>
              <span>{s.hint}</span>
            </div>
          ))}
        </div>
      </Card>
    </Col>
  )
}

const painPoints = [
  {
    title: '数据孤岛',
    subtitle: '知识分散在多个系统',
    desc: '文档、图纸、音视频、数据库记录分散在多个业务系统中，传统搜索无法跨模态、跨系统统一检索。',
    icon: <SearchOutlined style={{ fontSize: 24, color: accentColor }} />,
  },
  {
    title: '安全合规',
    subtitle: '数据不出域的刚需',
    desc: '金融、制造、政务等行业对数据出境和云端 SaaS 有严格限制，需要可私有化部署、满足审计与合规的 RAG 方案。',
    icon: <SafetyOutlined style={{ fontSize: 24, color: accentColor }} />,
  },
  {
    title: '权限失控',
    subtitle: '通用 RAG 的安全短板',
    desc: '通用 RAG 往往忽略企业已有 ACL，导致低权限用户检索到高密级内容，不同部门越权访问。',
    icon: <LockOutlined style={{ fontSize: 24, color: accentColor }} />,
  },
  {
    title: '多模态理解',
    subtitle: '非结构化数据难以利用',
    desc: '合同、报表、设计图、培训视频等难以被 LLM 直接理解，需要统一的多模态解析、索引与检索能力。',
    icon: <FileTextOutlined style={{ fontSize: 24, color: accentColor }} />,
  },
  {
    title: '集成困难',
    subtitle: '外部系统调用成本高',
    desc: 'OA、IM、ERP、BI 等系统希望调用 RAG 能力，但缺乏标准、安全、可审计的 API 接入方案。',
    icon: <ApiOutlined style={{ fontSize: 24, color: accentColor }} />,
  },
  {
    title: '来源不可信',
    subtitle: '生成结果无法验证',
    desc: '大模型幻觉导致答案不可信，企业需要每一条回答都能追溯到原始文档和具体片段。',
    icon: <BranchesOutlined style={{ fontSize: 24, color: accentColor }} />,
  },
]

const permissionLayers = [
  {
    title: '身份层',
    desc: '用户 / 用户组 / 部门 / 安全等级',
    items: ['JWT 登录与令牌刷新', '按职级与部门属性过滤'],
    icon: <TeamOutlined />,
  },
  {
    title: '知识库层',
    desc: '知识库级可见性',
    items: ['知识库可见性控制', '按用户组授权读写'],
    icon: <DatabaseOutlined />,
  },
  {
    title: '文档层',
    desc: '文档级 ACL',
    items: ['允许/拒绝列表', '按用户/用户组授权'],
    icon: <FileTextOutlined />,
  },
  {
    title: '字段层',
    desc: '敏感字段与文件类型',
    items: ['按文件类型授权', '敏感字段脱敏或拒绝'],
    icon: <EyeOutlined />,
  },
  {
    title: '标签层',
    desc: '多维度动态标签',
    items: ['密级 / 部门 / 项目标签', '批量授权与回收'],
    icon: <Tag color="transparent">TAG</Tag>,
  },
]

const ragSteps = [
  { title: '多模态接入', desc: '文档、图片、音视频、链接统一接入' },
  { title: '智能解析', desc: 'OCR、ASR、表格与结构提取' },
  { title: '向量化索引', desc: '多模态 Embedding 写入 Milvus' },
  { title: '混合检索', desc: '向量 + BM25 + Rerank 召回' },
  { title: '权限过滤', desc: '五级权限实时过滤结果' },
  { title: '可信生成', desc: '带引用溯源的流式回答' },
]

/* ──────────────── 快速入手 Quick Start ──────────────── */

const quickStartSteps = [
  {
    no: '01',
    title: '登录系统',
    desc: '使用 admin / admin123 登录工作台；首次登录后可进入「系统配置」修改密码。',
    icon: '🔑',
    color: '#3b82f6',
    detail: ['浏览器访问 http://localhost:3002', '默认账号 admin / admin123', '登录后默认进入「知识库」工作台'],
  },
  {
    no: '02',
    title: '创建知识库',
    desc: '在「知识库 → 我的知识库」点击「+ 新建知识库」，填写名称与描述，可见范围选择「公开 / 部门 / 指定用户」。',
    icon: '📚',
    color: '#8b5cf6',
    detail: ['名称建议使用业务名，如"财务制度"', '可见范围决定谁能检索该 KB', '创建后自动获得 KB ID，可用于 API 调用'],
  },
  {
    no: '03',
    title: '上传文档',
    desc: '在「上传中心」选择目标 KB，拖拽或选择文件上传。支持 PDF、Word、Excel、图片、音视频等 100+ 格式。',
    icon: '📤',
    color: '#06b6d4',
    detail: ['单文件 ≤ 500 MB，批量 ≤ 50 个', '支持链接型文档（URL 自动抓取）', '后台自动解析、切分、向量化'],
  },
  {
    no: '04',
    title: '检索与问答',
    desc: '在「搜索控制台」选择 KB，输入问题即可触发混合检索；或到「聊天」创建会话，享受多轮对话。',
    icon: '🔍',
    color: accentColor,
    detail: ['支持语义 / 关键词 / 混合三种检索', '每条回答附原文引用（可追溯）', '支持流式输出与敏感词拦截'],
  },
  {
    no: '05',
    title: '权限与集成',
    desc: '在「权限管理」配置 L1-L4 四级权限，在「API Key」生成对外接口，OA / IM / ERP 即可对接。',
    icon: '🔐',
    color: '#10b981',
    detail: ['L1 文件类型 / L2 文档 / L3 字段 / L4 标签', 'API Key 支持 scope 粒度控制', 'Kong 网关统一暴露对外 API'],
  },
]

const documentLifecycle = [
  { node: '上传文件', icon: '📤', color: '#3b82f6', hint: '用户拖拽 / API 上传' },
  { node: '格式识别', icon: '🔎', color: '#06b6d4', hint: 'PDF / Word / Excel / 图片 / 音视频 / URL' },
  { node: '智能解析', icon: '⚙️', color: '#0ea5e9', hint: 'OCR + 表格识别 + ASR + 结构提取' },
  { node: '切片入库', icon: '🧩', color: '#6366f1', hint: '按段落 / 标题 / 语义切分为 Chunk' },
  { node: '向量化', icon: '🧠', color: '#8b5cf6', hint: 'Embedding 模型写入向量库' },
  { node: '索引完成', icon: '✅', color: '#10b981', hint: 'Chunk 可被检索与问答' },
]

const retrievalFlow = [
  { node: '用户提问', icon: '💬', color: '#3b82f6', hint: '选择 KB + 自然语言问题' },
  { node: '查询改写', icon: '✍️', color: '#06b6d4', hint: '同义词、口语化 → 标准表达' },
  { node: '混合检索', icon: '🔀', color: accentColor, hint: '向量 + 关键词并行召回' },
  { node: 'Rerank', icon: '🎯', color: '#f59e0b', hint: '精排模型重排序 Top-K' },
  { node: '权限过滤', icon: '🛡️', color: '#10b981', hint: 'L1-L4 实时过滤 Chunk' },
  { node: '带引用生成', icon: '📝', color: '#ef4444', hint: 'LLM 输出 + 来源标注' },
]

const permissionFlow = [
  { node: '用户登录', icon: '👤', color: '#3b82f6', hint: 'JWT 解析身份 / 部门 / 安全等级' },
  { node: 'KB 授权', icon: '📚', color: '#06b6d4', hint: '判断 KB 是否对用户可见' },
  { node: '文档 ACL', icon: '📄', color: '#0ea5e9', hint: '允许 / 拒绝列表匹配' },
  { node: '字段过滤', icon: '🔍', color: '#6366f1', hint: 'L1 文件类型 + L3 敏感字段' },
  { node: '标签匹配', icon: '🏷️', color: '#8b5cf6', hint: 'L4 密级 / 部门 / 项目标签' },
  { node: '授权结果', icon: '✅', color: '#10b981', hint: '仅返回授权 Chunk' },
]

const integrationFlow = [
  { node: '外部系统', icon: '🏢', color: '#3b82f6', hint: 'OA / IM / ERP / BI' },
  { node: 'Kong 网关', icon: '🌐', color: '#06b6d4', hint: '统一入口 + 限流 + 审计' },
  { node: '认证鉴权', icon: '🔐', color: '#0ea5e9', hint: 'JWT 或 API Key (scope 隔离)' },
  { node: '后端服务', icon: '⚙️', color: accentColor, hint: 'FastAPI + 异步处理' },
  { node: 'RAG 引擎', icon: '🧠', color: '#8b5cf6', hint: '检索 + 权限 + LLM 生成' },
  { node: '结果返回', icon: '📤', color: '#10b981', hint: '带引用的 JSON 响应' },
]

const externalAuthTabs = [
  {
    key: 'kong',
    label: 'Kong 网关',
    icon: <GlobalOutlined />,
    content: (
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Paragraph style={{ fontSize: 16, color: '#374151' }}>
          所有外部流量先经过 Kong 统一入口，再路由到前端或后端服务。Kong 负责限流、日志、监控，并可按需开启认证插件。
        </Paragraph>
        <Descriptions
          bordered
          column={{ xs: 1, md: 2 }}
          size="middle"
          labelStyle={{ background: '#f9fafb', fontWeight: 500 }}
        >
          <Descriptions.Item label="代理端口">8000 / 8443</Descriptions.Item>
          <Descriptions.Item label="管理端口">8001 / 8444</Descriptions.Item>
          <Descriptions.Item label="后端路由">/api → app-backend:8080</Descriptions.Item>
          <Descriptions.Item label="前端路由">/ → frontend:80</Descriptions.Item>
          <Descriptions.Item label="当前限流">100 请求/分钟</Descriptions.Item>
          <Descriptions.Item label="可扩展插件">key-auth / jwt / cors</Descriptions.Item>
        </Descriptions>
        <Alert
          message="生产建议"
          description="生产环境建议在 Kong 开启 key-auth 或 openid-connect，统一校验调用方身份，并在网关层统一配置 CORS、限流和审计日志。"
          type="info"
          showIcon
          style={{ background: '#eff6ff', borderColor: '#bfdbfe' }}
        />
      </Space>
    ),
  },
  {
    key: 'jwt',
    label: 'JWT 认证',
    icon: <KeyOutlined />,
    content: (
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Paragraph style={{ fontSize: 16, color: '#374151' }}>
          后端基于 FastAPI OAuth2 Password Bearer 实现 JWT 认证。外部系统先登录获取 token，后续请求在 Header 中携带。
        </Paragraph>
        <pre
          style={{
            background: '#1a1a1a',
            color: '#f3f4f6',
            padding: 16,
            borderRadius: 8,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
            fontSize: 14,
            overflow: 'auto',
          }}
        >
{`Authorization: Bearer <access_token>`}
        </pre>
        <Descriptions
          bordered
          column={{ xs: 1, md: 2 }}
          size="middle"
          labelStyle={{ background: '#f9fafb', fontWeight: 500 }}
        >
          <Descriptions.Item label="算法">HS256</Descriptions.Item>
          <Descriptions.Item label="Token 有效期">30 分钟（可配置）</Descriptions.Item>
          <Descriptions.Item label="Token 载体">user_id / username / security_level</Descriptions.Item>
          <Descriptions.Item label="刷新机制">access_token + refresh_token</Descriptions.Item>
        </Descriptions>
      </Space>
    ),
  },
  {
    key: 'apikey',
    label: 'API Key',
    icon: <ApiOutlined />,
    content: (
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Paragraph style={{ fontSize: 16, color: '#374151' }}>
          针对服务器间调用，Kong 已预留 key-auth 配置。每个外部系统分配独立 API Key，在请求头中携带即可。
        </Paragraph>
        <pre
          style={{
            background: '#1a1a1a',
            color: '#f3f4f6',
            padding: 16,
            borderRadius: 8,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
            fontSize: 14,
            overflow: 'auto',
          }}
        >
{`api-key: <your-api-key>`}
        </pre>
        <Alert
          message="与 JWT 的互补关系"
          description="API Key 适合系统间无会话调用；JWT 适合用户级有状态调用。两者可在 Kong 分层组合使用。"
          type="warning"
          showIcon
          style={{ background: '#fffbeb', borderColor: '#fcd34d' }}
        />
      </Space>
    ),
  },
  {
    key: 'call',
    label: '调用示例',
    icon: <CloudServerOutlined />,
    content: (
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Paragraph style={{ fontSize: 16, color: '#374151' }}>
          以下示例展示外部系统如何通过 Kong 网关完成登录并调用检索接口。
        </Paragraph>
        <pre
          style={{
            background: '#1a1a1a',
            color: '#f3f4f6',
            padding: 16,
            borderRadius: 8,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
            fontSize: 13,
            overflow: 'auto',
            lineHeight: 1.7,
          }}
        >
{`# 1. 登录获取 token
curl -X POST http://localhost:8000/api/v1/auth/login \\
  -d "username=admin&password=admin"

# 2. 调用检索接口
curl -X POST http://localhost:8000/api/v1/search \\
  -H "Authorization: Bearer <token>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "query": "本季度营收情况",
    "kb_ids": ["<kb-id>"],
    "top_k": 5,
    "rerank_top_k": 3
  }'`}
        </pre>
      </Space>
    ),
  },
]

const ProductPage = () => {
  const navigate = useNavigate()
  const [activeAuthTab, setActiveAuthTab] = useState('kong')

  return (
    <div style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif' }}>
      {/* Hero */}
      <AnimatedSection>
        <div
          style={{
            position: 'relative',
            padding: '80px 0 64px',
            margin: '-24px -24px 48px',
            background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              position: 'absolute',
              top: '-20%',
              right: '-10%',
              width: 500,
              height: 500,
              background: 'radial-gradient(circle, rgba(229,112,53,0.25) 0%, transparent 70%)',
              borderRadius: '50%',
              filter: 'blur(60px)',
            }}
          />
          <div style={{ position: 'relative', zIndex: 1, maxWidth: 880, padding: '0 24px' }}>
            <Title level={1} style={{ wordBreak: 'break-word', overflowWrap: 'break-word', color: '#fff', marginBottom: 20, fontSize: 48, fontWeight: 600, letterSpacing: '-0.02em' }}>
              让企业知识
              <br />
              <span style={{ color: accentColor }}>安全、可信、可溯源</span>
            </Title>
            <Paragraph style={{ wordBreak: 'break-word', overflowWrap: 'break-word', color: 'rgba(255,255,255,0.75)', fontSize: 18, lineHeight: 1.7, maxWidth: 680, marginBottom: 32 }}>
              面向金融、制造、政务、能源等行业，提供数据不出域、权限可管控、来源可追溯、多模态可理解的企业知识检索与生成平台。
            </Paragraph>
            <Space size="middle">
              <Button
                type="primary"
                size="large"
                icon={<ArrowRightOutlined />}
                style={{ background: accentColor, borderColor: accentColor, borderRadius: 6 }}
                onClick={() => document.getElementById('rag-architecture')?.scrollIntoView({ behavior: 'smooth' })}
              >
                了解架构
              </Button>
              <Button
                ghost
                size="large"
                style={{ borderColor: 'rgba(255,255,255,0.4)', color: '#fff', borderRadius: 6 }}
                onClick={() => document.getElementById('external-auth')?.scrollIntoView({ behavior: 'smooth' })}
              >
                接入方案
              </Button>
            </Space>
          </div>
        </div>
      </AnimatedSection>

      {/* Quick Start */}
      <AnimatedSection delay={100}>
        <div style={{ marginBottom: 80 }}>
          <div style={{ textAlign: 'center', marginBottom: 48 }}>
            <Text style={{ color: accentColor, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              快速入手
            </Text>
            <Title level={2} style={{ marginTop: 8, marginBottom: 12, color: brandColor }}>
              5 步跑通从登录到集成
            </Title>
            <Paragraph style={{ color: mutedColor, fontSize: 16, maxWidth: 720, margin: '0 auto' }}>
              从账号登录到外部系统对接，下面是完整的上手路径和系统内部的 4 条核心流程。
            </Paragraph>
          </div>

          {/* 5-step onboarding timeline */}
          <Card
            style={{ borderRadius: 16, border: '1px solid #e5e7eb', marginBottom: 40 }}
            bodyStyle={{ padding: '40px 24px 32px' }}
          >
            <Row gutter={[20, 28]}>
              {quickStartSteps.map((s, idx) => (
                <Col xs={24} md={12} lg={idx === 4 ? 24 : 8} key={idx}>
                  <div
                    style={{
                      position: 'relative',
                      padding: '24px 22px',
                      borderRadius: 12,
                      background: '#fff',
                      border: '1px solid #e5e7eb',
                      height: '100%',
                      transition: 'all 200ms',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        marginBottom: 14,
                      }}
                    >
                      <div
                        style={{
                          width: 40,
                          height: 40,
                          borderRadius: 10,
                          background: `linear-gradient(135deg, ${s.color} 0%, ${s.color}dd 100%)`,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: '#fff',
                          fontSize: 22,
                          flexShrink: 0,
                          boxShadow: `0 4px 12px ${s.color}33`,
                        }}
                      >
                        {s.icon}
                      </div>
                      <div style={{ fontFamily: 'ui-monospace, monospace', fontSize: 13, color: s.color, fontWeight: 700 }}>
                        STEP {s.no}
                      </div>
                    </div>
                    <Title level={5} style={{ margin: 0, marginBottom: 8, color: brandColor }}>
                      {s.title}
                    </Title>
                    <Paragraph style={{ color: '#4b5563', marginBottom: 14, fontSize: 13, lineHeight: 1.7 }}>
                      {s.desc}
                    </Paragraph>
                    <ul style={{ paddingLeft: 18, margin: 0, color: mutedColor, fontSize: 12, lineHeight: 1.9 }}>
                      {s.detail.map((d, i) => (
                        <li key={i}>{d}</li>
                      ))}
                    </ul>
                  </div>
                </Col>
              ))}
            </Row>
          </Card>

          {/* Flow Diagrams */}
          <Row gutter={[20, 20]}>
            <FlowDiagramCard
              title="文档生命周期"
              subtitle="上传文件 → 智能解析 → 向量索引"
              steps={documentLifecycle}
              gradient="linear-gradient(135deg, #3b82f6 0%, #10b981 100%)"
            />
            <FlowDiagramCard
              title="检索与生成流程"
              subtitle="用户提问 → 混合检索 → 带引用回答"
              steps={retrievalFlow}
              gradient={`linear-gradient(135deg, ${accentColor} 0%, #ef4444 100%)`}
            />
            <FlowDiagramCard
              title="权限过滤流程"
              subtitle="四级穿透 → 默认拒绝 → 最小授权"
              steps={permissionFlow}
              gradient="linear-gradient(135deg, #06b6d4 0%, #8b5cf6 100%)"
            />
            <FlowDiagramCard
              title="外部系统集成"
              subtitle="OA / IM / ERP → Kong 网关 → RAG 引擎"
              steps={integrationFlow}
              gradient="linear-gradient(135deg, #10b981 0%, #3b82f6 100%)"
            />
          </Row>
        </div>
      </AnimatedSection>

      {/* Pain Points */}
      <AnimatedSection delay={100}>
        <div style={{ marginBottom: 80 }}>
          <div style={{ textAlign: 'center', marginBottom: 48 }}>
            <Text style={{ color: accentColor, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              行业痛点
            </Text>
            <Title level={2} style={{ marginTop: 8, marginBottom: 12, color: brandColor }}>
              为什么企业需要私有化 RAG？
            </Title>
            <Paragraph style={{ wordBreak: 'break-word', color: mutedColor, fontSize: 16, maxWidth: 640, margin: '0 auto' }}>
              通用大模型与 SaaS 搜索无法满足企业对安全、权限、溯源和多模态的核心诉求。
            </Paragraph>
          </div>
          <Row gutter={[24, 24]}>
            {painPoints.map((p, idx) => (
              <Col xs={24} md={12} lg={8} key={idx}>
                <Card
                  hoverable
                  style={{
                    height: '100%',
                    borderRadius: 12,
                    border: '1px solid #e5e7eb',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                    transition: 'transform 200ms, box-shadow 200ms',
                  }}
                  bodyStyle={{ padding: 28 }}
                >
                  <div style={{ marginBottom: 16 }}>{p.icon}</div>
                  <Text style={{ color: mutedColor, fontSize: 13, fontWeight: 500 }}>{p.subtitle}</Text>
                  <Title level={4} style={{ marginTop: 4, marginBottom: 12, color: brandColor }}>
                    {p.title}
                  </Title>
                  <Paragraph style={{ wordBreak: 'break-word', color: '#4b5563', marginBottom: 0, lineHeight: 1.7 }}>
                    {p.desc}
                  </Paragraph>
                </Card>
              </Col>
            ))}
          </Row>
        </div>
      </AnimatedSection>

      {/* Permission Structure */}
      <AnimatedSection delay={100}>
        <div style={{ marginBottom: 80, padding: '64px 0', background: surfaceColor, margin: '0 -24px 80px', paddingLeft: 24, paddingRight: 24 }}>
          <div style={{ textAlign: 'center', marginBottom: 48 }}>
            <Text style={{ color: accentColor, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              权限结构
            </Text>
            <Title level={2} style={{ marginTop: 8, marginBottom: 12, color: brandColor }}>
              默认拒绝，五级穿透
            </Title>
            <Paragraph style={{ wordBreak: 'break-word', color: mutedColor, fontSize: 16, maxWidth: 640, margin: '0 auto' }}>
              从身份到标签逐层过滤，确保检索与生成内容严格受控，每一条结果都经过授权。
            </Paragraph>
          </div>
          <Row gutter={[24, 24]}>
            {permissionLayers.map((layer, idx) => (
              <Col xs={24} md={12} lg={idx === 0 ? 24 : 12 } key={idx}>
                <Card
                  style={{
                    borderRadius: 12,
                    border: '1px solid #e5e7eb',
                    height: idx === 0 ? 'auto' : '100%',
                  }}
                  bodyStyle={{ padding: 24 }}
                >
                  <Space align="start" size="middle">
                    <div
                      style={{
                        width: 44,
                        height: 44,
                        borderRadius: 10,
                        background: '#fff7ed',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: accentColor,
                        fontSize: 20,
                        flexShrink: 0,
                      }}
                    >
                      {layer.icon}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <Title level={5} style={{ margin: 0, marginBottom: 4, color: brandColor }}>
                        {layer.title}
                      </Title>
                      <Paragraph style={{ color: mutedColor, marginBottom: 12, fontSize: 13 }}>
                        {layer.desc}
                      </Paragraph>
                      <Space wrap>
                        {layer.items.map((item, i) => (
                          <Tag key={i} color="default" style={{ background: '#fff', borderColor: '#e5e7eb', color: '#374151' }}>
                            {item}
                          </Tag>
                        ))}
                      </Space>
                    </div>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
          <Divider style={{ margin: '48px 0' }} />
          <Collapse ghost expandIconPosition="end">
            <Panel
              header={<Text strong style={{ color: brandColor, fontSize: 16 }}>查看完整权限校验流程</Text>}
              key="flow"
            >
              <Steps direction="vertical" size="small" current={-1}>
                <Step title="身份认证" description="JWT 解析用户身份、安全等级与部门属性" />
                <Step title="知识库授权" description="判断用户是否有该知识库访问权限" />
                <Step title="文档 ACL" description="检查文档允许/拒绝列表" />
                <Step title="字段/类型过滤" description="按文件类型和敏感字段配置过滤或脱敏" />
                <Step title="标签匹配" description="按密级、部门、项目等标签动态过滤" />
                <Step title="结果返回" description="仅返回用户被授权看到的 Chunk" />
              </Steps>
            </Panel>
          </Collapse>
        </div>
      </AnimatedSection>

      {/* RAG Architecture */}
      <AnimatedSection delay={100}>
        <div id="rag-architecture" style={{ marginBottom: 80 }}>
          <div style={{ textAlign: 'center', marginBottom: 48 }}>
            <Text style={{ color: accentColor, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              RAG 架构
            </Text>
            <Title level={2} style={{ marginTop: 8, marginBottom: 12, color: brandColor }}>
              从数据到答案的完整闭环
            </Title>
            <Paragraph style={{ wordBreak: 'break-word', color: mutedColor, fontSize: 16, maxWidth: 640, margin: '0 auto' }}>
              多模态接入、统一解析、混合检索、权限过滤、带引用溯源的生成。
            </Paragraph>
          </div>
          <Card
            style={{ borderRadius: 16, border: '1px solid #e5e7eb', marginBottom: 32 }}
            bodyStyle={{ padding: '32px 24px' }}
          >
            <div style={{ overflowX: 'auto' }}>
              <Steps direction="horizontal" size="small" current={-1} responsive>
                {ragSteps.map((s, idx) => (
                  <Step key={idx} title={s.title} description={s.desc} />
                ))}
              </Steps>
            </div>
          </Card>
          <Row gutter={[24, 24]}>
            <Col xs={24} md={12}>
              <Card
                title={<Text strong style={{ color: brandColor, fontSize: 16 }}>核心组件</Text>}
                style={{ borderRadius: 12, border: '1px solid #e5e7eb', height: '100%' }}
              >
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="Web 框架">FastAPI + Python 3.11</Descriptions.Item>
                  <Descriptions.Item label="向量数据库">Milvus 2.4</Descriptions.Item>
                  <Descriptions.Item label="关系数据库">PostgreSQL 16</Descriptions.Item>
                  <Descriptions.Item label="缓存">Redis 7</Descriptions.Item>
                  <Descriptions.Item label="消息队列">RabbitMQ 3</Descriptions.Item>
                  <Descriptions.Item label="对象存储">MinIO</Descriptions.Item>
                  <Descriptions.Item label="网关">Kong 3.5</Descriptions.Item>
                  <Descriptions.Item label="前端">React 18 + Vite + Ant Design 5</Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>
            <Col xs={24} md={12}>
              <Card
                title={<Text strong style={{ color: brandColor, fontSize: 16 }}>关键特性</Text>}
                style={{ borderRadius: 12, border: '1px solid #e5e7eb', height: '100%' }}
              >
                <ul style={{ paddingLeft: 18, margin: 0, color: '#374151', lineHeight: 2 }}>
                  <li>多模态 Chunk 与统一 embedding</li>
                  <li>向量 + 关键词 + Rerank 混合检索</li>
                  <li>检索结果权限实时过滤</li>
                  <li>聊天消息来源可追溯</li>
                  <li>流式输出与敏感词拦截</li>
                  <li>对话、反馈、协作与评测闭环</li>
                  <li>Prometheus + Grafana 可观测</li>
                </ul>
              </Card>
            </Col>
          </Row>
        </div>
      </AnimatedSection>

      {/* External Auth & Call */}
      <AnimatedSection delay={100}>
        <div id="external-auth" style={{ marginBottom: 40 }}>
          <div style={{ textAlign: 'center', marginBottom: 48 }}>
            <Text style={{ color: accentColor, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              外部接入
            </Text>
            <Title level={2} style={{ marginTop: 8, marginBottom: 12, color: brandColor }}>
              鉴权与调用方案
            </Title>
            <Paragraph style={{ color: mutedColor, fontSize: 16, maxWidth: 640, margin: '0 auto' }}>
              通过 Kong 网关统一接入，支持 JWT、API Key 等多种鉴权方式，提供标准 RESTful API。
            </Paragraph>
          </div>
          <Card
            style={{ borderRadius: 16, border: '1px solid #e5e7eb' }}
            bodyStyle={{ padding: 32 }}
          >
            <Tabs
              activeKey={activeAuthTab}
              onChange={setActiveAuthTab}
              tabBarStyle={{ flexWrap: 'wrap' }}
              items={externalAuthTabs.map((t) => ({
                key: t.key,
                label: (
                  <Space>
                    {t.icon}
                    <span style={{ fontWeight: 500 }}>{t.label}</span>
                  </Space>
                ),
                children: t.content,
              }))}
            />
          </Card>
        </div>
      </AnimatedSection>

      {/* CTA Footer */}
      <AnimatedSection delay={100}>
        <div
          style={{
            textAlign: 'center',
            padding: '64px 24px',
            background: '#0f172a',
            margin: '0 -24px -24px',
            borderRadius: '16px 16px 0 0',
          }}
        >
          <Title level={3} style={{ color: '#fff', marginBottom: 16 }}>
            准备开始使用？
          </Title>
          <Paragraph style={{ color: 'rgba(255,255,255,0.65)', fontSize: 16, marginBottom: 24 }}>
            从知识库管理开始，构建属于企业的私有化智能知识引擎。
          </Paragraph>
          <Button
            type="primary"
            size="large"
            icon={<MessageOutlined />}
            style={{ background: accentColor, borderColor: accentColor, borderRadius: 6 }}
            onClick={() => navigate('/knowledge-base')}
          >
            进入知识库
          </Button>
        </div>
      </AnimatedSection>
    </div>
  )
}

export default ProductPage
