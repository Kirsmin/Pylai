<script setup lang="ts">
import { NCard, NSpace, NH1, NH2, NH3, NText, NTag } from 'naive-ui'
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="about-container">
    <NCard class="about-card" :bordered="false" hoverable>
      <a class="back-button" @click="router.push('/')">
        ← 返回
      </a>
      <div class="about-content">
        <NH1 class="about-title">Pylai</NH1>

        <NSpace vertical size="large" class="about-text">
          <NText depth="1">Pylai 项目由 KirsminX 维护与开发</NText>
        </NSpace>
      <div class="about-protocol">
        <NH2>开源许可</NH2>

        <div class="license-item">
          <NSpace align="center">
            <span class="project-name">Pylaiui</span>
            <a href="https://opensource.org/licenses/MIT" target="_blank" rel="noopener">
              <NTag type="info" size="small">MIT</NTag>
            </a>
          </NSpace>
          <p>基于 Vue 3 的 UI 组件库。</p>
        </div>

        <div class="license-item">
          <NSpace align="center">
            <span class="project-name">Pylaios</span>
            <a href="https://opensource.org/licenses/MIT" target="_blank" rel="noopener">
              <NTag type="info" size="small">MIT</NTag>
            </a>
          </NSpace>
          <p>由 C# 开发的后端服务。</p>
        </div>

        <div class="license-item">
          <NSpace align="center">
            <span class="project-name">Vue</span>
            <a href="https://opensource.org/licenses/MIT" target="_blank" rel="noopener">
              <NTag type="info" size="small">MIT</NTag>
            </a>
          </NSpace>
          <p>渐进式 JavaScript 框架。</p>
        </div>

        <div class="license-item">
          <NSpace align="center">
            <span class="project-name">Naive UI</span>
            <a href="https://opensource.org/licenses/MIT" target="_blank" rel="noopener">
              <NTag type="info" size="small">MIT</NTag>
            </a>
          </NSpace>
          <p>可变主题的 Vue 3 组件库。</p>
        </div>

        <div class="license-item">
          <NSpace align="center">
            <span class="project-name">Maple Mono</span>
            <a href="https://openfontlicense.org" target="_blank" rel="noopener">
              <NTag type="success" size="small">OFL</NTag>
            </a>
          </NSpace>
          <p>支持连字的开源等宽字体。</p>
        </div>

        <div class="license-item">
          <NSpace align="center">
            <span class="project-name">HarmonyOS Sans</span>
            <a href="/about/licenses/harmonyos_sans.txt" target="_blank" rel="noopener">
              <NTag type="error" size="small">HarmonyOS</NTag>
            </a>
          </NSpace>
          <p>华为开源多语言中文字体。</p>
        </div>
      </div>
      </div>
    </NCard>
  </div>
</template>

<style scoped>
.about-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  background: var(--page-bg);
}

.about-card {
  --n-color: var(--card-bg);
  --n-border-color: var(--card-border);
  --n-box-shadow: var(--card-shadow);
  width: min(92%, 800px);
  border-radius: 16px;
  background-color: var(--card-bg);
  backdrop-filter: blur(24px) saturate(1.1);
  -webkit-backdrop-filter: blur(24px) saturate(1.1);
  border: 1px solid var(--card-border);
  box-shadow: var(--card-shadow);
  transition: box-shadow 0.3s ease;
  position: relative;
}

.back-button {
  position: absolute;
  top: 16px;
  left: 16px;
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  text-decoration: none;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: color 0.2s;
}

.back-button:hover {
  color: var(--text-primary);
}

.about-card:hover {
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.12);
}

.about-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
  padding: 40px 24px;
  text-align: center;
}

.about-title {
  margin: 0;
  font-weight: 600;
  font-size: 32px;
  color: var(--text-primary);
}

.about-text {
  width: 100%;
  font-size: 16px;
  line-height: 1.8;
}

.about-protocol {
  width: 100%;
  text-align: left;
  font-size: 16px;
}

.about-protocol :deep(h2) {
  font-size: 22px;
  margin-top: 0;
  margin-bottom: 16px;
  color: var(--text-primary);
}

.license-item {
  margin-bottom: 16px;
}

.license-item .project-name {
  font-weight: 600;
  font-size: 16px;
  color: var(--text-primary);
}

.license-item p {
  margin: 6px 0 0 0;
  font-size: 14px;
  color: var(--text-secondary);
}

.license-item a {
  text-decoration: none;
}

.license-item a:hover {
  opacity: 0.8;
}

@media (max-width: 640px) {
  .about-container {
    padding: 16px;
  }

  .about-card {
    max-width: 100%;
    border-radius: 8px;
  }

  .about-content {
    gap: 16px;
    padding: 24px 16px;
  }

  .about-title {
    font-size: 24px;
  }
}
</style>
