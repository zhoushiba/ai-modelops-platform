<template>
  <div v-if="loading" class="state-block">
    <el-skeleton :rows="rows" animated />
    <div class="state-hint">正在加载数据…</div>
  </div>
  <div v-else-if="error" class="state-block">
    <el-result icon="error" title="加载失败" :sub-title="error">
      <template #extra>
        <el-button type="primary" @click="$emit('retry')">重新加载</el-button>
      </template>
    </el-result>
  </div>
  <slot v-else />
</template>

<script setup lang="ts">
withDefaults(defineProps<{ loading?: boolean; error?: string; rows?: number }>(), {
  loading: false,
  error: '',
  rows: 6,
})

defineEmits<{ retry: [] }>()
</script>

<style scoped>
.state-hint {
  margin-top: 16px;
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
}
</style>
