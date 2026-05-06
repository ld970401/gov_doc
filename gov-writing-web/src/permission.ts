import router from '@/router'
import { getBspLoginUrl, getLoginStatus } from '@/api/auth'

const USER_KEY = 'user'

function hasCachedUser() {
  return !!sessionStorage.getItem(USER_KEY)
}

function cacheUser(user: any) {
  sessionStorage.setItem(USER_KEY, JSON.stringify(user ?? {}))
}

router.beforeEach(async (to, _from, next) => {
  // 允许通过 route meta 显式跳过鉴权
  if ((to.meta as any)?.public === true) {
    next()
    return
  }

  if (hasCachedUser()) {
    next()
    return
  }

  try {
    const resp = await getLoginStatus()
    const code = String(resp.data?.code ?? '')
    if (code === '1') {
      cacheUser(resp.data?.data?.user)
      next()
      return
    }
  } catch {
    // ignore and redirect below
  }

  window.open(getBspLoginUrl(), '_self')
})

