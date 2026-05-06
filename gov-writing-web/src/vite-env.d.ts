/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_USE_LEGACY_AUTH_HEADER?: string;
  readonly VITE_LEGACY_USER_ID?: string;
  readonly VITE_LEGACY_ACCOUNT?: string;
  readonly VITE_LEGACY_NAME?: string;
  readonly VITE_LEGACY_ORG_NAME?: string;
  readonly VITE_LEGACY_ORG_CODE?: string;
  readonly VITE_BSP_APP_CODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}