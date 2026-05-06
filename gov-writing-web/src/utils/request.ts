import axios from 'axios'
import { getBspLoginUrl, getLoginStatus } from '@/api/auth'

/**
 * Legacy 鉴权头：
 * - 必填：X-Legacy-User-Id / X-Legacy-Account / X-Legacy-Name
 * - 可选：X-Legacy-Org-Name / X-Legacy-Org-Code
 *
 * 所有值仅来源于 getLoginStatus() 返回的 user 字段：
 *   - X-Legacy-User-Id  <- user.ID
 *   - X-Legacy-Account  <- user.ACCOUNT
 *   - X-Legacy-Name     <- user.NAME
 *   - X-Legacy-Org-Name <- user.ORG_NAME
 *   - X-Legacy-Org-Code <- user.ORG_CODE
 */
const LEGACY_HEADERS_CACHE_KEY = 'legacy_auth_headers'
let legacyHeadersCache: Record<string, string> | null = null
let legacyHeadersLoading: Promise<Record<string, string> | null> | null = null

/**
 * 浏览器 XHR 要求 header value 必须是 ISO-8859-1 可表示字符。
 * 对包含中文等非 Latin-1 的值进行 URL 编码，避免 setRequestHeader 抛错。
 */
function toSafeHeaderValue(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return ''
  for (let i = 0; i < trimmed.length; i++) {
    if (trimmed.charCodeAt(i) > 255) {
      return encodeURIComponent(trimmed)
    }
  }
  return trimmed
}

function readLegacyHeadersCache(): Record<string, string> | null {
  try {
    const raw = sessionStorage.getItem(LEGACY_HEADERS_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return null
    const cached = parsed as Record<string, string>
    // 兼容旧缓存：即便缓存是历史未编码值，也在读取时做一轮安全规范化。
    const normalized: Record<string, string> = {}
    for (const [k, v] of Object.entries(cached)) {
      normalized[k] = toSafeHeaderValue(String(v ?? ''))
    }
    return normalized
  } catch {
    return null
  }
}

function writeLegacyHeadersCache(headers: Record<string, string> | null) {
  try {
    if (!headers) {
      sessionStorage.removeItem(LEGACY_HEADERS_CACHE_KEY)
      return
    }
    sessionStorage.setItem(LEGACY_HEADERS_CACHE_KEY, JSON.stringify(headers))
  } catch {
    // ignore cache write failures
  }
}

function buildLegacyAuthHeadersFromUser(user: Record<string, unknown> | null): Record<string, string> | null {
  const pick = (key: string) => {
    if (!user) return ''
    const v = user[key]
    return v === undefined || v === null ? '' : String(v).trim()
  }

  const userId = pick('ID')
  const account = pick('ACCOUNT')
  const name = pick('NAME')
  const orgName = pick('ORG_NAME')
  const orgCode = pick('ORG_CODE')
  if (!userId || !account || !name) return null

  const headers: Record<string, string> = {
    'X-Legacy-User-Id': toSafeHeaderValue(userId),
    'X-Legacy-Account': toSafeHeaderValue(account),
    'X-Legacy-Name': toSafeHeaderValue(name),
  }
  if (orgName) headers['X-Legacy-Org-Name'] = toSafeHeaderValue(orgName)
  if (orgCode) headers['X-Legacy-Org-Code'] = toSafeHeaderValue(orgCode)
  return headers
}

async function ensureLegacyAuthHeaders(): Promise<Record<string, string> | null> {
  if (legacyHeadersCache) return legacyHeadersCache
  const fromSession = readLegacyHeadersCache()
  if (fromSession) {
    legacyHeadersCache = fromSession
    return fromSession
  }
  if (legacyHeadersLoading) return legacyHeadersLoading

  legacyHeadersLoading = (async () => {
    try {
      const resp = await getLoginStatus()
      const code = String(resp.data?.code ?? '')
      if (code !== '1') return null
      const user = (resp.data?.data?.user ?? null) as Record<string, unknown> | null
      const headers = buildLegacyAuthHeadersFromUser(user)
      if (!headers) return null
      legacyHeadersCache = headers
      writeLegacyHeadersCache(headers)
      return headers
    } catch {
      return null
    } finally {
      legacyHeadersLoading = null
    }
  })()

  return legacyHeadersLoading
}

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/agentloop',
  timeout: 30000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

request.interceptors.request.use(
  async (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    const legacy = await ensureLegacyAuthHeaders()
    if (legacy) {
      Object.assign(config.headers, legacy)
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

request.interceptors.response.use(
  (response) => {
    const { data } = response
    if (data.code === 0) {
      return data
    }
    return Promise.reject(new Error(data.message || '请求失败'))
  },
  async (error) => {
    const status = error.response?.status
    if (status === 401 || status === 403) {
      try {
        const resp = await getLoginStatus()
        const code = String(resp.data?.code ?? '')
        const user = (resp.data?.data?.user ?? null) as Record<string, unknown> | null
        const headers = code === '1' ? buildLegacyAuthHeadersFromUser(user) : null
        legacyHeadersCache = headers
        writeLegacyHeadersCache(headers)
        if (code !== '1') {
          window.open(getBspLoginUrl(), '_self')
        }
      } catch {
        window.open(getBspLoginUrl(), '_self')
      }
    }
    const message = error.response?.data?.message || error.message || '网络错误'
    return Promise.reject(new Error(message))
  },
)

export default request
