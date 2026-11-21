import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import { pinia } from './stores'
import { useAuthStore } from './stores/auth'
import './styles/main.css'

async function bootstrap(): Promise<void> {
  const app = createApp(App)

  for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(name, component)
  }

  app.use(pinia)
  app.use(ElementPlus, { locale: zhCn })

  // 演示/截图模式：构建时注入 VITE_DEMO_AUTO_LOGIN=1，可在无人工交互下直接进入控制台。
  // 账号来自 .env.example 里公开的默认账号，不涉及任何私有凭据。
  const auth = useAuthStore(pinia)
  if (import.meta.env.VITE_DEMO_AUTO_LOGIN === '1' && !auth.isLoggedIn) {
    try {
      await auth.login(
        import.meta.env.VITE_DEMO_USERNAME || 'admin',
        import.meta.env.VITE_DEMO_PASSWORD || 'admin123',
      )
    } catch {
      // 登录失败则正常落到登录页，不阻塞应用启动
    }
  }

  app.use(router)
  await router.isReady()
  app.mount('#app')

  if (auth.isLoggedIn && router.currentRoute.value.name === 'login') {
    await router.replace({ name: 'dashboard' })
  }
}

void bootstrap()
