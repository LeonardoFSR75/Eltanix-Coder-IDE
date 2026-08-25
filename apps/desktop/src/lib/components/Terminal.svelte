<script lang="ts">
  import { onMount } from "svelte";
  import { Terminal } from "@xterm/xterm";
  import { FitAddon } from "@xterm/addon-fit";
  import "@xterm/xterm/css/xterm.css";

  let containerEl: HTMLDivElement;
  let term: Terminal;
  let fitAddon: FitAddon;

  onMount(() => {
    if (!containerEl) return;

    term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'Consolas, Monaco, "Courier New", monospace',
      theme: {
        background: "#0f172a",
        foreground: "#f8fafc",
        cursor: "#06b6d4",
      },
    });

    fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerEl);
    fitAddon.fit();

    term.writeln("\x1b[1;32mEltanix Coder IDE Terminal (Desktop Svelte 5)\x1b[0m");
    term.writeln("Conectado ao executor Docker e sandbox efêmera.");
    term.write("\r\n$ ");

    term.onData((data) => {
      // Echo básico de desenvolvimento
      if (data === "\r") {
        term.write("\r\n$ ");
      } else if (data === "\u007F") {
        term.write("\b \b");
      } else {
        term.write(data);
      }
    });

    const handleResize = () => fitAddon.fit();
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      term.dispose();
    };
  });
</script>

<div class="terminal-wrapper">
  <div class="terminal-bar">Terminal</div>
  <div bind:this={containerEl} class="xterm-container"></div>
</div>

<style>
  .terminal-wrapper {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    background-color: #0f172a;
    border-top: 1px solid var(--border-color);
  }
  .terminal-bar {
    height: 24px;
    padding: 0 12px;
    background-color: var(--bg-panel);
    color: var(--text-muted);
    font-size: 0.75rem;
    display: flex;
    align-items: center;
  }
  .xterm-container {
    flex: 1;
    padding: 8px;
    width: 100%;
    height: calc(100% - 24px);
    overflow: hidden;
  }
</style>
