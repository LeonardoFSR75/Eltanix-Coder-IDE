<script lang="ts">
  let { branch = "main", model = "Ollama (local)", cost = "$0.0000" } = $props<{
    branch?: string;
    model?: string;
    cost?: string;
  }>();
</script>

<footer class="status-bar">
  <div class="left-section">
    <span class="item">🌿 {branch}</span>
    <span class="item">🤖 {model}</span>
  </div>
  <div class="right-section">
    <span class="item">💰 Custo: {cost}</span>
    <span class="item">UTF-8</span>
    <span class="item">Svelte 5 Desktop</span>
  </div>
</footer>

<style>
  .status-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 22px;
    background-color: #0284c7;
    color: white;
    font-size: 0.7rem;
    padding: 0 8px;
    user-select: none;
  }
  .left-section, .right-section {
    display: flex;
    gap: 12px;
  }
  .item {
    display: flex;
    align-items: center;
  }
</style>
