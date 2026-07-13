import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import landingCss from './landing-theme.css?inline'

function LandingPage() {
  useEffect(() => {
    const styleId = 'landing-theme-style'
    let styleEl = document.getElementById(styleId) as HTMLStyleElement | null
    if (!styleEl) {
      styleEl = document.createElement('style')
      styleEl.id = styleId
      styleEl.textContent = landingCss
      document.head.appendChild(styleEl)
    }

    const revealItems = [...document.querySelectorAll('.reveal')]
    const revealObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible')
            revealObserver.unobserve(entry.target)
          }
        })
      },
      { rootMargin: '18% 0px 8% 0px', threshold: 0.06 }
    )
    revealItems.forEach((item) => revealObserver.observe(item))

    const sections = [...document.querySelectorAll('.section')]
    let scrollTicking = false
    const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

    const updateScrollMotion = () => {
      const viewport = window.innerHeight || 1
      sections.forEach((section) => {
        const container = section.querySelector('.container') as HTMLElement | null
        if (!container) return
        const rect = section.getBoundingClientRect()
        const sectionCenter = rect.top + rect.height / 2
        const viewportCenter = viewport / 2
        const distance = (sectionCenter - viewportCenter) / viewport
        const abs = Math.abs(distance)
        const fade = clamp((abs - 0.34) / 0.86, 0, 1)
        const opacity = clamp(1 - fade * 0.42, 0.58, 1)
        const translate = clamp(distance * -28, -26, 26)
        const scale = clamp(1 - fade * 0.018, 0.982, 1)
        const blur = clamp(fade * 1.35, 0, 1.35)
        container.style.setProperty('--scroll-opacity', opacity.toFixed(3))
        container.style.setProperty('--scroll-y', `${translate.toFixed(1)}px`)
        container.style.setProperty('--scroll-scale', scale.toFixed(3))
        container.style.setProperty('--scroll-blur', `${blur.toFixed(2)}px`)
      })
      scrollTicking = false
    }

    const requestScrollMotion = () => {
      if (scrollTicking) return
      scrollTicking = true
      requestAnimationFrame(updateScrollMotion)
    }

    window.addEventListener('scroll', requestScrollMotion, { passive: true })
    window.addEventListener('resize', requestScrollMotion)
    updateScrollMotion()

    const navLinks = [...document.querySelectorAll('.nav-links a')]
    const dots = [...document.querySelectorAll('.dot')]
    const sectionObserver = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (!visible) return
        const target = visible.target as HTMLElement
        const id = target.id
        const isDark = target.dataset.theme === 'dark'
        document.body.classList.toggle('on-dark', isDark)
        navLinks.forEach((link) => {
          link.classList.toggle('active', link.getAttribute('href') === `#${id}`)
        })
        dots.forEach((dot) => {
          dot.classList.toggle('active', dot.getAttribute('href') === `#${id}`)
        })
      },
      { threshold: [0.34, 0.48, 0.62] }
    )
    sections.forEach((section) => sectionObserver.observe(section))

    return () => {
      styleEl?.remove()
      revealObserver.disconnect()
      window.removeEventListener('scroll', requestScrollMotion)
      window.removeEventListener('resize', requestScrollMotion)
      sectionObserver.disconnect()
      document.body.classList.remove('on-dark')
    }
  }, [])

  return (
    <div className="landing-page">
<nav className="nav" aria-label="主导航">
    <a className="brand" href="#cover" aria-label="Private Multimodal RAG">
      <span className="brand-mark">R</span>
      <span>Private Multimodal RAG</span>
    </a>
    <div className="nav-links">
      <a href="#capability">产品能力</a>
      <a href="#api-governance">API 管理</a>
      <a href="#security">权限安全</a>
      <a href="#field-output">字段产出</a>
      <a href="#results">成果展示</a>
      <a href="#landing">落地案例</a>
      <Link to="/login" className="landing-login">登录系统</Link>
    </div>
  </nav>

  <main>
    <section className="section" id="cover" data-theme="dark">
      <div className="cover-rails" aria-hidden="true">
        <span className="cover-rail"></span>
        <span className="cover-rail"></span>
        <span className="cover-rail"></span>
      </div>
      <div className="container cover-layout">
        <div className="reveal">
          <div className="cover-mark">R</div>
          <p className="eyebrow">企业级私有化多模态 RAG</p>
          <h1 className="cover-title">Private Multimodal RAG</h1>
          <p className="cover-subtitle">
            统一接入企业知识、业务 API 与权限体系，让 AI 在组织授权边界内完成检索、生成与审计。
          </p>
        </div>
      </div>
      <div className="cover-scroll">向下滚动进入产品展示</div>
    </section>

    <section className="section dark" id="overview" data-theme="dark">
      <div className="grid-backdrop" aria-hidden="true"></div>
      <div className="container hero-layout">
        <div className="reveal">
          <span className="eyebrow">企业级私有化知识智能平台</span>
          <h1><span>让企业知识接入 AI</span><span>让权限分级贯穿全流程</span><span>让多模态 RAG 安全落地</span></h1>
          <p className="lead">
            Private Multimodal RAG 面向企业内部知识库、业务系统与 API 体系，提供多模态接入、混合检索、安全生成和权限分级能力，让 AI 回答始终处在公司授权边界之内。
          </p>
          <div className="hero-actions" aria-label="核心特性">
            <span className="pill">多模态接入</span>
            <span className="pill">统一 API 管理</span>
            <span className="pill">权限分级控制</span>
            <span className="pill">全链路审计</span>
          </div>
        </div>
        <div className="image-shell reveal">
          <img
            src="/landing-assets/images/platform-overview.webp"
            alt="企业私有化多模态 RAG 平台示意图"
            loading="lazy"
            decoding="async"
            fetchPriority="high"
          />
          <div className="caption-strip">
            <div className="caption-card">
              <strong>多模态</strong>
              <span>文档、表格、图片、视频和链接统一接入</span>
            </div>
            <div className="caption-card">
              <strong>可控</strong>
              <span>按角色、字段、敏感等级进行访问裁剪</span>
            </div>
            <div className="caption-card">
              <strong>可落地</strong>
              <span>网关、监控、审计与部署体系完整闭环</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section className="section" id="capability" data-theme="light">
      <div className="container">
        <div className="section-heading reveal">
          <span className="section-kicker">产品能力</span>
          <h2>企业 AI 闭环</h2>
          <p className="lead">
            从 PDF、Word、Excel、PPT、图片、视频到业务系统数据，统一接入后进入混合检索和安全生成链路。这里重点展示系统如何把多模态知识变成可检索、可引用、可管控的企业能力。
          </p>
        </div>

        <div className="capability-grid">
          <article className="capability reveal">
            <div>
              <span className="cap-number">01</span>
              <h3>多模态接入</h3>
              <p>把企业分散在文档、表格、图片、视频和网页里的知识统一解析、切分、索引。</p>
            </div>
            <ul>
              <li>PDF、Word、Excel、PPT 统一处理</li>
              <li>图片 OCR、视频帧、链接内容可接入</li>
              <li>Chunk 继承文档、段落和字段权限</li>
            </ul>
          </article>

          <article className="capability reveal">
            <div>
              <span className="cap-number">02</span>
              <h3>混合检索</h3>
              <p>向量召回、关键词回退和 Re-rank 重排序组合，保证企业复杂问题能命中有效上下文。</p>
            </div>
            <ul>
              <li>Milvus 向量检索承载语义召回</li>
              <li>关键词降级保障精确字段命中</li>
              <li>检索、工具调用、生成策略可编排</li>
            </ul>
          </article>

          <article className="capability reveal">
            <div>
              <span className="cap-number">03</span>
              <h3>安全生成</h3>
              <p>生成前过滤权限，生成中压缩上下文，生成后复核敏感信息，避免模型越权输出。</p>
            </div>
            <ul>
              <li>提示词注入检测与前置拦截</li>
              <li>上下文压缩前执行权限裁剪</li>
              <li>答案输出二次校验与审计留痕</li>
            </ul>
          </article>

          <article className="capability featured reveal">
            <div>
              <span className="cap-number">04</span>
              <h3>权限分级</h3>
              <p>以用户组、角色、文档、字段、标签和敏感等级控制数据可见范围。</p>
            </div>
            <ul>
              <li>新员工、普通员工、管理层、老板权限不同</li>
              <li>不同身份对应不同数据访问范围</li>
              <li>L2 字段级内容实现精细化过滤</li>
            </ul>
          </article>
        </div>
      </div>
    </section>

    <section className="section white" id="api-governance" data-theme="light">
      <div className="container">
        <div className="section-heading reveal">
          <span className="section-kicker">统一化 API 管理</span>
          <h2>统一 API 管理</h2>
          <p className="lead">
            源项目通过 Kong 网关把前端、后端、知识库、检索、生成、权限和审计统一到一个入口。对企业来说，这意味着接入业务系统时可以统一鉴权、限流、路由、审计和接口权限，而不是每个系统单独管理。
          </p>
        </div>

        <div className="api-layout">
          <div className="api-console reveal">
            <div className="api-console-head">
              <strong>Kong Gateway</strong>
              <span>统一入口 / key-auth / rate-limiting</span>
            </div>
            <div className="route-list" aria-label="API 管理示例">
              <div className="route-row">
                <strong>POST</strong>
                <em>/api/v1/chat</em>
                <span>问答</span>
              </div>
              <div className="route-row">
                <strong>POST</strong>
                <em>/api/v1/ingest</em>
                <span>接入</span>
              </div>
              <div className="route-row">
                <strong>GET</strong>
                <em>/api/v1/permissions</em>
                <span>权限</span>
              </div>
              <div className="route-row">
                <strong>POST</strong>
                <em>/api/v1/audit</em>
                <span>审计</span>
              </div>
            </div>
          </div>

          <div className="api-policy-grid">
            <article className="api-policy-card reveal">
              <div>
                <strong>统一鉴权</strong>
                <p>所有应用先经过网关鉴权，API Key、JWT 和用户权限共同决定可调用范围。</p>
              </div>
              <span className="tag">key-auth</span>
            </article>
            <article className="api-policy-card highlight reveal">
              <div>
                <strong>接口级权限</strong>
                <p>不同角色开放不同接口，员工可问制度，经理可查部门数据，管理层可汇总经营视图。</p>
              </div>
              <span className="tag">RBAC / ABAC</span>
            </article>
            <article className="api-policy-card reveal">
              <div>
                <strong>限流与路由</strong>
                <p>统一处理调用频率、服务路由和异常隔离，避免模型与业务系统被无序调用。</p>
              </div>
              <span className="tag">rate-limiting</span>
            </article>
            <article className="api-policy-card reveal">
              <div>
                <strong>调用审计</strong>
                <p>记录谁在什么时候调用了哪个接口、拿到了哪些字段、触发了哪些拦截策略。</p>
              </div>
              <span className="tag">audit log</span>
            </article>
          </div>
        </div>
      </div>
    </section>

    <section className="section steel" id="security" data-theme="light">
      <div className="container">
        <div className="section-heading reveal">
          <span className="section-kicker">权限安全体系</span>
          <h2>L2 字段级控制</h2>
          <p className="lead">
            系统不只判断“能不能看这个文件”，而是在检索与生成链路中持续判断“能不能看这个段落、单元格、字段和敏感词”。这让企业可以把真实业务数据接入 AI，而不是只接入低风险公开资料。
          </p>
        </div>

        <div className="security-layout">
          <div className="l2-focus reveal">
            <span className="l2-badge">核心安全能力：L2 字段级内容</span>
            <h3>同一份资料，不同身份看到不同答案</h3>
            <p>
              Word 段落、Excel 单元格、表格列、结构化字段都会带上权限元数据。检索时先过滤未授权 chunk，生成时只使用被授权上下文，输出时再检查敏感泄露风险。
            </p>
            <div className="field-demo" aria-label="字段级权限示例">
              <div className="field-row">
                <span>合同金额</span>
                <span>已授权项目经理可见</span>
                <span className="allow">允许</span>
              </div>
              <div className="field-row">
                <span>员工薪资</span>
                <span className="mask"></span>
                <span className="deny">屏蔽</span>
              </div>
              <div className="field-row">
                <span>客户名单</span>
                <span className="mask"></span>
                <span className="deny">拦截</span>
              </div>
              <div className="field-row">
                <span>脱敏摘要</span>
                <span>外包人员仅可访问脱敏字段</span>
                <span className="allow">允许</span>
              </div>
            </div>
          </div>

          <div className="security-side">
            <div className="role-matrix reveal">
              <h3>角色权限分级</h3>
              <div className="role-grid">
                <div className="role">
                  <strong>新员工</strong>
                  <span>仅访问入职、制度公开信息和基础知识。</span>
                </div>
                <div className="role">
                  <strong>普通员工</strong>
                  <span>访问本部门业务资料，敏感字段默认脱敏。</span>
                </div>
                <div className="role">
                  <strong>管理层</strong>
                  <span>查看团队、项目、经营相关授权数据。</span>
                </div>
                <div className="role">
                  <strong>老板</strong>
                  <span>可访问核心经营和高敏信息，并保留审计。</span>
                </div>
              </div>
            </div>

            <div className="security-grid">
              <article className="security-card reveal">
                <h3>提示词前置拦截</h3>
                <p>Prompt 开头即进行风险检测，识别注入攻击、越权诱导和绕过策略。</p>
              </article>
              <article className="security-card reveal">
                <h3>文件字段拦截</h3>
                <p>对指定字段、列、段落和 chunk 进行权限过滤，防止敏感字段进入上下文。</p>
              </article>
              <article className="security-card reveal">
                <h3>敏感性拦截</h3>
                <p>按 L0-L4 敏感等级屏蔽内容，外包人员等低权限角色只访问脱敏数据。</p>
              </article>
              <article className="security-card reveal">
                <h3>API 级权限控制</h3>
                <p>API 调用鉴权、接口级授权、限流和调用链路审计，避免工具侧越权。</p>
              </article>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section className="section white" id="field-output" data-theme="light">
      <div className="container">
        <div className="section-heading reveal">
          <span className="section-kicker">权限控制落地</span>
          <h2>字段级产出</h2>
          <p className="lead">
            同一张客户经营表，系统在回答前按身份过滤字段。普通员工看到脱敏摘要，管理层看到部门数据，老板看到完整经营视图；敏感字段不会进入模型上下文。
          </p>
        </div>

        <div className="field-output-layout">
          <div className="access-board reveal">
            <h3>客户经营数据输出示例</h3>
            <div className="data-table" role="table" aria-label="字段级权限输出示例">
              <div className="data-row data-head" role="row">
                <div className="data-cell">字段</div>
                <div className="data-cell">普通员工</div>
                <div className="data-cell">部门经理</div>
                <div className="data-cell">老板</div>
                <div className="data-cell">处理策略</div>
              </div>
              <div className="data-row" role="row">
                <div className="data-cell">客户名称</div>
                <div className="data-cell"><span className="redacted"></span></div>
                <div className="data-cell">华东 A 客户</div>
                <div className="data-cell">华东 A 客户</div>
                <div className="data-cell">按部门过滤</div>
              </div>
              <div className="data-row" role="row">
                <div className="data-cell">合同金额</div>
                <div className="data-cell"><span className="redacted"></span></div>
                <div className="data-cell">480 万</div>
                <div className="data-cell">480 万</div>
                <div className="data-cell">L2 字段控制</div>
              </div>
              <div className="data-row" role="row">
                <div className="data-cell">逾期风险</div>
                <div className="data-cell">高风险</div>
                <div className="data-cell">高风险</div>
                <div className="data-cell">高风险</div>
                <div className="data-cell">允许摘要</div>
              </div>
              <div className="data-row" role="row">
                <div className="data-cell">负责人手机号</div>
                <div className="data-cell"><span className="redacted"></span></div>
                <div className="data-cell"><span className="redacted"></span></div>
                <div className="data-cell">138****6321</div>
                <div className="data-cell">高敏脱敏</div>
              </div>
              <div className="data-row" role="row">
                <div className="data-cell">老板审批备注</div>
                <div className="data-cell"><span className="redacted"></span></div>
                <div className="data-cell"><span className="redacted"></span></div>
                <div className="data-cell">建议暂停授信</div>
                <div className="data-cell">L4 可见</div>
              </div>
            </div>
          </div>

          <div className="access-summary">
            <article className="summary-card reveal">
              <strong>产品能力展示</strong>
              <p>演示时可以直接切换“员工 / 经理 / 老板”身份，现场看到字段如何被隐藏、脱敏或放行。</p>
            </article>
            <article className="summary-card highlight reveal">
              <strong>使用效果</strong>
              <p>业务人员不用理解权限模型，只会看到符合自己身份的答案；敏感字段不会进入模型上下文。</p>
            </article>
            <article className="summary-card reveal">
              <strong>可视化成果</strong>
              <p>每次输出都能展示：命中文档、被裁剪字段、敏感等级、API 调用记录和最终答案来源。</p>
            </article>
          </div>
        </div>
      </div>
    </section>

    <section className="section steel" id="results" data-theme="light">
      <div className="container">
        <div className="section-heading reveal">
          <span className="section-kicker">结果展示 / 产出可视化</span>
          <h2>上线效果看板</h2>
          <p className="lead">
            这里展示最终交付给公司管理者和信息化团队的结果：多模态资料接入了多少、权限拦截是否生效、API 调用是否可控、哪些部门真正用起来。
          </p>
        </div>

        <div className="dashboard-grid">
          <div className="dashboard-panel reveal">
            <h3>一周运行结果</h3>
            <div className="kpi-grid">
              <div className="kpi">
                <strong>3,482</strong>
                <span>企业知识问答次数</span>
              </div>
              <div className="kpi">
                <strong>527</strong>
                <span>L2 字段过滤次数</span>
              </div>
              <div className="kpi">
                <strong>216</strong>
                <span>敏感内容拦截次数</span>
              </div>
              <div className="kpi">
                <strong>1,204</strong>
                <span>授权 API 调用次数</span>
              </div>
            </div>
          </div>

          <div className="dashboard-panel reveal">
            <h3>部门使用效果</h3>
            <div className="department-board">
              <div className="department-row">
                <span>销售部</span>
                <div className="bar"><span style={{width: '86%'}}></span></div>
                <strong>86%</strong>
              </div>
              <div className="department-row">
                <span>财务部</span>
                <div className="bar"><span style={{width: '74%'}}></span></div>
                <strong>74%</strong>
              </div>
              <div className="department-row">
                <span>法务部</span>
                <div className="bar"><span style={{width: '69%'}}></span></div>
                <strong>69%</strong>
              </div>
              <div className="department-row">
                <span>IT 运维</span>
                <div className="bar"><span style={{width: '92%'}}></span></div>
                <strong>92%</strong>
              </div>
            </div>
            <div className="result-tags">
              <span className="tag">回答带引用</span>
              <span className="tag">权限裁剪可见</span>
              <span className="tag">审计链路完整</span>
              <span className="tag">管理层可汇总</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section className="section dark" id="landing" data-theme="dark">
      <div className="grid-backdrop" aria-hidden="true"></div>
      <div className="container">
        <div className="section-heading reveal">
          <span className="section-kicker">实际落地案例</span>
          <h2>岗位级 AI 助手</h2>
          <p className="lead">
            一个底座可以支撑多个公司内助手，但每个助手背后的知识范围、API 权限和字段可见范围都不同。员工用的是工作助手，老板看到的是经营驾驶舱。
          </p>
        </div>

        <div className="case-grid">
          <article className="case-card reveal">
            <div>
              <h3>新员工助手</h3>
              <p>回答入职流程、制度、办公系统、报销规范，只连接公开制度库和 HR 入职资料。</p>
              <ul>
                <li>看不到薪酬明细和组织敏感信息</li>
                <li>不能调用客户、合同、财务 API</li>
                <li>输出标准流程和入口链接</li>
              </ul>
            </div>
            <div className="case-stat">
              <strong>L1</strong>
              <span>公开与内部基础信息</span>
            </div>
          </article>

          <article className="case-card reveal">
            <div>
              <h3>部门经营助手</h3>
              <p>面向部门负责人，汇总本部门客户、合同、项目进度和风险事项，跨部门数据自动脱敏。</p>
              <ul>
                <li>可调用本部门 CRM 和项目系统</li>
                <li>合同金额、负责人字段按授权展示</li>
                <li>输出风险清单和处置建议</li>
              </ul>
            </div>
            <div className="case-stat">
              <strong>L3</strong>
              <span>部门级授权视图</span>
            </div>
          </article>

          <article className="case-card executive reveal">
            <div>
              <h3>老板经营驾驶舱</h3>
              <p>面向公司管理层，整合客户、财务、合同、项目、风险数据，输出完整经营判断。</p>
              <ul>
                <li>可查看完整金额、客户和审批备注</li>
                <li>可跨部门汇总经营风险</li>
                <li>所有查询、脱敏和 API 调用留痕</li>
              </ul>
            </div>
            <div className="case-stat">
              <strong>L4</strong>
              <span>全局经营权限</span>
            </div>
          </article>
        </div>

        <div className="ops-layout">
          <div className="ops-list reveal">
            <div className="ops-item">
              <strong>私有化与混合部署</strong>
              <span>支持内网、专有云、Docker Compose、Kubernetes 和蓝绿发布。</span>
            </div>
            <div className="ops-item">
              <strong>全链路可观测</strong>
              <span>Prometheus、Grafana 与告警体系覆盖检索、模型调用、网关和服务健康。</span>
            </div>
            <div className="ops-item">
              <strong>安全审计闭环</strong>
              <span>记录检索过滤、脱敏、API 调用、模型响应和最终输出，满足企业追溯要求。</span>
            </div>
          </div>
          <div className="access-board reveal">
            <h3 style={{color: '#111318'}}>每次回答都留下可审计证据</h3>
            <div className="data-table" role="table" aria-label="审计记录示例">
              <div className="data-row data-head" role="row">
                <div className="data-cell">时间</div>
                <div className="data-cell">角色</div>
                <div className="data-cell">动作</div>
                <div className="data-cell">结果</div>
                <div className="data-cell">策略</div>
              </div>
              <div className="data-row" role="row">
                <div className="data-cell">09:31</div>
                <div className="data-cell">普通员工</div>
                <div className="data-cell">查询合同金额</div>
                <div className="data-cell">已拦截</div>
                <div className="data-cell">L2 字段限制</div>
              </div>
              <div className="data-row" role="row">
                <div className="data-cell">10:12</div>
                <div className="data-cell">部门经理</div>
                <div className="data-cell">查询客户风险</div>
                <div className="data-cell">部门内放行</div>
                <div className="data-cell">L3 部门权限</div>
              </div>
              <div className="data-row" role="row">
                <div className="data-cell">11:08</div>
                <div className="data-cell">老板</div>
                <div className="data-cell">汇总经营风险</div>
                <div className="data-cell">完整输出</div>
                <div className="data-cell">L4 全局权限</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section className="section" id="finale" data-theme="dark">
      <div className="container finale-layout">
        <div className="finale-visual reveal">
          <video
            autoPlay
            muted
            loop
            playsInline
            preload="metadata"
            aria-label="Private Multimodal RAG 标识动画"
          >
            <source
              src="/landing-assets/videos/neolink-logo-loop.webm"
              type="video/webm"
            />
            <source
              src="/landing-assets/videos/neolink-logo-loop.mp4"
              type="video/mp4"
            />
          </video>
        </div>
        <div className="finale-copy reveal">
          <h2>每一次使用都在沉淀，企业知识持续进化</h2>
          <p>
            多模态资料接入、统一 API 管理、权限分级控制与全链路审计共同沉淀为企业 AI 基础设施。系统越用越清楚组织边界，知识资产持续产生业务价值。
          </p>
        </div>
        <div className="finale-bottom reveal">
          <div className="footer-links">
            <div>
              <strong>产品</strong>
              <span>多模态接入</span><br />
              <span>统一 API 管理</span><br />
              <span>权限分级控制</span>
            </div>
            <div>
              <strong>安全</strong>
              <span>L2 字段级</span><br />
              <span>敏感拦截</span><br />
              <span>审计留痕</span>
            </div>
            <div>
              <strong>落地</strong>
              <span>私有化部署</span><br />
              <span>可观测运维</span><br />
              <span>企业级扩展</span>
            </div>
          </div>
          <Link to="/login" className="finale-cta">开始使用</Link>
        </div>
      </div>
    </section>
  </main>

  <div className="progress" aria-hidden="true">
    <a className="dot" href="#cover"></a>
    <a className="dot" href="#overview"></a>
    <a className="dot" href="#capability"></a>
    <a className="dot" href="#api-governance"></a>
    <a className="dot" href="#security"></a>
    <a className="dot" href="#field-output"></a>
    <a className="dot" href="#results"></a>
    <a className="dot" href="#landing"></a>
    <a className="dot" href="#finale"></a>
  </div>

  
    </div>
  )
}

export default LandingPage
