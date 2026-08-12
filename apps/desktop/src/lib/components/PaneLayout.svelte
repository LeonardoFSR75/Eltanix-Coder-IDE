<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    left,
    right,
    bottom
  } = $props<{
    left?: Snippet;
    right?: Snippet;
    bottom?: Snippet;
  }>();
</script>

<div class="pane-container">
  <div class="main-split">
    <div class="left-pane">
      {@render left?.()}
    </div>
    <div class="right-pane">
      {@render right?.()}
    </div>
  </div>
  {#if bottom}
    <div class="bottom-pane">
      {@render bottom()}
    </div>
  {/if}
</div>

<style>
  .pane-container {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
  .main-split {
    display: flex;
    flex: 1;
    height: 65%;
    width: 100%;
    overflow: hidden;
  }
  .left-pane {
    flex: 1;
    height: 100%;
    overflow: hidden;
  }
  .right-pane {
    width: 380px;
    height: 100%;
    overflow: hidden;
  }
  .bottom-pane {
    height: 35%;
    width: 100%;
    overflow: hidden;
  }
</style>
