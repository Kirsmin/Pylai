<script setup lang="ts">
import Dock from '@/components/Dock.vue'
</script>

<template>
  <div class="home-container">
    <div class="home-wrapper">
      <NCard class="home-card" :bordered="false" hoverable>
        <div class="home-content">
          <NH1 class="home-title">
            Pylai
          </NH1>

          <NText depth="1" class="home-subtitle">
            Fajro's 控制面板
          </NText>
        </div>
      </NCard>
      <Dock />
    </div>
  </div>
</template>

<style scoped>
.home-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  background: var(--page-bg);
}

.home-wrapper {
  width: min(92%, 520px);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.home-card {
  --n-color: var(--card-bg);
  --n-border-color: var(--card-border);
  --n-box-shadow: var(--card-shadow);
  width: 100%;
  border-radius: 16px;
  background-color: var(--card-bg);
  backdrop-filter: blur(24px) saturate(1.1);
  -webkit-backdrop-filter: blur(24px) saturate(1.1);
  border: 1px solid var(--card-border);
  box-shadow: var(--card-shadow);
  transition: box-shadow 0.3s ease;
}

.home-card:hover {
  box-shadow: var(--card-shadow-hover);
}

.home-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 32px 16px;
  text-align: center;
}

.home-title {
  margin: 0;
  font-weight: 600;
  font-size: 32px;
  color: var(--text-primary);
}

.home-subtitle {
  font-size: 16px;
  line-height: 1.6;
}

@media (max-width: 640px) {
  .home-container {
    padding: 16px;
  }

  .home-title {
    font-size: 24px;
  }

  .home-subtitle {
    font-size: 14px;
  }

  .home-content {
    padding: 24px 8px;
  }
}
</style>
