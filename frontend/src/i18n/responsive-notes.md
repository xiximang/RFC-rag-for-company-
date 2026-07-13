# 移动端适配建议

## 1. 导航栏折叠
- 在屏幕宽度 ≤ 768 px 时，将左侧固定 Sider 收起为抽屉（Drawer）或汉堡菜单。
- Ant Design 的 `Layout.Sider` 支持 `collapsed` / `collapsedWidth` / `breakpoint`，可监听 `onBreakpoint` 自动折叠。
- 顶部 Header 中的标题与用户信息应隐藏次要元素，仅保留 Logo、状态徽标和折叠按钮。

## 2. 表格横向滚动
- 所有数据表格外层包裹 `div` 并设置 `overflow-x: auto`。
- 为表格设置 `scroll={{ x: 'max-content' }}`（Ant Design Table），避免小屏下列被压缩重叠。
- 对非关键列在断点处隐藏，或改用卡片列表（Card List）展示。

## 3. 字体与间距缩放
- 使用相对单位：`rem` / `em` / `vw` 替代固定 `px`，便于随根字体缩放。
- 在 `html` 上设置基础字体大小，媒体查询中按屏幕宽度微调，例如：
  ```css
  @media (max-width: 576px) {
    html { font-size: 14px; }
  }
  ```
- 减少大屏间距（padding / margin）在移动端的表现，使用 `clamp()` 或断点变量。

## 4. 表单与按钮
- 表单输入框、按钮在移动端应占满宽度（`width: 100%`），并增大触控区域（最小 44×44 px）。
- 将表单标签改为占位符或垂直布局，避免水平空间不足。

## 5. 弹窗与抽屉
- 弹窗宽度使用 `max-width: 90vw`，避免超出视口。
- 详情面板优先使用底部滑出抽屉（Drawer placement="bottom"）替代右侧宽抽屉。

## 6. 响应式断点参考
| 断点 | 宽度 | 典型处理 |
|------|------|----------|
| xs   | < 576px | 单列布局、隐藏侧边栏、全宽按钮 |
| sm   | 576–768px | 简化导航、表格滚动 |
| md   | 768–992px | 侧边栏可折叠 |
| lg   | ≥ 992px | 完整桌面布局 |
