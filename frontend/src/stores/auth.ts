import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi } from '@/api'
import { TOKEN_KEY, USER_KEY } from '@/api/http'
import type { User } from '@/types'

function readUser(): User | null {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null') as User | null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref<User | null>(readUser())
  const isLoggedIn = computed(() => Boolean(token.value))
  const displayName = computed(() => user.value?.display_name || user.value?.username || '未登录')

  function persist(): void {
    if (token.value) localStorage.setItem(TOKEN_KEY, token.value)
    if (user.value) localStorage.setItem(USER_KEY, JSON.stringify(user.value))
  }

  async function login(username: string, password: string): Promise<User> {
    const result = await authApi.login(username, password)
    token.value = result.access_token
    user.value = result.user
    persist()
    return result.user
  }

  async function fetchMe(): Promise<void> {
    if (!token.value) return
    user.value = await authApi.me()
    persist()
  }

  function logout(): void {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  return { token, user, isLoggedIn, displayName, login, fetchMe, logout }
})
