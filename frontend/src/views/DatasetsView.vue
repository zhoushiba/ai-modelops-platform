<template>
  <div>
    <div class="page-header">
      <div>
        <h2>数据集管理</h2>
        <p>上传 CSV/JSONL 即成为不可变版本，支持字段映射、质量体检、版本 diff 与导出</p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate()">新建数据集</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-input
        v-model="filters.q"
        placeholder="搜索数据集名称 / 描述"
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
      <span class="muted">共 {{ total }} 个数据集</span>
    </div>

    <AsyncState :loading="loading && !items.length" :error="error" :rows="6" @retry="load">
      <div class="card">
        <el-table :data="items" style="width: 100%">
          <el-table-column label="数据集" min-width="240">
            <template #default="{ row }">
              <div class="name-cell">
                <b>{{ row.name }}</b>
                <span class="muted desc">{{ row.description || '暂无描述' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="任务类型" width="120">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ taskTypeLabel(row.task_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="版本" width="90">
            <template #default="{ row }">
              <span class="mono">v{{ row.latest_version?.version ?? '—' }}</span>
              <span class="muted"> / {{ row.version_count }}</span>
            </template>
          </el-table-column>
          <el-table-column label="样本量" width="150">
            <template #default="{ row }">
              <template v-if="row.latest_version">
                <b>{{ formatNumber(row.latest_version.row_count) }}</b>
                <span class="muted"> · train {{ row.latest_version.train_count }} / val {{ row.latest_version.val_count }}</span>
              </template>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="标签" width="80">
            <template #default="{ row }">{{ row.latest_version?.label_count ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="校验和" width="130">
            <template #default="{ row }">
              <span class="mono muted">{{ truncate(row.latest_version?.checksum, 12) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" width="170">
            <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="190" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openDetail(row)">详情</el-button>
              <el-button text type="primary" size="small" @click="openCreate(row)">新版本</el-button>
              <el-popconfirm title="删除后数据集与所有版本都会下线，确认？" width="240" @confirm="remove(row)">
                <template #reference>
                  <el-button text type="danger" size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="70" description="还没有数据集，点击右上角「新建数据集」上传" />
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

    <!-- 新建 / 追加版本 -->
    <el-dialog v-model="dialogVisible" :title="dialogMode === 'create' ? '新建数据集' : `追加版本 · ${dialogDataset?.name || ''}`" width="560px">
      <el-form :model="form" label-width="100px">
        <template v-if="dialogMode === 'create'">
          <el-form-item label="名称" required>
            <el-input v-model="form.name" maxlength="80" placeholder="例如：客服工单分类（2026-11）" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="form.description" type="textarea" :rows="2" maxlength="200" />
          </el-form-item>
          <el-form-item label="任务类型" required>
            <el-radio-group v-model="form.task_type">
              <el-radio value="text_classification">文本分类</el-radio>
              <el-radio value="rag_corpus">RAG 知识库</el-radio>
            </el-radio-group>
          </el-form-item>
        </template>
        <el-form-item v-else label="版本说明">
          <el-input v-model="form.note" placeholder="例如：补充退款类工单 40 条" />
        </el-form-item>

        <el-form-item label="字段映射">
          <div class="field-row">
            <el-input v-model="form.text_field" placeholder="文本列" />
            <el-input v-model="form.label_field" placeholder="标签列（RAG 可留空）" />
            <el-input v-model="form.split_field" placeholder="split 列（可选）" />
          </div>
        </el-form-item>
        <el-form-item label="验证集比例">
          <el-input-number v-model="form.val_ratio" :min="0" :max="0.5" :step="0.05" :precision="2" />
          <span class="muted hint">文件里没有 split 列时，按文本哈希稳定切分</span>
        </el-form-item>

        <el-form-item label="数据文件" required>
          <el-upload
            ref="uploadRef"
            drag
            :auto-upload="false"
            :limit="1"
            accept=".csv,.jsonl,.json,.txt"
            :on-change="onFileChange"
            :on-remove="onFileRemove"
            style="width: 100%"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖入 CSV / JSONL，或 <em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">CSV 需包含文本列与标签列（UTF-8）；单文件上限 20MB</div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">上传并创建版本</el-button>
      </template>
    </el-dialog>

    <!-- 数据集详情 -->
    <el-drawer v-model="drawerVisible" :title="current?.name || '数据集详情'" size="70%">
      <template v-if="current">
        <div class="drawer-summary">
          <el-descriptions :column="4" size="small" border>
            <el-descriptions-item label="任务类型">{{ taskTypeLabel(current.task_type) }}</el-descriptions-item>
            <el-descriptions-item label="版本数">{{ current.version_count }}</el-descriptions-item>
            <el-descriptions-item label="负责人">{{ current.owner || '—' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatDateTime(current.created_at) }}</el-descriptions-item>
          </el-descriptions>
          <p class="muted desc-line">{{ current.description || '暂无描述' }}</p>
        </div>

        <el-tabs v-model="tab" @tab-change="onTabChange">
          <el-tab-pane label="版本列表" name="versions">
            <el-table :data="versions" size="small">
              <el-table-column label="版本" width="80">
                <template #default="{ row }"><span class="mono">v{{ row.version }}</span></template>
              </el-table-column>
              <el-table-column label="总样本" width="100">
                <template #default="{ row }">{{ formatNumber(row.row_count) }}</template>
              </el-table-column>
              <el-table-column label="train / val" width="130">
                <template #default="{ row }">{{ row.train_count }} / {{ row.val_count }}</template>
              </el-table-column>
              <el-table-column label="标签数" width="80" prop="label_count" />
              <el-table-column label="校验和" width="130">
                <template #default="{ row }"><span class="mono muted">{{ truncate(row.checksum, 12) }}</span></template>
              </el-table-column>
              <el-table-column label="创建时间" width="160">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" min-width="230">
                <template #default="{ row }">
                  <el-button text type="primary" size="small" @click="previewVersion(row)">样本</el-button>
                  <el-button text type="primary" size="small" @click="showQuality(row)">质量</el-button>
                  <el-button
                    text
                    type="primary"
                    size="small"
                    :disabled="row.version <= 1"
                    @click="showDiff(row)"
                  >
                    对比上一版
                  </el-button>
                  <el-button text type="primary" size="small" @click="exportCsv(row)">导出</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <el-empty :image-size="60" description="暂无版本" />
              </template>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="样本预览" name="samples">
            <div class="filter-bar">
              <el-radio-group v-model="sampleSplit" size="small" @change="loadSamples(1)">
                <el-radio-button value="">全部</el-radio-button>
                <el-radio-button value="train">train</el-radio-button>
                <el-radio-button value="val">val</el-radio-button>
              </el-radio-group>
              <span class="muted">
                {{ activeVersion ? `v${activeVersion.version} · ${formatNumber(sampleTotal)} 条` : '请先在版本列表选择版本' }}
              </span>
            </div>
            <el-table :data="samples" size="small" v-loading="versionLoading">
              <el-table-column prop="row_index" label="#" width="70" />
              <el-table-column prop="text" label="文本" min-width="320" show-overflow-tooltip />
              <el-table-column prop="label" label="标签" width="120" show-overflow-tooltip />
              <el-table-column prop="split" label="split" width="80" />
              <template #empty>
                <el-empty :image-size="60" description="点击版本列表的「样本」加载数据" />
              </template>
            </el-table>
            <div class="pager">
              <el-pagination
                v-model:current-page="samplePage"
                :page-size="sampleSize"
                :total="sampleTotal"
                layout="prev, pager, next"
                small
                @current-change="loadSamples"
              />
            </div>
          </el-tab-pane>

          <el-tab-pane label="质量报告" name="quality">
            <template v-if="quality">
              <div class="grid-cards">
                <div class="stat-card">
                  <span class="label">样本量</span>
                  <span class="value">{{ formatNumber(quality.row_count) }}</span>
                  <span class="sub">标签 {{ quality.label_count }} 类 · split {{ splitText }}</span>
                </div>
                <div class="stat-card">
                  <span class="label">重复率</span>
                  <span class="value">{{ formatPercent(quality.duplicate_ratio) }}</span>
                  <span class="sub">{{ quality.duplicate_count }} 条重复文本</span>
                </div>
                <div class="stat-card">
                  <span class="label">空值 / 超长</span>
                  <span class="value">{{ quality.empty_count }} / {{ quality.too_long_count }}</span>
                  <span class="sub">超长会在训练时截断</span>
                </div>
                <div class="stat-card">
                  <span class="label">文本长度</span>
                  <span class="value">{{ quality.length_stats.avg ?? 0 }}</span>
                  <span class="sub">
                    p50 {{ quality.length_stats.p50 }} · p95 {{ quality.length_stats.p95 }} · max
                    {{ quality.length_stats.max }}
                  </span>
                </div>
              </div>

              <el-alert
                v-for="issue in quality.issues"
                :key="issue"
                :title="issue"
                type="warning"
                :closable="false"
                show-icon
                class="issue"
              />
              <el-alert
                v-if="!quality.issues.length"
                title="质量检查未发现明显问题"
                type="success"
                :closable="false"
                show-icon
                class="issue"
              />

              <div class="card label-card">
                <div class="card-title"><span>标签分布</span></div>
                <el-table :data="labelRows" size="small">
                  <el-table-column prop="label" label="标签" />
                  <el-table-column prop="count" label="样本数" width="120" />
                  <el-table-column label="占比" width="220">
                    <template #default="{ row }">
                      <el-progress :percentage="Number((row.ratio * 100).toFixed(1))" :stroke-width="10" />
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </template>
            <el-empty v-else :image-size="60" description="点击版本列表的「质量」生成报告" />
          </el-tab-pane>

          <el-tab-pane label="版本对比" name="diff">
            <template v-if="diff">
              <el-alert
                :title="`v${diff.base_version} → v${diff.target_version}`"
                type="info"
                :closable="false"
                show-icon
              />
              <div class="grid-cards diff-cards">
                <div class="stat-card">
                  <span class="label">新增</span>
                  <span class="value">+{{ diff.added }}</span>
                  <span class="sub">新版本独有样本</span>
                </div>
                <div class="stat-card">
                  <span class="label">删除</span>
                  <span class="value">-{{ diff.removed }}</span>
                  <span class="sub">旧版本独有样本</span>
                </div>
                <div class="stat-card">
                  <span class="label">标签变更</span>
                  <span class="value">{{ diff.label_changed }}</span>
                  <span class="sub">同文本不同标签</span>
                </div>
                <div class="stat-card">
                  <span class="label">总量变化</span>
                  <span class="value">{{ diff.previous_version_total }} → {{ diff.current_version_total }}</span>
                  <span class="sub">共 {{ diff.changed_total }} 处变化</span>
                </div>
              </div>
              <div class="card">
                <div class="card-title"><span>新增样本示例</span></div>
                <ul class="example-list">
                  <li v-for="(text, index) in diff.added_examples" :key="`a${index}`">{{ text }}</li>
                  <li v-if="!diff.added_examples.length" class="muted">无新增样本</li>
                </ul>
              </div>
            </template>
            <el-empty v-else :image-size="60" description="点击版本列表的「对比上一版」" />
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, type UploadFile, type UploadInstance } from 'element-plus'
import { Plus, Refresh, Search, UploadFilled } from '@element-plus/icons-vue'
import AsyncState from '@/components/AsyncState.vue'
import { datasetApi } from '@/api'
import type { Dataset, DatasetSample, DatasetVersion, QualityReport, VersionDiff } from '@/types'
import { formatDateTime, formatNumber, formatPercent, taskTypeLabel, truncate } from '@/utils/format'

const loading = ref(false)
const error = ref('')
const items = ref<Dataset[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const filters = reactive({ q: '', task_type: '' })

const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'version'>('create')
const dialogDataset = ref<Dataset | null>(null)
const form = reactive({
  name: '',
  description: '',
  task_type: 'text_classification',
  note: '',
  text_field: 'text',
  label_field: 'label',
  split_field: 'split',
  val_ratio: 0.2,
})
const file = ref<File | null>(null)
const uploadRef = ref<UploadInstance>()
const submitting = ref(false)

const drawerVisible = ref(false)
const current = ref<Dataset | null>(null)
const versions = ref<DatasetVersion[]>([])
const tab = ref('versions')
const activeVersion = ref<DatasetVersion | null>(null)
const versionLoading = ref(false)
const samples = ref<DatasetSample[]>([])
const sampleTotal = ref(0)
const sampleSplit = ref('')
const samplePage = ref(1)
const sampleSize = 20
const quality = ref<QualityReport | null>(null)
const diff = ref<VersionDiff | null>(null)

const splitText = computed(() => {
  if (!quality.value) return '—'
  return Object.entries(quality.value.split_distribution)
    .map(([key, value]) => `${key} ${value}`)
    .join(' / ')
})
const labelRows = computed(() => {
  if (!quality.value) return []
  const totalCount = quality.value.row_count || 1
  return Object.entries(quality.value.label_distribution).map(([label, count]) => ({
    label,
    count,
    ratio: count / totalCount,
  }))
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await datasetApi.list({
      q: filters.q || undefined,
      task_type: filters.task_type || undefined,
      page: page.value,
      size: size.value,
    })
    items.value = result.items
    total.value = result.total
  } catch (err) {
    error.value = (err as Error).message || '加载数据集失败'
  } finally {
    loading.value = false
  }
}

function onSearch(): void {
  page.value = 1
  void load()
}

function resetForm(): void {
  form.name = ''
  form.description = ''
  form.task_type = 'text_classification'
  form.note = ''
  form.text_field = 'text'
  form.label_field = 'label'
  form.split_field = 'split'
  form.val_ratio = 0.2
  file.value = null
  uploadRef.value?.clearFiles()
}

function openCreate(dataset?: Dataset): void {
  resetForm()
  dialogDataset.value = dataset || null
  dialogMode.value = dataset ? 'version' : 'create'
  if (dataset) {
    form.task_type = dataset.task_type
    form.text_field = dataset.task_type === 'rag_corpus' ? 'content' : 'text'
  }
  dialogVisible.value = true
}

function onFileChange(uploadFile: UploadFile): void {
  file.value = uploadFile.raw || null
}

function onFileRemove(): void {
  file.value = null
}

async function submit(): Promise<void> {
  if (!file.value) {
    ElMessage.warning('请选择要上传的数据文件')
    return
  }
  if (dialogMode.value === 'create' && !form.name.trim()) {
    ElMessage.warning('请填写数据集名称')
    return
  }
  const payload = new FormData()
  payload.append('file', file.value)
  payload.append('text_field', form.text_field || 'text')
  payload.append('label_field', form.label_field || '')
  payload.append('split_field', form.split_field || '')
  payload.append('val_ratio', String(form.val_ratio))

  submitting.value = true
  try {
    if (dialogMode.value === 'create') {
      payload.append('name', form.name)
      payload.append('description', form.description)
      payload.append('task_type', form.task_type)
      const result = await datasetApi.create(payload)
      ElMessage.success(`数据集已创建：v${result.version.version}，共 ${result.version.row_count} 条`)
    } else {
      payload.append('note', form.note)
      const result = await datasetApi.addVersion(dialogDataset.value!.id, payload)
      ElMessage.success(`新版本 v${result.version.version} 已创建，共 ${result.version.row_count} 条`)
      if (current.value?.id === dialogDataset.value!.id) await openDetail(dialogDataset.value!)
    }
    dialogVisible.value = false
    await load()
  } finally {
    submitting.value = false
  }
}

async function openDetail(row: Dataset): Promise<void> {
  const detail = await datasetApi.detail(row.id)
  current.value = detail
  versions.value = detail.versions || []
  drawerVisible.value = true
  tab.value = 'versions'
  activeVersion.value = versions.value[0] || null
}

async function previewVersion(row: DatasetVersion): Promise<void> {
  activeVersion.value = row
  tab.value = 'samples'
  await loadSamples(1)
}

async function showQuality(row: DatasetVersion): Promise<void> {
  activeVersion.value = row
  tab.value = 'quality'
  quality.value = null
  versionLoading.value = true
  try {
    quality.value = await datasetApi.quality(row.id)
  } finally {
    versionLoading.value = false
  }
}

async function showDiff(row: DatasetVersion): Promise<void> {
  const previous = versions.value.find((item) => item.version === row.version - 1)
  if (!previous) {
    ElMessage.warning('找不到上一版本，无法对比')
    return
  }
  activeVersion.value = row
  tab.value = 'diff'
  diff.value = null
  versionLoading.value = true
  try {
    diff.value = await datasetApi.diff(row.id, previous.id)
  } finally {
    versionLoading.value = false
  }
}

async function loadSamples(targetPage: number): Promise<void> {
  if (!activeVersion.value) return
  samplePage.value = typeof targetPage === 'number' ? targetPage : samplePage.value
  versionLoading.value = true
  try {
    const result = await datasetApi.samples(activeVersion.value.id, {
      split: sampleSplit.value || undefined,
      page: samplePage.value,
      size: sampleSize,
    })
    samples.value = result.items
    sampleTotal.value = result.total
  } finally {
    versionLoading.value = false
  }
}

function onTabChange(name: string | number): void {
  if (name === 'samples' && activeVersion.value && !samples.value.length) {
    void loadSamples(1)
  }
}

async function exportCsv(row: DatasetVersion): Promise<void> {
  await datasetApi.exportCsv(row.id, `dataset-${row.dataset_id}-v${row.version}.csv`)
  ElMessage.success('已开始下载 CSV')
}

async function remove(row: Dataset): Promise<void> {
  await datasetApi.remove(row.id)
  ElMessage.success('数据集已删除')
  if (current.value?.id === row.id) drawerVisible.value = false
  await load()
}

onMounted(load)
</script>

<style scoped>
.name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.name-cell .desc {
  font-size: 12px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.field-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  width: 100%;
}

.hint {
  margin-left: 10px;
  font-size: 12px;
}

.drawer-summary {
  margin-bottom: 8px;
}

.desc-line {
  margin: 10px 0 0;
  font-size: 13px;
}

.issue {
  margin-top: 10px;
}

.label-card {
  margin-top: 14px;
}

.diff-cards {
  margin: 14px 0;
}

.example-list {
  margin: 0;
  padding-left: 18px;
  color: #334155;
  font-size: 13px;
  line-height: 1.9;
}
</style>
