import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { pinia } from '@/stores'
import { useAuthStore } from '@/stores/auth'

/** 侧边栏菜单即路由表：title/icon 由 AdminLayout 直接消费。 */
export const menuRoutes: RouteRecordRaw[] = [
  {
    path: 'dashboard',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { title: '运行看板', icon: 'DataLine' },
  },
  {
    path: 'datasets',
    name: 'datasets',
    component: () => import('@/views/DatasetsView.vue'),
    meta: { title: '数据集管理', icon: 'Files' },
  },
  {
    path: 'training',
    name: 'training',
    component: () => import('@/views/TrainingView.vue'),
    meta: { title: '训练任务', icon: 'Cpu' },
  },
  {
    path: 'registry',
    name: 'registry',
    component: () => import('@/views/RegistryView.vue'),
    meta: { title: '模型注册表', icon: 'Box' },
  },
  {
    path: 'deployments',
    name: 'deployments',
    component: () => import('@/views/DeploymentsView.vue'),
    meta: { title: '部署与推理', icon: 'Promotion' },
  },
  {
    path: 'evals',
    name: 'evals',
    component: () => import('@/views/EvalsView.vue'),
    meta: { title: '评测对比', icon: 'DataAnalysis' },
  },
  {
    path: 'prompts',
    name: 'prompts',
    component: () => import('@/views/PromptsView.vue'),
    meta: { title: 'Prompt 模板', icon: 'ChatDotSquare' },
  },
  {
    path: 'api-keys',
    name: 'api-keys',
    component: () => import('@/views/ApiKeysView.vue'),
    meta: { title: 'API Key 与调用日志', icon: 'Key' },
  },
]

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/AdminLayout.vue'),
    redirect: '/dashboard',
    children: menuRoutes,
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  // hash 模式：静态托管的 dist 也能直接刷新，截图/演示无需服务端 rewrite
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  const auth = useAuthStore(pinia)
  if (to.meta.public) {
    if (to.name === 'login' && auth.isLoggedIn) return { name: 'dashboard' }
    return true
  }
  if (!auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || 'ModelOps 控制台'
  document.title = `${title} · ModelOps 控制台`
})

export default router
