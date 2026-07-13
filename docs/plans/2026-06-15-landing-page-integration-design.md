# 营销首页与现有前端融合设计

## 1. 决策结论

- **首页定位**：未登录官网页（Landing Page）。
- **访问路径**：未登录用户访问根路径 `/` 看到长滚动营销首页；点击「登录」进入 `/login`；登录后跳转至 `/knowledge-base`（应用工作台）。
- **已登录用户**：访问 `/` 自动重定向到 `/knowledge-base`，不再看到营销页（避免已登录用户被营销页打断工作流）。
- **视觉策略**：营销页保持独立深色科技风格，应用内继续沿用现有 `theme.ts` 的 B 端设计令牌，两者通过品牌 Logo、主按钮色和字体实现「品牌一致、场景分离」。

## 2. 现有系统上下文

| 项目 | 现状 |
|------|------|
| 技术栈 | React 18 + Vite + TypeScript + react-router-dom v6 + antd |
| 设计令牌 | `frontend/src/styles/theme.ts`：brand `#0f172a`、accent `#e57035`、background `#f8fafc` |
| 路由入口 | `frontend/src/router.tsx`，`App.tsx` 根据 `isAuthenticated` 决定是否包 `AppLayout` |
| 登录页 | `frontend/src/pages/Login.tsx`，登录成功后 `navigate('/')` |
| 左侧菜单 | `frontend/src/layout/AppLayout.tsx`，当前首页 `/` 对应「知识库」 |
| 新首页 | 单文件 HTML `/tmp/new_homepage/网页1.0.0.html`，约 1700 行内联 CSS + 原生 JS，引用 9 张 PNG + 2 个 MP4，总计约 12 MB |

## 3. 视觉设计体系融合

### 3.1 设计原则

- **场景分离**：营销页负责「吸引与说明」，应用内负责「效率与操作」。两套视觉体系不必完全相同，但要在 Logo、按钮主色、字体上形成品牌记忆。
- **不强行统一颜色**：营销页深色科技风（`#070b12` → `#101722`）与现有 B 端浅色后台反差明显，这是可接受的；统一色反而削弱营销页冲击力。
- **组件可复用底层**：容器、网格、卡片等布局结构可复用，但视觉皮肤保留营销页自己的 CSS 变量。

### 3.2 颜色映射

| 用途 | 现有 B 端主题 | 营销页建议值 | 说明 |
|------|--------------|-------------|------|
| 品牌深色 | `#0f172a` | `#070b12` / `#101722` | 营销页背景更深，突出科技感 |
| 强调色 | `#e57035`（暖橙） | 保留 `#e57035` 用于 CTA 主按钮 | 让「登录/立即体验」按钮在两个场景看起来是同一家产品 |
| 科技蓝 | `#3b82f6` | `#1769e0` / `#19a7ce` | 营销页信息色，与现有蓝色系不冲突 |
| 背景浅色 | `#f8fafc` | `#f7f8fb` / `#fbfdff` | 几乎一致，可直接沿用 |
| 成功/警告/错误 | 现有状态色 | 营销页保持语义一致 | 使用现有 status tokens |

### 3.3 字体策略

- 营销页目前使用 `Inter` + 系统中文回退。
- **推荐**：保留 Inter 作为营销页英文/数字展示字体，中文使用 `"PingFang SC", "Microsoft YaHei"`；与应用页共享同一套中文回退，避免切换页面时字体抖动。
- 不使用过于艺术的字体，保持企业级可信感。

### 3.4 圆角 / 阴影

- 营销页卡片圆角 `16px`、按钮/标签 `999px`、小元素 `8px`。
- 应用页圆角 `radius.md=8 / lg=12 / xl=16`。
- **做法**：营销页独立 CSS 变量，但在按钮主 CTA 上统一到 `radius.full`，视觉连贯。

## 4. 路由与鉴权流

### 4.1 推荐路由结构

```tsx
<Routes>
  {/* 公共路由 */}
  <Route path="/" element={<HomeGate />} />
  <Route path="/login" element={<Login />} />

  {/* 需要登录的路由 */}
  <Route element={<RequireAuth />}>
    <Route path="/knowledge-base" element={<KnowledgeBase />} />
    <Route path="/product" element={<ProductPage />} />
    <Route path="/upload-center" element={<UploadCenter />} />
    <Route path="/search-console" element={<SearchConsole />} />
    <Route path="/eval-workbench" element={<EvalWorkbench />} />
    <Route path="/permission-mgr" element={<PermissionMgr />} />
    <Route path="/system-admin" element={<SystemAdmin />} />
  </Route>

  <Route path="*" element={<NotFound />} />
</Routes>
```

### 4.2 HomeGate 组件

```tsx
function HomeGate() {
  const { isAuthenticated } = useAuthStore()
  return isAuthenticated ? <Navigate to="/knowledge-base" replace /> : <LandingPage />
}
```

### 4.3 影响点

- `Login.tsx` 登录成功后 `navigate('/')` 需改为 `navigate('/knowledge-base')`。
- `AppLayout.tsx` 菜单默认选中项 `/` 需改为 `/knowledge-base`。
- `AppLayout` Logo 点击可返回 `/knowledge-base`。
- 任何 `navigate('/')` 的内部调用都需检查并改为 `/knowledge-base`。

## 5. 组件拆分

新建目录 `frontend/src/landing/`，营销页按「区块」拆分为独立组件：

```
frontend/src/landing/
├── LandingPage.tsx              # 页面骨架：Nav + 各 Section + Footer + 动画 hooks
├── landing-theme.css            # 营销页专属 CSS 变量与工具类
├── components/
│   ├── LandingNav.tsx           # 顶部固定导航 + 移动端抽屉
│   ├── HeroSection.tsx          # 封面（cover-mark、标题、副标题、CTA）
│   ├── OverviewSection.tsx      # 企业级私有化知识智能平台
│   ├── CapabilitySection.tsx    # 企业 AI 闭环 4 个能力卡片
│   ├── ApiGovernanceSection.tsx # 统一 API 管理
│   ├── SecuritySection.tsx      # L2 字段级控制
│   ├── FieldOutputSection.tsx   # 字段级产出表格
│   ├── ResultsSection.tsx       # 上线效果看板
│   ├── CasesSection.tsx         # 岗位级 AI 助手
│   └── FinaleSection.tsx        # 结尾视频 + Footer + CTA
└── hooks/
    ├── useReveal.ts             # IntersectionObserver reveal
    └── useScrollMotion.ts       # requestAnimationFrame 滚动视差/模糊
```

### 拆分理由

- 每个 Section 独立，便于后续 A/B 测试、内容替换和懒加载。
- CSS 按组件通过 `landing-theme.css` 统一变量管理，避免内联 1700 行 CSS。
- 动画逻辑抽到 hooks，避免在 JSX 中直接操作 DOM。

## 6. 静态资源安放与优化

### 6.1 目录规划

```
frontend/public/landing-assets/
├── images/
│   ├── platform-overview.webp
│   ├── deployment-observability.webp
│   ├── permission-security.webp
│   ├── result-dashboard.webp
│   ├── system-architecture.webp
│   ├── rag-retrieval-flow.webp
│   ├── permission-levels.webp
│   ├── ui-model-config.webp
│   └── ui-search.webp
└── videos/
    ├── neolink-logo-loop.mp4
    └── neolink-logo-loop.webm
```

### 6.2 处理步骤

1. **重命名**：原路径含空格「网页 1.0.0/...」，改为无空格 kebab-case。
2. **格式转换**：PNG 转为 WebP（可减少 60% 以上体积）；MP4 保留并增加 WebM 备用。
3. **压缩**：
   - 图片：使用 `oxipng` / `cwebp` 压缩。
   - 视频：使用 `ffmpeg` 降低码率，目标 `neolink-logo-loop` < 500 KB。
4. **懒加载**：所有非首屏图片使用 `loading="lazy" decoding="async"`；首屏 `platform-overview.png` 使用 `fetchpriority="high"` 并预加载。
5. **视频策略**：
   - 封面循环视频 `autoplay muted loop playsinline`。
   - 大视频 `neolink-video-...mp4`（2.9 MB）仅作为可选展示，默认不自动播放，提供播放按钮或降级为 poster 图片。

### 6.3 性能预算

| 指标 | 目标 |
|------|------|
| 首页总资源 | < 3 MB（优化后） |
| LCP | < 2.5s |
| FID/INP | 良好 |
| 首屏阻塞资源 | 仅 CSS + 首图 + 字体 |

## 7. 动画迁移方案

### 7.1 Reveal 动画

原实现：原生 `IntersectionObserver` 给 `.reveal` 元素加 `.is-visible`。

迁移：

```ts
// hooks/useReveal.ts
export function useReveal<T extends HTMLElement>(options?: IntersectionObserverInit) {
  const ref = useRef<T>(null)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible')
          observer.unobserve(entry.target)
        }
      })
    }, { threshold: 0.06, rootMargin: '18% 0px 8% 0px', ...options })
    observer.observe(node)
    return () => observer.disconnect()
  }, [options])
  return ref
}
```

组件使用：

```tsx
const revealRef = useReveal<HTMLDivElement>()
return <div ref={revealRef} className="reveal">...</div>
```

### 7.2 滚动视差/模糊

原实现：`requestAnimationFrame` 中直接修改每个 `.container` 的 style。

迁移：

```ts
// hooks/useScrollMotion.ts
export function useScrollMotion() {
  useEffect(() => {
    let ticking = false
    const update = () => {
      // 通过 refs 或 CSS 变量更新，避免 React re-render
      ticking = false
    }
    const onScroll = () => {
      if (ticking) return
      ticking = true
      requestAnimationFrame(update)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
}
```

注意：

- 在 React StrictMode 下确保事件监听清理正确。
- 如果性能不佳，可降级为纯 CSS `scroll-driven animations`（现代浏览器支持）。

## 8. 导航与用户体验

### 8.1 顶部导航

左侧：
- Logo + 产品名「Private Multimodal RAG」

中间（桌面端）：
- 产品能力、API 管理、权限安全、字段产出、成果展示、落地案例（锚点链接）

右侧：
- 「登录系统」按钮（accent 色）
- 可选「GitHub / 文档」外链

移动端：
- 汉堡菜单，点击后左侧滑出抽屉，包含锚点和登录按钮。

### 8.2 CTA 设计

| 位置 | 文案 | 行为 |
|------|------|------|
| 封面主按钮 | 立即体验 | 跳转到 `/login` |
| 封面次按钮 | 查看能力 | 平滑滚动到 `#capability` |
| 结尾大按钮 | 开始使用 / 进入系统 | 跳转到 `/login` |
| 导航常驻 | 登录 | 跳转到 `/login` |

### 8.3 已登录用户行为

- 已登录用户直接访问 `/` 重定向到 `/knowledge-base`。
- 在应用内左侧菜单增加「产品官网」外链，方便已登录用户查看介绍页（或保留 `/landing` 独立路径作为可选入口）。

## 9. 实现步骤（推荐顺序）

1. **准备资源**
   - 复制 `/tmp/new_homepage/网页 1.0.0/` 到 `frontend/public/landing-assets/`
   - 重命名并压缩图片/视频，生成 WebP/WebM
   - 更新所有资源引用路径

2. **创建营销页骨架**
   - 新建 `frontend/src/landing/LandingPage.tsx`
   - 新建 `frontend/src/landing/landing-theme.css`（抽取 HTML 中的 CSS 变量与关键样式）
   - 新建 `frontend/src/landing/hooks/useReveal.ts` 和 `useScrollMotion.ts`

3. **拆分 Section 组件**
   - 按上文目录逐个迁移 HTML 区块
   - 将原生 className 替换为 React 组件 + CSS Modules 或 scoped CSS

4. **路由改造**
   - 修改 `frontend/src/router.tsx`：新增 `/` 的 `HomeGate`，将原 `/` 改为 `/knowledge-base`
   - 修改 `Login.tsx` 登录成功后 `navigate('/knowledge-base')`
   - 修改 `AppLayout.tsx` 默认菜单选中 `/knowledge-base`

5. **导航与 CTA**
   - 实现 `LandingNav.tsx`（桌面锚点 + 移动端抽屉 + 登录按钮）
   - 在 Hero 和 Finale 添加 CTA

6. **动画与交互**
   - 接入 `useReveal` 和 `useScrollMotion`
   - 验证滚动性能，必要时降级为纯 CSS

7. **响应式与无障碍**
   - 使用 clamp/media query 适配移动端
   - 为视频添加 `aria-label`，为锚点导航添加 `aria-current`

8. **构建验证**
   - `pnpm build` 通过
   - 检查资源路径、Tree Shaking、CSS 体积

9. **测试**
   - 未登录访问 `/` 显示 LandingPage
   - 点击登录跳转 `/login`
   - 登录后跳转 `/knowledge-base`
   - 已登录访问 `/` 自动重定向
   - 移动端导航正常

## 10. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 营销页 CSS 与 antd 全局样式冲突 | 中 | 营销页 CSS 使用更具体的选择器前缀（如 `.landing-page`），避免覆盖 antd |
| 资源体积过大导致首屏慢 | 高 | 图片转 WebP、视频压缩、懒加载、首图预加载 |
| 原生滚动动画在 React 下性能差 | 中 | 使用 refs + rAF，避免 setState；低端设备降级为纯 CSS |
| 路由改造影响现有跳转 | 中 | 全局搜索 `navigate('/')` 和 `<Navigate to="/"` 并更新 |
| 深色营销页与浅色登录页过渡突兀 | 低 | 登录页保持深色背景，CTA 按钮统一 accent 色，形成视觉桥梁 |

## 11. 验收标准

- [ ] 未登录用户访问 `http://localhost:5173/` 看到完整营销首页，无左侧菜单。
- [ ] 点击「登录」进入现有登录页，登录成功后跳转到知识库工作台。
- [ ] 已登录用户访问 `/` 自动重定向到 `/knowledge-base`。
- [ ] 营销页所有锚点平滑滚动，移动端导航可折叠。
- [ ] 首屏加载时间 < 2.5s（本地 build + preview）。
- [ ] 图片/视频资源路径正确，构建后无 404。
- [ ] 现有应用内页面不受营销页样式影响。
