/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 演示模式：构建时置为 '1'，首屏自动用默认账号登录（仅供截图/内网演示） */
  readonly VITE_DEMO_AUTO_LOGIN?: string
  readonly VITE_DEMO_USERNAME?: string
  readonly VITE_DEMO_PASSWORD?: string
  /** 在线推理调试台的预填 API Key（演示用，留空则手工粘贴） */
  readonly VITE_DEMO_API_KEY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'

  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}
