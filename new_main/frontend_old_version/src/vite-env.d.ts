/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API 서버 오리진 (끝 슬래시 없음). 비우면 현재 오리진 */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
