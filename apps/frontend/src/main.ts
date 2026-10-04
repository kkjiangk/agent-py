import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import { createAppRouter } from "./router";
import { createAuthRouteAccess, useAuthStore } from "./stores/auth";
import "./styles.css";

const app = createApp(App);
const pinia = createPinia();
app.use(pinia);
app.use(createAppRouter(createAuthRouteAccess(useAuthStore(pinia))));
app.mount("#app");
