<template>
  <div>
    <div class="page-header">
      <div>
        <h2>模型注册表</h2>
        <p>训练产物登记为不可变版本，用 staging / production / archived 管理上线状态并支持回滚</p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <router-link to="/training"><el-button type="primary" plain>去训练任务注册 →</el-button></router-link>
      </div>
    </div>

    <div class="filter-bar">
      <el-input
        v-model="filters.q"
        placeholder="搜索模型名称 / 描述"
        clearable
        style="width: 260px"
        :prefix-icon="Search"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <el-select v-model="filters.task_type" placeholder="任务类型" clearable style="width: 170px" @change="onSearch">
        <el-option value="text_classification" label="文本分类" />
        <el-option value="rag_corpus" label="RAG 知识库" />
      </el-select>
      <el-button @click="onSearch">查询</el-button>
      <span class="muted">共 {{ total }} 个模型</span>
    </div>

    <AsyncState :loading="loading && !items.length" :error="error" :rows="6" @retry="load">
      <div class="card">
        <el-table :data="items" style="width: 100%">
          <el-table-column label="模型" min-width="230">
            <template #default="{ row }">
              <div class="name-cell">
                <b>{{ row.name }}</b>
                <span class="muted desc">{{ row.description || '暂无描述' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="任务类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ taskTypeLabel(row.task_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="版本" width="110">
            <template #default="{ row }">
              <div>
                <span class="mono">latest v{{ row.latest_version?.version ?? '—' }}</span>
              </div>
              <div class="muted small">共 {{ row.version_count }} 个版本</div>
            </template>
          </el-table-column>
          <el-table-column label="生产版本" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.production_version" type="success" effect="light" size="small">
                v{{ row.production_version }}
              </el-tag>
              <span v-else class="muted">未上线</span>
            </template>
          </el-table-column>
          <el-table-column label="最佳准确率" width="120">
            <template #default="{ row }">
              <span v-if="row.best_accuracy !== null" class="mono">{{ formatPercent(row.best_accuracy, 2) }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="框架" width="110">
            <template #default="{ row }">
              <span class="mono muted">{{ row.latest_version?.framework || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="165">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openDetail(row)">版本与上线</el-button>
              <el-button
                text
                type="primary"
                size="small"
                :disabled="!row.version_count || (row.production_version || 0) >= (row.latest_version?.version || 0)"
                @click="openRollback(row)"
              >
                回滚
              </el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="70" description="还没有模型版本，先去训练任务页跑一次训练" />
          </template>
        </el-table>

        <div class="pager">
          <el-pagination
            v-model:current-page="page"
            :page-size="size"
            :total="total"
            layout="prev, pager, next, total"
            background
            @current-change="load"
          />
        </div>
      </div>
    </AsyncState>

    <!-- 版本列表 -->
    <el-drawer v-model="drawerVisible" :title="current ? `模型版本 · ${current.name}` : '模型版本'" size="72%">
      <template v-if="current">
        <el-descriptions :column="4" size="small" border class="summary">
          <el-descriptions-item label="任务类型">{{ taskTypeLabel(current.task_type) }}</el-descriptions-item>
          <el-descriptions-item label="版本数">{{ current.version_count }}</el-descriptions-item>
          <el-descriptions-item label="生产版本">
            {{ current.production_version ? `v${current.production_version}` : '未上线' }}
          </el-descriptions-item>
          <el-descriptions-item label="最佳准确率">{{ formatPercent(current.best_accuracy, 2) }}</el-descriptions-item>
        </el-descriptions>

        <el-table :data="versions" size="small" class="version-table">
          <el-table-column label="版本" width="80">
            <template #default="{ row }"><span class="mono">v{{ row.version }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="modelStatus(row.status).type" effect="light" size="small">
                {{ modelStatus(row.status).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="准确率 / 指标" width="190">
            <template #default="{ row }">
              <template v-if="row.metrics?.accuracy !== undefined">
                <div class="mono">acc {{ formatPercent(row.metrics.accuracy, 2) }}</div>
                <div class="muted mono">F1 {{ formatPercent(row.metrics.f1_macro, 2) }}</div>
              </template>
              <template v-else>
                <div class="mono">{{ row.metrics?.chunk_count }} chunks</div>
                <div class="muted mono">dim {{ row.metrics?.embedding_dim }}</div>
              </template>
            </template>
          </el-table-column>
          <el-table-column label="训练任务" width="150" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="muted">{{ row.training_job_name || `job#${row.training_job_id}` }}</span>
            </template>
          </el-table-column>
          <el-table-column label="产物" width="130">
            <template #default="{ row }">{{ formatBytes(row.artifact_size) }}</template>
          </el-table-column>
          <el-table-column label="部署数" width="80" prop="deployment_count" />
          <el-table-column label="创建时间" width="160">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" min-width="260">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="showCard(row)">Model Card</el-button>
              <el-button
                text
                type="success"
                size="small"
                :disabled="row.status === 'production'"
                @click="setStatus(row, 'production')"
              >
                设为生产
              </el-button>
              <el-button
                text
                type="warning"
                size="small"
                :disabled="row.status === 'staging'"
                @click="setStatus(row, 'staging')"
              >
                预发布
              </el-button>
              <el-button
                text
                type="info"
                size="small"
                :disabled="row.status === 'archived'"
                @click="setStatus(row, 'archived')"
              >
                归档
              </el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="60" description="暂无版本" />
          </template>
        </el-table>
      </template>
    </el-drawer>

    <!-- 回滚 -->
    <el-dialog v-model="rollbackVisible" title="回滚到指定版本" width="420px">
      <p class="muted">
        当前生产版本：
        <b>{{ current?.production_version ? `v${current.production_version}` : '未上线' }}</b>
        ，选择要回滚到的版本（该版本会被直接置为 production，当前生产版本自动归档）。
      </p>
      <el-select v-model="rollbackVersion" placeholder="选择版本" style="width: 100%">
        <el-option v-for="version in versions" :key="version.id" :value="version.version" :label="`v${version.version}`">
          <span>v{{ version.version }}</span>
          <span class="muted option-status">{{ modelStatus(version.status).text }}</span>
        </el-option>
      </el-select>
      <template #footer>
        <el-button @click="rollbackVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="doRollback">确认回滚</el-button>
      </template>
    </el-dialog>

    <!-- Model Card -->
    <el-dialog v-model="cardVisible" :title="cardTitle" width="760px">
      <pre class="code-block card-preview">{{ cardContent }}</pre>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import AsyncState from '@/components/AsyncState.vue'
import { modelApi } from '@/api'
import type { ModelRegistry, ModelVersion } from '@/types'
import { formatBytes, formatDateTime, formatPercent, modelStatus, taskTypeLabel } from '@/utils/format'

const loading = ref(false)
const error = ref('')
const items = ref<ModelRegistry[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const filters = reactive({ q: '', task_type: '' })

const drawerVisible = ref(false)
const current = ref<ModelRegistry | null>(null)
const versions = ref<ModelVersion[]>([])
const submitting = ref(false)

const rollbackVisible = ref(false)
const rollbackVersion = ref<number | null>(null)
const cardVisible = ref(false)
const cardTitle = ref('')
const cardContent = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await modelApi.list({
      q: filters.q || undefined,
      task_type: filters.task_type || undefined,
      page: page.value,
      size: size.value,
    })
    items.value = result.items
    total.value = result.total
  } catch (err) {
    error.value = (err as Error).message || '加载模型列表失败'
  } finally {
    loading.value = false
  }
}

function onSearch(): void {
  page.value = 1
  void load()
}

async function openDetail(row: ModelRegistry): Promise<void> {
  const detail = await modelApi.detail(row.id)
  current.value = detail
  versions.value = (detail.versions || []).slice().sort((a, b) => b.version - a.version)
  drawerVisible.value = true
}

async function setStatus(version: ModelVersion, status: string): Promise<void> {
  await modelApi.status(version.id, status, `控制台操作：${status}`)
  ElMessage.success(`v${version.version} 已更新为 ${modelStatus(status).text}`)
  if (current.value) await openDetail(current.value)
  await load()
}

function openRollback(row: ModelRegistry): void {
  current.value = row
  rollbackVersion.value = null
  void (async () => {
    const detail = await modelApi.detail(row.id)
    current.value = detail
    versions.value = (detail.versions || []).slice().sort((a, b) => b.version - a.version)
    rollbackVisible.value = true
  })()
}

async function doRollback(): Promise<void> {
  if (!current.value || !rollbackVersion.value) {
    ElMessage.warning('请选择要回滚到的版本')
    return
  }
  submitting.value = true
  try {
    await modelApi.rollback(current.value.id, rollbackVersion.value)
    ElMessage.success(`已回滚到 v${rollbackVersion.value}`)
    rollbackVisible.value = false
    await load()
    if (drawerVisible.value) await openDetail(current.value)
  } finally {
    submitting.value = false
  }
}

async function showCard(version: ModelVersion): Promise<void> {
  const result = await modelApi.card(version.id)
  cardTitle.value = `Model Card · ${version.registry_name} v${version.version}`
  cardContent.value = result.model_card || version.model_card_md || '暂无 Model Card'
  cardVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.desc {
  font-size: 12px;
}

.small {
  font-size: 11px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.summary {
  margin-bottom: 14px;
}

.version-table {
  margin-bottom: 8px;
}

.option-status {
  margin-left: 10px;
  font-size: 12px;
}

.card-preview {
  max-height: 60vh;
  margin: 0;
}
</style>
