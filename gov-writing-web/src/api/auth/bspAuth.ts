import axios from 'axios'

export type BspLoginStatusResponse = {
  code: number | string
  data?: {
    user?: Record<string, any>
  }
  msg?: string
  message?: string
}

function getAppCode() {
  const fromEnv = (import.meta as any).env?.VITE_BSP_APP_CODE as string | undefined
  const fromGlobal = (globalThis as any).app_code as string | undefined
  return (fromEnv || fromGlobal || 'AI-POLICE').trim()
}

export function getBspLoginUrl() {
  const appCode = getAppCode()
  return `/ucenter/?app_code=${encodeURIComponent(appCode)}`
}

export function getBspLogoutUrl() {
  const appCode = getAppCode()
  return `/ucenter/logout?app_code=${encodeURIComponent(appCode)}`
}

export async function getLoginStatus() {
  return axios.get<BspLoginStatusResponse>('/bsp/restapi/user/getLoginStatus')
}

