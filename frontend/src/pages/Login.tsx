import { useState } from 'react'
import { Card, Form, Input, Button, message, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { SafetyOutlined, LoginOutlined } from '@ant-design/icons'
import api from '@/services/api'
import { useAuthStore } from '@/stores/authStore'
import { getErrorMessage } from '@/utils/error'
import { useTranslation } from '@/i18n'
import { colors, spacing, radius, shadows, typography } from '@/styles/theme'

const { Title, Paragraph } = Typography

interface LoginForm {
  username: string
  password: string
}

const Login = () => {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { setToken, setUser } = useAuthStore()
  const { t } = useTranslation()

  const handleLogin = async (values: LoginForm) => {
    setLoading(true)
    try {
      const res = await api.post('/v1/auth/login', new URLSearchParams({
        username: values.username,
        password: values.password,
      }), {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      })
      const { access_token, user } = res.data
      setToken(access_token)
      setUser(user)
      message.success(t('login.loginSuccess'))
      navigate('/knowledge-base')
    } catch (e: unknown) {
      message.error(getErrorMessage(e, t('login.loginFailed')))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%)',
        padding: spacing.lg,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: '-10%',
          right: '-10%',
          width: 600,
          height: 600,
          background: 'radial-gradient(circle, rgba(229,112,53,0.2) 0%, transparent 65%)',
          borderRadius: '50%',
          filter: 'blur(80px)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: '-15%',
          left: '-10%',
          width: 500,
          height: 500,
          background: 'radial-gradient(circle, rgba(59,130,246,0.15) 0%, transparent 65%)',
          borderRadius: '50%',
          filter: 'blur(80px)',
        }}
      />

      <Card
        style={{
          width: 420,
          maxWidth: '100%',
          borderRadius: radius.xl,
          border: 'none',
          boxShadow: shadows.xl,
          position: 'relative',
          zIndex: 1,
        }}
        bodyStyle={{ padding: spacing.xxl }}
      >
        <div style={{ textAlign: 'center', marginBottom: spacing.xl }}>
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: radius.lg,
              background: colors.brand,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto',
              marginBottom: spacing.lg,
              color: colors.accent,
              fontSize: 28,
            }}
          >
            <SafetyOutlined />
          </div>
          <Title level={3} style={{ margin: 0, marginBottom: spacing.sm, color: colors.textPrimary }}>
            {t('login.title')}
          </Title>
          <Paragraph style={{ color: colors.textMuted, margin: 0, fontSize: typography.sizes.sm }}>
            {t('login.subtitle')}
          </Paragraph>
        </div>

        <Form layout="vertical" onFinish={handleLogin} size="large">
          <Form.Item
            name="username"
            label={<span style={{ color: colors.textSecondary, fontWeight: typography.weights.medium }}>{t('login.username')}</span>}
            rules={[{ required: true, message: t('login.usernamePlaceholder') }]}
          >
            <Input placeholder={t('login.usernamePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="password"
            label={<span style={{ color: colors.textSecondary, fontWeight: typography.weights.medium }}>{t('login.password')}</span>}
            rules={[{ required: true, message: t('login.passwordPlaceholder') }]}
          >
            <Input.Password placeholder={t('login.passwordPlaceholder')} />
          </Form.Item>
          <Form.Item style={{ marginTop: spacing.lg, marginBottom: 0 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              icon={<LoginOutlined />}
              style={{
                background: colors.accent,
                borderColor: colors.accent,
                borderRadius: radius.md,
                height: 44,
                fontWeight: typography.weights.semibold,
              }}
            >
              {t('login.loginButton')}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}

export default Login
