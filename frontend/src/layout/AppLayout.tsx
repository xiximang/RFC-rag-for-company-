import type React from 'react'
import { useEffect, useMemo, useState } from 'react'
import { Layout, Menu, Avatar, Space, Button, Badge, Drawer } from 'antd'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  DatabaseOutlined,
  UploadOutlined,
  SearchOutlined,
  LineChartOutlined,
  SafetyOutlined,
  SettingOutlined,
  ProfileOutlined,
  KeyOutlined,
  GlobalOutlined,
  DashboardOutlined,
  LogoutOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '@/stores/authStore'
import { useTranslation, type Language } from '@/i18n'
import { colors, spacing, radius, shadows, typography, breakpoints } from '@/styles/theme'
import api from '@/services/api'

const { Sider, Content } = Layout

interface AppLayoutProps {
  children: React.ReactNode
}

const MENU_KEY_CONFIG = [
  { key: '/knowledge-base', icon: <DatabaseOutlined />, labelKey: 'nav.knowledgeBase' },
  { key: '/upload-center', icon: <UploadOutlined />, labelKey: 'nav.uploadCenter' },
  { key: '/search-console', icon: <SearchOutlined />, labelKey: 'nav.search' },
  { key: '/eval-workbench', icon: <LineChartOutlined />, labelKey: 'nav.evalWorkbench' },
  { key: '/permission-mgr', icon: <SafetyOutlined />, labelKey: 'nav.permission', adminOnly: true },
  { key: '/api-keys', icon: <KeyOutlined />, labelKey: 'nav.apiKeys' },
  { key: '/operations', icon: <DashboardOutlined />, labelKey: 'nav.operations', adminOnly: true },
  { key: '/system-admin', icon: <SettingOutlined />, labelKey: 'nav.systemConfig', adminOnly: true },
  { key: '/product', icon: <ProfileOutlined />, labelKey: 'nav.product' },
]

const AppLayout: React.FC<AppLayoutProps> = ({ children }) => {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const { t, i18n } = useTranslation()
  const { language, changeLanguage } = i18n

  const isAdmin = user ? user.role === 'admin' || user.security_level === 'L4' : false

  const menuItems = useMemo(
    () =>
      MENU_KEY_CONFIG
        .filter((item) => !item.adminOnly || isAdmin)
        .map((item) => ({
          key: item.key,
          icon: item.icon,
          label: t(item.labelKey),
        })),
    [isAdmin, t]
  )

  const [systemStatus, setSystemStatus] = useState<'success' | 'warning' | 'error'>('success')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < breakpoints.md)
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [])

  const toggleLanguage = () => {
    const next: Language = language === 'zh' ? 'en' : 'zh'
    changeLanguage(next)
  }

  const renderSiderContent = () => (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Logo */}
      <div
        style={{
          height: 48,
          display: 'flex',
          alignItems: 'center',
          padding: `0 ${spacing.md}px`,
          borderBottom: `1px solid ${colors.borderLight}`,
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: radius.sm,
            background: colors.brand,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: colors.accent,
            fontWeight: typography.weights.bold,
            fontSize: typography.sizes.md,
            marginRight: spacing.sm,
          }}
        >
          R
        </div>
        <div>
          <div style={{ fontWeight: typography.weights.semibold, fontSize: typography.sizes.sm, color: colors.textPrimary }}>
            {t('nav.brand')}
          </div>
          <div style={{ fontSize: 11, color: colors.textMuted, lineHeight: 1.3 }}>{t('nav.brandSub')}</div>
        </div>
      </div>

      {/* Menu */}
      <Menu
        mode="inline"
        selectedKeys={[location.pathname]}
        items={menuItems}
        onClick={({ key }) => {
          navigate(key)
          setMobileMenuOpen(false)
        }}
        style={{
          borderRight: 'none',
          paddingTop: spacing.xs,
          flex: 1,
          overflowY: 'auto',
        }}
        theme="light"
      />

      {/* Bottom: User + Controls */}
      <div
        style={{
          borderTop: `1px solid ${colors.borderLight}`,
          padding: `${spacing.sm}px ${spacing.md}px`,
          flexShrink: 0,
        }}
      >
        {/* User row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.xs }}>
          <Space size={6}>
            <Avatar
              size={24}
              style={{
                backgroundColor: colors.accentLight,
                color: colors.accent,
                fontWeight: typography.weights.semibold,
                fontSize: 12,
              }}
            >
              {(user?.username || 'A')[0].toUpperCase()}
            </Avatar>
            <span style={{
              fontSize: typography.sizes.sm,
              color: colors.textSecondary,
              maxWidth: 100,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {user?.username || 'Admin'}
            </span>
          </Space>
          <Button
            type="text"
            size="small"
            icon={<LogoutOutlined style={{ fontSize: 12 }} />}
            style={{ color: colors.textMuted, width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            onClick={() => {
              logout()
              navigate('/login')
            }}
          />
        </div>
        {/* Controls row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Button
            type="text"
            size="small"
            icon={<GlobalOutlined style={{ fontSize: 12 }} />}
            onClick={toggleLanguage}
            style={{ color: colors.textMuted, fontSize: 11, padding: '0 4px', height: 22 }}
          >
            {t(`common.language.${language}`)}
          </Button>
          <Badge
            status={systemStatus}
            text={
              <span style={{ fontSize: 11, color: colors.textMuted }}>
                {systemStatus === 'success'
                  ? t('nav.running')
                  : systemStatus === 'warning'
                    ? t('nav.degraded')
                    : t('nav.error')}
              </span>
            }
            style={{ fontSize: 11 }}
          />
        </div>
      </div>
    </div>
  )

  useEffect(() => {
    let mounted = true
    const checkHealth = async () => {
      if (document.hidden) return
      try {
        const res = await api.get('/v1/health')
        if (!mounted) return
        setSystemStatus(res.data.status === 'ok' ? 'success' : 'warning')
      } catch {
        if (!mounted) return
        setSystemStatus('error')
      }
    }

    checkHealth()
    const interval = setInterval(checkHealth, 30000)
    const handleVisibility = () => {
      if (!document.hidden) checkHealth()
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      mounted = false
      clearInterval(interval)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])

  return (
    <Layout style={{ height: '100vh', overflowX: 'hidden', overflow: 'hidden', background: colors.background }}>
      {isMobile ? (
        <Drawer
          placement="left"
          open={mobileMenuOpen}
          onClose={() => setMobileMenuOpen(false)}
          width={230}
          closable={false}
          bodyStyle={{ padding: 0 }}
        >
          {renderSiderContent()}
        </Drawer>
      ) : (
        <Sider
          theme="light"
          width={190}
          style={{
            background: colors.surface,
            borderRight: `1px solid ${colors.border}`,
            boxShadow: shadows.sm,
            zIndex: 10,
            overflowX: 'hidden',
          }}
        >
          {renderSiderContent()}
        </Sider>
      )}
      <Layout style={{ overflow: 'hidden' }}>
        <Content
          style={{
            margin: spacing.lg,
            padding: spacing.lg,
            background: colors.surface,
            borderRadius: radius.lg,
            minHeight: 280,
            border: `1px solid ${colors.border}`,
            boxShadow: shadows.sm,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {children}
        </Content>
      </Layout>
    </Layout>
  )
}

export default AppLayout
