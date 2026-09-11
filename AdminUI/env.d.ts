/// <reference types="vite/client" />

/** 由 Vite 从 AdminUI/package.json 注入，避免 UI 内重复硬编码版本号。 */
declare const __APP_VERSION__: string
