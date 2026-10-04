<script setup lang="ts">
import { ArrowRight, Eye, EyeOff, LoaderCircle, Sparkles } from "lucide-vue-next";
import { computed, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "../stores/auth";

const props = defineProps<{ readonly mode: "login" | "register" }>();
const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const form = reactive({ displayName: "", email: "", password: "" });
const passwordVisible = ref(false);
const isLogin = computed(() => props.mode === "login");
const heading = computed(() => (isLogin.value ? "欢迎回来" : "创建你的工作台"));
const submitLabel = computed(() => (isLogin.value ? "登录" : "注册并进入"));
const alternatePath = computed(() => (isLogin.value ? "/register" : "/login"));
const alternateLabel = computed(() => (isLogin.value ? "还没有账号？创建工作台" : "已有账号？直接登录"));

function intendedPath(): string {
  const redirect = route.query.redirect;
  return typeof redirect === "string" && redirect.startsWith("/") ? redirect : "/chat";
}

async function submit(): Promise<void> {
  try {
    if (isLogin.value) {
      await auth.login({ email: form.email, password: form.password });
    } else {
      await auth.register({
        displayName: form.displayName,
        email: form.email,
        password: form.password
      });
    }
    await router.replace(intendedPath());
  } catch {
    // The auth store publishes the normalized API error to global feedback.
  }
}
</script>

<template>
  <main class="auth-view">
    <section class="auth-view__panel" :aria-labelledby="`${mode}-title`">
      <RouterLink class="auth-view__brand" to="/login">
        <Sparkles :size="20" aria-hidden="true" />
        <span>Super AI</span>
      </RouterLink>
      <div class="auth-view__intro">
        <p>运维智能工作台</p>
        <h1 :id="`${mode}-title`">{{ heading }}</h1>
        <span>{{ isLogin ? "继续你的对话、知识与诊断工作。" : "用一个账号管理你的对话、知识与诊断记录。" }}</span>
      </div>
      <form class="auth-view__form" @submit.prevent="submit">
        <label v-if="!isLogin">
          <span>昵称</span>
          <input v-model.trim="form.displayName" autocomplete="name" required />
        </label>
        <label>
          <span>邮箱</span>
          <input v-model.trim="form.email" autocomplete="email" inputmode="email" type="email" required />
        </label>
        <label>
          <span>密码</span>
          <span class="auth-view__password"><input v-model="form.password" :autocomplete="isLogin ? 'current-password' : 'new-password'" minlength="8" :type="passwordVisible ? 'text' : 'password'" required /><button type="button" :aria-label="passwordVisible ? '隐藏密码' : '显示密码'" :title="passwordVisible ? '隐藏密码' : '显示密码'" @click="passwordVisible = !passwordVisible"><EyeOff v-if="passwordVisible" :size="17" aria-hidden="true" /><Eye v-else :size="17" aria-hidden="true" /></button></span>
        </label>
        <button class="auth-view__submit" type="submit" :disabled="auth.isLoading">
          <span>{{ auth.isLoading ? (isLogin ? "正在登录" : "正在创建") : submitLabel }}</span>
          <LoaderCircle v-if="auth.isLoading" class="auth-view__spin" :size="17" aria-hidden="true" /><ArrowRight v-else :size="17" aria-hidden="true" />
        </button>
      </form>
      <RouterLink class="auth-view__alternate" :to="alternatePath">{{ alternateLabel }}</RouterLink>
    </section>
  </main>
</template>

<style scoped>
.auth-view { align-items: center; background: var(--canvas); display: grid; min-height: 100vh; padding: 1.25rem; }
.auth-view__panel { background: var(--surface-raised); border: 1px solid var(--line); border-radius: var(--radius-lg); box-shadow: var(--shadow-float); margin: 0 auto; max-width: 29rem; padding: clamp(1.5rem, 5vw, 2.75rem); width: 100%; }
.auth-view__brand { align-items: center; color: var(--text-primary); display: inline-flex; font-size: 0.96rem; font-weight: 720; gap: 0.58rem; text-decoration: none; }
.auth-view__brand svg { color: var(--accent); }
.auth-view__intro { margin: 2.75rem 0 1.85rem; }
.auth-view__intro p { color: var(--accent-strong); font-size: 0.74rem; font-weight: 700; letter-spacing: 0.04em; margin: 0 0 0.5rem; }
.auth-view__intro h1 { font-size: clamp(1.65rem, 5vw, 2.1rem); font-weight: 720; letter-spacing: 0; margin: 0; }
.auth-view__intro > span { color: var(--text-secondary); display: block; font-size: 0.88rem; line-height: 1.65; margin-top: 0.75rem; }
.auth-view__form { display: grid; gap: 1rem; }
label { color: var(--text-secondary); display: grid; font-size: 0.82rem; font-weight: 650; gap: 0.46rem; }
input { background: #fff; border: 1px solid var(--line-strong); border-radius: var(--radius-sm); color: var(--text-primary); font: inherit; min-height: 2.9rem; padding: 0 0.82rem; width: 100%; }
input:focus { border-color: var(--accent); outline: 3px solid var(--accent-focus); outline-offset: 1px; }
.auth-view__password { display: block; position: relative; }
.auth-view__password input { padding-right: 2.85rem; }
.auth-view__password button { align-items: center; border-radius: 0.4rem; color: var(--text-tertiary); display: inline-flex; height: 2.35rem; justify-content: center; position: absolute; right: 0.25rem; top: 0.25rem; width: 2.35rem; }
.auth-view__password button:hover { background: var(--surface-hover); color: var(--text-primary); }
.auth-view__submit { align-items: center; background: var(--accent); border-radius: var(--radius-sm); color: white; display: flex; font-weight: 670; justify-content: space-between; margin-top: 0.35rem; min-height: 3rem; padding: 0 0.95rem; transition: background var(--transition-fast), transform var(--transition-fast); }
.auth-view__submit:hover:not(:disabled) { background: var(--accent-strong); transform: translateY(-1px); }
.auth-view__submit:disabled { cursor: wait; opacity: 0.72; }
.auth-view__spin { animation: auth-spin 0.8s linear infinite; }
.auth-view__alternate { color: var(--accent-strong); display: inline-block; font-size: 0.85rem; font-weight: 600; margin-top: 1.5rem; text-decoration: none; }
@keyframes auth-spin { to { transform: rotate(360deg); } }
</style>
