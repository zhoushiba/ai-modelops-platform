/**
 * axios 统一封装：
 * 1. 请求拦截器统一注入 JWT；
 * 2. 响应拦截器拆掉统一信封（`{code,message,data,trace_id}`），业务失败统一 toast；
 * 3. 401 自动清理登录态并跳回登录页；
 * 4. 把后端业务码 / HTTP 状态 / trace_id 打包成 ApiError，便于页面做错误态。
 */
import axios, { type AxiosError, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

export const TOKEN_KEY = 'mops_token'
export const USER_KEY = 'mops_user'

export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
  trace_id: string
}

export class ApiError extends Error {
  code?: number
  status?: number
  traceId?: string

  constructor(message: string, options: { code?: number; status?: number; traceId?: string } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = options.code
    this.status = options.status
    this.traceId = options.traceId
  }
}

function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

function redirectToLogin(): void {
  clearSession()
  if (!window.location.hash.startsWith('#/login')) {
    const current = window.location.hash.replace(/^#/, '') || '/dashboard'
    window.location.hash = `#/login?redirect=${encodeURIComponent(current)}`
  }
}

const http = axios.create({ baseURL: '/api', timeout: 120_000 })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  return config
})

http.interceptors.response.use(
  (response) => {
    const payload = response.data as ApiEnvelope<unknown>
    if (payload && typeof payload === 'object' && 'code' in payload) {
      if (payload.code !== 0) {
        ElMessage.error(payload.message || '请求失败')
        return Promise.reject(
          new ApiError(payload.message || '请求失败', {
            code: payload.code,
            status: response.status,
            traceId: payload.trace_id,
          }),
        )
      }
      // 统一信封：调用方直接拿 data
      return payload.data as never
    }
    return response.data as never
  },
  (error: AxiosError<ApiEnvelope<unknown> & { error?: { message?: string } }>) => {
    const status = error.response?.status
    const body = error.response?.data
    const message =
      body?.message || body?.error?.message || (status ? `请求失败（HTTP ${status}）` : error.message) || '网络异常'
    if (status === 401) {
      ElMessage.warning('登录状态已失效，请重新登录')
      redirectToLogin()
    } else {
      ElMessage.error(message)
    }
    return Promise.reject(
      new ApiError(message, { code: body?.code, status, traceId: body?.trace_id }),
    )
  },
)

export function get<T>(url: string, params?: Record<string, unknown>, config?: AxiosRequestConfig): Promise<T> {
  return http.get(url, { params, ...config }) as unknown as Promise<T>
}

export function post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return http.post(url, data, config) as unknown as Promise<T>
}

export function put<T>(url: string, data?: unknown): Promise<T> {
  return http.put(url, data) as unknown as Promise<T>
}

export function patch<T>(url: string, data?: unknown): Promise<T> {
  return http.patch(url, data) as unknown as Promise<T>
}

export function del<T>(url: string): Promise<T> {
  return http.delete(url) as unknown as Promise<T>
}

/** 下载 CSV 等二进制/文本附件（保留统一鉴权与错误提示）。 */
export async function download(url: string, filename: string): Promise<void> {
  const response = await http.get(url, { responseType: 'blob' })
  const blob = response as unknown as Blob
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = filename
  link.click()
  URL.revokeObjectURL(link.href)
}

export default http
