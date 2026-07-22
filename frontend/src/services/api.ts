import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { message } from 'antd'
import { useAuthStore } from '@/stores/authStore'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = useAuthStore.getState().token
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // Normalize URLs: remove trailing slashes to avoid FastAPI 307 redirects
    if (config.url && config.url.length > 1 && config.url.endsWith('/')) {
      config.url = config.url.replace(/\/+$/, '')
    }
    return config
  },
  (error) => Promise.reject(error)
)

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: string; message?: string }>) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail || error.response?.data?.message || error.message || '请求失败'

    if (status === 401) {
      message.error('登录已过期，请重新登录')
      useAuthStore.getState().logout()
      window.location.href = '/login'
    } else {
      message.error(detail)
    }
    return Promise.reject(error)
  }
)

export async function submitCandidateFeedback(
  messageId: string,
  payload: {
    ranking: number[]
    chosen_rank: number
    ratings: Record<number, number>
    comment?: string
    action?: string
  }
) {
  const res = await api.post(`/v1/chat/messages/${messageId}/candidate-feedback`, payload)
  return res.data
}

export default api
