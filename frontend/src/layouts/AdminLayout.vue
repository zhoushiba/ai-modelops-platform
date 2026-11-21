<template>
  <el-container class="layout">
    <el-aside :width="collapsed ? '64px' : '224px'" class="layout-aside">
      <div class="brand" @click="router.push('/dashboard')">
        <el-icon :size="24" color="#7dd3fc"><Monitor /></el-icon>
        <span v-show="!collapsed" class="brand-text">
          <b>ModelOps</b>
          <small>模型训练与推理平台</small>
        </span>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="collapsed"
        :collapse-transition="false"
        class="layout-menu"
        background-color="#0f172a"
        text-color="#cbd5e1"
        active-text-color="#7dd3fc"
        router
      >
        <el-menu-item v-for="item in menuRoutes" :key="item.path" :index="`/${item.path}`">
          <el-icon><component :is="item.meta?.icon || 'Menu'" /></el-icon>
          <template #title>{{ item.meta?.title }}</template>
        </el-menu-item>
      </el-menu>

      <div v-show="!collapsed" class="aside-footer">
        <div class="env-tag">
          <el-icon><Cpu /></el-icon>
          <span>sqlite · demo</span>
        </div>
        <span>v1.0.0</span>
      </div>
    </el-aside>

    <el-container>
      <el-header class="layout-header">
        <div class="header-left">
          <el-button text :icon="collapsed ? Expand : Fold" @click="collapsed = !collapsed" />
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>控制台</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <el-tag v-if="health === 'ok'" type="success" effect="light" size="small">
            <el-icon><CircleCheck /></el-icon> 服务正常
          </el-tag>
          <el-tag v-else-if="health === 'down'" type="danger" effect="light" size="small">后端未连接</el-tag>
          <el-tag v-else type="info" effect="light" size="small">检测中…</el-tag>

          <a class="docs-link" :href="docsUrl" target="_blank" rel="noreferrer">
            <el-icon><Document /></el-icon> OpenAPI 文档
          </a>

          <el-dropdown trigger="click">
            <span class="user-chip">
              <el-avatar :size="26">{{ auth.displayName.slice(0, 1) }}</el-avatar>
              <span class="user-name">{{ auth.displayName }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>{{ auth.user?.role }} · {{ auth.user?.username }}</el-dropdown-item>
                <el-dropdown-item divided @click="onLogout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="layout-main">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Expand, Fold } from '@element-plus/icons-vue'
import { menuRoutes } from '@/router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const collapsed = ref(false)
const health = ref<'checking' | 'ok' | 'down'>('checking')
const docsUrl = `${window.location.protocol}//${window.location.hostname}:8000/docs`

const activeMenu = computed(() => `/${String(route.path).split('/')[1] || 'dashboard'}`)
const currentTitle = computed(() => (route.meta.title as string) || '运行看板')

onMounted(async () => {
  try {
    const response = await fetch('/health')
    health.value = response.ok ? 'ok' : 'down'
  } catch {
    health.value = 'down'
  }
  try {
    await auth.fetchMe()
  } catch {
    // 拦截器负责 401 跳转，这里静默失败即可
  }
})

function onLogout(): void {
  auth.logout()
  ElMessage.success('已退出登录')
  void router.push('/login')
}
</script>

<style scoped>
.layout {
  min-height: 100vh;
}

.layout-aside {
  display: flex;
  flex-direction: column;
  background: #0f172a;
  transition: width 0.2s ease;
  overflow: hidden;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 64px;
  padding: 0 18px;
  cursor: pointer;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  white-space: nowrap;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
  color: #e2e8f0;
}

.brand-text b {
  font-size: 16px;
  letter-spacing: 0.4px;
}

.brand-text small {
  font-size: 11px;
  color: #94a3b8;
}

.layout-menu {
  flex: 1;
  border-right: none;
  padding: 10px 8px;
}

.layout-menu:not(.el-menu--collapse) {
  width: 100%;
}

.layout-menu :deep(.el-menu-item) {
  height: 42px;
  border-radius: 8px;
  margin-bottom: 4px;
}

.layout-menu :deep(.el-menu-item.is-active) {
  background: rgba(56, 189, 248, 0.14);
}

.aside-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  font-size: 11px;
  color: #64748b;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
  white-space: nowrap;
}

.env-tag {
  display: flex;
  align-items: center;
  gap: 4px;
}

.layout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  padding: 0 20px;
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.docs-link {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #475569;
  text-decoration: none;
}

.docs-link:hover {
  color: #0284c7;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 13px;
  color: #1e293b;
  outline: none;
}

.user-name {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.layout-main {
  background: #f1f5f9;
  padding: 20px;
}
</style>
