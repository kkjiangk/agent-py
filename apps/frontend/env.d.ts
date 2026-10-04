/// <reference types="vite/client" />

declare module "virtual:agent-py-public-config" {
  export const apiBaseUrl: string;
}

declare module "*.vue" {
  import type { DefineComponent } from "vue";

  const component: DefineComponent<object, object, unknown>;
  export default component;
}
