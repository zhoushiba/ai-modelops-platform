<template>
  <div>
    <div class="page-header">
      <div>
        <h2>Prompt 模板与 A/B 实验</h2>
        <p>模板支持 <code v-pre>{{ 变量 }}</code> 占位符、版本号随内容变更递增，可双模板并行渲染输出做人工打分对比</p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" :loading="loading" @click="reloadAll">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建模板</el-button>
        <el-button type="success" :icon="Switch" :disabled="templates.length < 2" @click="openExperiment">
          发起 A/B 实验
        </el-button>
      </div>
    </div>

    <AsyncState :loading="loading && !templates.length" :error="error" :rows="4" @retry="reloadAll">
      <div class="card">
        <div class="card-title">Prompt 模板</div>
        <el-table :data="templates" style="width: 100%">
          <el-table-column label="模板" min-width="200">
            <template #default="{ row }">
              <b>{{ row.name }}</b>
              <div class="muted small">{{ row.description || '暂无描述' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="版本" width="80">
            <template #default="{ row }"><span class="mono">v{{ row.version }}</span></template>
          </el-table-column>
          <el-table-column label="变量" width="170">
            <template #default="{ row }">
              <el-tag v-for="variable in row.variables" :key="variable" size="small" effect="plain" class="var-tag">
                {{ variable }}
              </el-tag>
              <span v-if="!row.variables?.length" class="muted">无</span>
            </template>
          </el-table-column>
          <el-table-column label="标签" width="130">
            <template #default="{ row }"><span class="muted">{{ row.tags || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="内容预览" min-width="300">
            <template #default="{ row }">
              <span class="mono preview-text">{{ truncate(row.content, 110) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" width="160">
            <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openRender(row)">渲染预览</el-button>
              <el-button text type="primary" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="70" description="还没有模板，点右上角「新建模板」" />
          </template>
        </el-table>
      </div>

      <div class="card experiments-card">
        <div class="card-title">
          A/B 实验记录
          <span class="muted small">（同一输入分别用两个模板渲染，记录输出与耗时，支持 1-5 分人工打分）</span>
        </div>
        <el-table :data="experiments" size="small" style="width: 100%">
          <el-table-column label="实验" min-width="150">
            <template #default="{ row }">
              <b>{{ row.name || `exp#${row.id}` }}</b>
              <div class="muted small">{{ formatDateTime(row.created_at) }}</div>
            </template>
          </el-table-column>
          <el-table-column label="A / B 模板" min-width="180">
            <template #default="{ row }">
              <div>A：{{ row.template_a_name }}</div>
              <div>B：{{ row.template_b_name }}</div>
            </template>
          </el-table-column>
          <el-table-column label="A 输出" min-width="230">
            <template #default="{ row }">
              <span class="mono preview-text">{{ truncate(row.output_a, 90) }}</span>
              <div class="muted small mono">{{ row.latency_a_ms }} ms</div>
            </template>
          </el-table-column>
          <el-table-column label="B 输出" min-width="230">
            <template #default="{ row }">
              <span class="mono preview-text">{{ truncate(row.output_b, 90) }}</span>
              <div class="muted small mono">{{ row.latency_b_ms }} ms</div>
            </template>
          </el-table-column>
          <el-table-column label="打分" width="130">
            <template #default="{ row }">
              <span class="mono">{{ row.score_a ?? '—' }} / {{ row.score_b ?? '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openScore(row)">打分 / 查看</el-button>
            </template>
          </el-table-column>
          <template #empty><el-empty :image-size="60" description="还没有 A/B 实验" /></template>
        </el-table>
      </div>
    </AsyncState>

    <!-- 新建/编辑模板 -->
    <el-dialog v-model="formVisible" :title="editing ? '编辑模板' : '新建 Prompt 模板'" width="680px">
      <el-form label-width="90px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：客服回复-专业版" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="form.tags" placeholder="逗号分隔，如：客服,回复" />
        </el-form-item>
        <el-form-item label="模板内容">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="8"
            placeholder="使用 {{变量名}} 占位，如：你是客服助手，请根据资料回答：{{context}}"
          />
        </el-form-item>
        <el-form-item label="变量">
          <span class="muted mono">{{ extractedVariables.length ? extractedVariables.join(', ') : '从内容中自动抽取' }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 渲染预览 -->
    <el-dialog v-model="renderVisible" :title="`渲染预览 · ${renderTemplateName}`" width="720px">
      <el-form label-width="120px">
        <el-form-item v-for="variable in renderVariables" :key="variable" :label="variable">
          <el-input v-model="renderInputs[variable]" :placeholder="`{{${variable}}} 的值`" />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="missingVariables.length"
        type="warning"
        :closable="false"
        show-icon
        :title="`缺失变量：${missingVariables.join(', ')}`"
        class="render-alert"
      />
      <div class="panel-label">渲染结果</div>
      <pre class="code-block render-output">{{ rendered || '点击下方「重新渲染」查看结果' }}</pre>
      <template #footer>
        <el-button @click="renderVisible = false">关闭</el-button>
        <el-button type="primary" :loading="rendering" @click="doRender">重新渲染</el-button>
      </template>
    </el-dialog>

    <!-- 发起 A/B -->
    <el-dialog v-model="expVisible" title="发起 A/B 实验" width="640px">
      <el-form label-width="100px">
        <el-form-item label="实验名称">
          <el-input v-model="expForm.name" placeholder="可选，如：简洁 vs 详细" />
        </el-form-item>
        <el-form-item label="模板 A">
          <el-select v-model="expForm.template_a_id" style="width: 100%">
            <el-option v-for="item in templates" :key="item.id" :value="item.id" :label="item.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="模板 B">
          <el-select v-model="expForm.template_b_id" style="width: 100%">
            <el-option v-for="item in templates" :key="item.id" :value="item.id" :label="item.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="输入内容">
          <el-input v-model="expForm.input_text" type="textarea" :rows="3" placeholder="用户问题 / 待处理文本" />
        </el-form-item>
        <el-form-item v-for="variable in expVariables" :key="variable" :label="variable">
          <el-input v-model="expForm.variables[variable]" :placeholder="`变量 ${variable} 的值`" />
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="实验会同步调用推理引擎（未配置上游 LLM 时使用内置规则/检索式生成），记录两个模板的输出与耗时"
      />
      <template #footer>
        <el-button @click="expVisible = false">取消</el-button>
        <el-button type="primary" :loading="experimenting" @click="doExperiment">运行实验</el-button>
      </template>
    </el-dialog>

    <!-- 打分 -->
    <el-dialog v-model="scoreVisible" title="A/B 结果与打分" width="760px">
      <template v-if="scoring">
        <el-row :gutter="14">
          <el-col :span="12">
            <div class="panel-label">模板 A · {{ scoring.template_a_name }}（{{ scoring.latency_a_ms }} ms）</div>
            <pre class="code-block score-output">{{ scoring.output_a }}</pre>
            <el-rate v-model="scoreForm.a" :max="5" />
          </el-col>
          <el-col :span="12">
            <div class="panel-label">模板 B · {{ scoring.template_b_name }}（{{ scoring.latency_b_ms }} ms）</div>
            <pre class="code-block score-output">{{ scoring.output_b }}</pre>
            <el-rate v-model="scoreForm.b" :max="5" />
          </el-col>
        </el-row>
        <div class="panel-label">备注</div>
        <el-input v-model="scoreForm.notes" type="textarea" :rows="2" placeholder="哪个更好？为什么？" />
      </template>
      <template #footer>
        <el-button @click="scoreVisible = false">关闭</el-button>
        <el-button type="primary" :loading="scoringBusy" @click="submitScore">保存打分</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Switch } from '@element-plus/icons-vue'
import AsyncState from '@/components/AsyncState.vue'
import { promptApi } from '@/api'
import type { PromptExperiment, PromptTemplate } from '@/types'
import { formatDateTime, truncate } from '@/utils/format'

const loading = ref(false)
const error = ref('')
const templates = ref<PromptTemplate[]>([])
const experiments = ref<PromptExperiment[]>([])

const formVisible = ref(false)
const editing = ref<PromptTemplate | null>(null)
const submitting = ref(false)
const form = reactive({ name: '', description: '', tags: '', content: '' })

const renderVisible = ref(false)
const renderTemplateName = ref('')
const renderingTemplate = ref<PromptTemplate | null>(null)
const renderInputs = reactive<Record<string, string>>({})
const rendered = ref('')
const missingVariables = ref<string[]>([])
const rendering = ref(false)

const expVisible = ref(false)
const experimenting = ref(false)
const expForm = reactive({
  name: '',
  template_a_id: null as number | null,
  template_b_id: null as number | null,
  input_text: '',
  variables: {} as Record<string, string>,
})

const scoreVisible = ref(false)
const scoring = ref<PromptExperiment | null>(null)
const scoringBusy = ref(false)
const scoreForm = reactive({ a: 0, b: 0, notes: '' })

const extractedVariables = computed(() => {
  const matches = form.content.matchAll(/\{\{\s*([A-Za-z_][\w]*)\s*\}\}/g)
  return Array.from(new Set(Array.from(matches, (match) => match[1])))
})

const renderVariables = computed(() => renderingTemplate.value?.variables || [])
const expVariables = computed(() => {
  const template = templates.value.find((item) => item.id === expForm.template_a_id)
  return template?.variables || []
})

async function reloadAll(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [templateResult, experimentResult] = await Promise.all([
      promptApi.list(),
      promptApi.experiments(),
    ])
    templates.value = templateResult.items
    experiments.value = experimentResult.items
  } catch (err) {
    error.value = (err as Error).message || '加载 Prompt 数据失败'
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editing.value = null
  form.name = ''
  form.description = ''
  form.tags = ''
  form.content = '你是客服助手，请根据以下资料简洁回答用户问题。\n资料：{{context}}\n问题：{{question}}'
  formVisible.value = true
}

function openEdit(template: PromptTemplate): void {
  editing.value = template
  form.name = template.name
  form.description = template.description
  form.tags = template.tags
  form.content = template.content
  formVisible.value = true
}

async function submitForm(): Promise<void> {
  if (!form.name.trim() || !form.content.trim()) {
    ElMessage.warning('名称与内容都不能为空')
    return
  }
  submitting.value = true
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description,
      tags: form.tags,
      content: form.content,
    }
    if (editing.value) {
      await promptApi.update(editing.value.id, payload)
      ElMessage.success('模板已更新（内容变更会自动升版本）')
    } else {
      await promptApi.create(payload)
      ElMessage.success('模板已创建')
    }
    formVisible.value = false
    await reloadAll()
  } finally {
    submitting.value = false
  }
}

async function remove(template: PromptTemplate): Promise<void> {
  await ElMessageBox.confirm(`确认删除模板「${template.name}」？`, '删除确认', { type: 'warning' })
  await promptApi.remove(template.id)
  ElMessage.success('已删除')
  await reloadAll()
}

function openRender(template: PromptTemplate): void {
  renderingTemplate.value = template
  renderTemplateName.value = template.name
  for (const key of Object.keys(renderInputs)) delete renderInputs[key]
  for (const variable of template.variables || []) renderInputs[variable] = ''
  rendered.value = ''
  missingVariables.value = []
  renderVisible.value = true
  void doRender()
}

async function doRender(): Promise<void> {
  if (!renderingTemplate.value) return
  rendering.value = true
  try {
    const result = await promptApi.render(renderingTemplate.value.id, { ...renderInputs })
    rendered.value = result.rendered
    missingVariables.value = result.missing_variables
  } finally {
    rendering.value = false
  }
}

function openExperiment(): void {
  expForm.name = ''
  expForm.template_a_id = templates.value[0]?.id ?? null
  expForm.template_b_id = templates.value[1]?.id ?? templates.value[0]?.id ?? null
  expForm.input_text = '我的订单显示已发货三天了，物流一直没更新，能帮我看看吗？'
  expForm.variables = {}
  expVisible.value = true
}

async function doExperiment(): Promise<void> {
  if (!expForm.template_a_id || !expForm.template_b_id) {
    ElMessage.warning('请选择两个模板')
    return
  }
  experimenting.value = true
  try {
    await promptApi.createExperiment({
      name: expForm.name.trim() || `A/B ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
      template_a_id: expForm.template_a_id,
      template_b_id: expForm.template_b_id,
      input_text: expForm.input_text,
      variables: { ...expForm.variables },
    })
    ElMessage.success('实验已完成')
    expVisible.value = false
    await reloadAll()
  } finally {
    experimenting.value = false
  }
}

function openScore(experiment: PromptExperiment): void {
  scoring.value = experiment
  scoreForm.a = experiment.score_a || 0
  scoreForm.b = experiment.score_b || 0
  scoreForm.notes = experiment.notes || ''
  scoreVisible.value = true
}

async function submitScore(): Promise<void> {
  if (!scoring.value) return
  scoringBusy.value = true
  try {
    await promptApi.scoreExperiment(scoring.value.id, {
      score_a: scoreForm.a || null,
      score_b: scoreForm.b || null,
      notes: scoreForm.notes,
    })
    ElMessage.success('打分已保存')
    scoreVisible.value = false
    await reloadAll()
  } finally {
    scoringBusy.value = false
  }
}

onMounted(reloadAll)
</script>

<style scoped>
.card-title {
  margin-bottom: 12px;
  font-size: 15px;
  font-weight: 600;
}

.small {
  font-size: 11px;
}

.var-tag {
  margin: 2px 4px 2px 0;
}

.preview-text {
  font-size: 12px;
}

.experiments-card {
  margin-top: 14px;
}

.panel-label {
  margin: 8px 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}

.render-alert {
  margin-bottom: 8px;
}

.render-output,
.score-output {
  max-height: 300px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
