<template>
  <div class="login-page">
    <section class="login-brand">
      <div class="brand-mark">
        <el-icon :size="30"><Monitor /></el-icon>
        <span>ModelOps</span>
      </div>
      <h1>AI 模型训练与推理服务平台</h1>
      <p class="tagline">
        从数据集版本、训练任务、模型注册与回滚，到一键部署和 OpenAI 兼容推理接口，
        一条链路跑通「训练 → 评测 → 部署 → 调用计量」。
      </p>

      <ul class="feature-list">
        <li>
          <el-icon><Files /></el-icon>
          <div><b>数据即版本</b><span>数据切片、质量体检、版本 diff、CSV 导出</span></div>
        </li>
        <li>
          <el-icon><Cpu /></el-icon>
          <div><b>可追踪的训练</b><span>后台工作者执行、日志/指标流式可看、可取消、可失败重试</span></div>
        </li>
        <li>
          <el-icon><Promotion /></el-icon>
          <div><b>一键部署 + 限流记账</b><span>API Key 哈希存储、令牌桶限流、429 与用量统计</span></div>
        </li>
        <li>
          <el-icon><DataAnalysis /></el-icon>
          <div><b>评测与 A/B</b><span>模型版本横向对比、Prompt 模板 A/B 打分</span></div>
        </li>
      </ul>

      <div class="tech-stack">FastAPI · SQLAlchemy · scikit-learn · Vue 3 · TypeScript · Element Plus</div>
    </section>

    <section class="login-panel">
      <div class="login-card">
        <h2>登录控制台</h2>
        <p class="muted">使用演示账号体验全流程</p>

        <el-alert type="info" :closable="false" show-icon class="demo-hint">
          演示账号：<b>admin</b> / <b>admin123</b>
        </el-alert>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="onSubmit">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" size="large" placeholder="admin" :prefix-icon="User" autocomplete="username" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              show-password
              placeholder="admin123"
              :prefix-icon="Lock"
              autocomplete="current-password"
              @keyup.enter="onSubmit"
            />
          </el-form-item>
          <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="onSubmit">
            登录
          </el-button>
        </el-form>

        <div class="login-foot">
          <span>首次启动会自动落库演示数据集、训练任务与 Prompt 模板</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: 'admin', password: 'admin123' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit(): Promise<void> {
  if (loading.value) return
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    const user = await auth.login(form.username, form.password)
    ElMessage.success(`欢迎回来，${user.display_name}`)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    await router.replace(redirect)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(380px, 0.9fr);
}

.login-brand {
  position: relative;
  padding: 56px 64px;
  color: #e2e8f0;
  background: radial-gradient(1200px 600px at 10% 0%, #1e3a8a 0%, #0f172a 55%, #020617 100%);
  display: flex;
  flex-direction: column;
  justify-content: center;
  overflow: hidden;
}

.login-brand::after {
  content: '';
  position: absolute;
  inset: auto -120px -160px auto;
  width: 460px;
  height: 460px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.28), transparent 65%);
}

.brand-mark {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: #7dd3fc;
}

.login-brand h1 {
  font-size: 40px;
  line-height: 1.2;
  margin: 28px 0 14px;
  max-width: 520px;
}

.tagline {
  max-width: 520px;
  color: #94a3b8;
  line-height: 1.8;
  margin: 0 0 30px;
}

.feature-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 16px;
  max-width: 560px;
}

.feature-list li {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.feature-list .el-icon {
  margin-top: 3px;
  color: #38bdf8;
}

.feature-list b {
  display: block;
  font-size: 14px;
  color: #f1f5f9;
}

.feature-list span {
  font-size: 13px;
  color: #94a3b8;
}

.tech-stack {
  margin-top: 34px;
  font-size: 12px;
  letter-spacing: 0.4px;
  color: #64748b;
}

.login-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  background: #f8fafc;
}

.login-card {
  width: 100%;
  max-width: 380px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 30px 28px 24px;
  box-shadow: 0 20px 45px -30px rgba(15, 23, 42, 0.45);
}

.login-card h2 {
  margin: 0 0 4px;
  font-size: 22px;
}

.demo-hint {
  margin: 16px 0 18px;
}

.submit-btn {
  width: 100%;
  margin-top: 4px;
}

.login-foot {
  margin-top: 18px;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.6;
}

@media (max-width: 900px) {
  .login-page {
    grid-template-columns: 1fr;
  }

  .login-brand {
    padding: 36px 28px;
  }

  .login-brand h1 {
    font-size: 28px;
  }

  .feature-list {
    display: none;
  }
}
</style>
