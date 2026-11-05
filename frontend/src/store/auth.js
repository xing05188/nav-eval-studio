import { defineStore } from 'pinia'
import { api, TOKEN_KEY, USER_KEY } from '@/api'

function readUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: readUser(),
  }),

  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    displayName: (state) => state.user?.display_name || state.user?.username || '未登录',
    role: (state) => state.user?.role || 'viewer',
    isAdmin: (state) => state.user?.role === 'admin',
  },

  actions: {
    async login(form) {
      const data = await api.login(form)
      this.token = data.access_token
      this.user = data.user
      localStorage.setItem(TOKEN_KEY, data.access_token)
      localStorage.setItem(USER_KEY, JSON.stringify(data.user))
      return data.user
    },

    async fetchMe() {
      const user = await api.me()
      this.user = user
      localStorage.setItem(USER_KEY, JSON.stringify(user))
      return user
    },

    async logout() {
      try {
        if (this.token) await api.logout()
      } catch {
        // 注销失败不阻塞前端清理
      }
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    },
  },
})
