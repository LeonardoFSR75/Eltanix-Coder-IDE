<script lang="ts">
  import { onMount } from "svelte";
  import TopMenuBar from "./lib/components/TopMenuBar.svelte";
  import FileExplorer from "./lib/components/FileExplorer.svelte";
  import TabStrip, { type TabItem } from "./lib/components/TabStrip.svelte";
  import GitPanel from "./lib/components/GitPanel.svelte";
  import SearchPanel from "./lib/components/SearchPanel.svelte";
  import QuickOpen from "./lib/components/QuickOpen.svelte";
  import CommandPalette, { type Command } from "./lib/components/CommandPalette.svelte";
  import Editor from "./lib/components/Editor.svelte";
  import InlineDiffApprovalBar from "./lib/components/InlineDiffApprovalBar.svelte";
  import Terminal from "./lib/components/Terminal.svelte";
  import AgentDock from "./lib/components/AgentDock.svelte";
  import StatusBar from "./lib/components/StatusBar.svelte";
  import ProjectModal from "./lib/components/ProjectModal.svelte";
  import LoginModal from "./lib/components/LoginModal.svelte";
  import { readFile, writeFile } from "./lib/api/workspace";
  import { listProjects, getProjectSummary, type ProjectRecord } from "./lib/api/projects";
  import { hasAuthToken, onUnauthorized } from "./lib/client";

  const STORAGE_KEY = "eltanix_current_project";

  let currentProject = $state("eltanix-code");
  let projects = $state<{ slug: string; name: string }[]>([]);
  let profile = $state("auto");

  let activeBranch = $state("main");
  let activeCost = $state("$0.0000");

  let showSidebar = $state(true);
  let showTerminal = $state(true);
  let showAgent = $state(true);
  let isProjectModalOpen = $state(false);
  let isLoginModalOpen = $state(!hasAuthToken());
  let sidebarView = $state<"explorer" | "git" | "search">("explorer");
  let showQuickOpen = $state(false);
  let showCommandPalette = $state(false);

  let openTabs = $state<TabItem[]>([
    { path: "apps/desktop/src/App.svelte", name: "App.svelte", isDirty: false },
  ]);
  let activeTabPath = $state("apps/desktop/src/App.svelte");
  let fileContents = $state<Record<string, string>>({
    "apps/desktop/src/App.svelte": `<!-- Eltanix Coder IDE Lite — Svelte 5 Agentic IDE -->\n<script lang="ts">\n  console.log("Eltanix Coder IDE Lite pronto!");\n<\/script>`,
  });

  let pendingAgentDiff = $state<{
    sessionId: string;
    path: string;
    beforeContent: string;
    existed: boolean;
  } | null>(null);

  let activeCode = $derived(fileContents[activeTabPath] ?? "// Carregando...");

  let editorRef: { notifySaved: () => void } | null = $state(null);
  let revealTarget = $state<{ line: number; column: number } | null>(null);

  async function handleNavigate(path: string, line: number, column: number) {
    await handleOpenPath(path);
    // Reatribuir (não mutar) para o `$effect` do Editor perceber a mudança
    // mesmo quando o destino é a mesma linha/coluna de uma navegação anterior.
    revealTarget = null;
    await Promise.resolve();
    revealTarget = { line, column };
  }

  function getLanguageFromPath(path: string): string {
    if (path.endsWith(".ts")) return "typescript";
    if (path.endsWith(".js")) return "javascript";
    if (path.endsWith(".svelte")) return "html";
    if (path.endsWith(".json")) return "json";
    if (path.endsWith(".py")) return "python";
    if (path.endsWith(".md")) return "markdown";
    if (path.endsWith(".css")) return "css";
    return "plaintext";
  }

  async function loadProjectSummary(slug: string) {
    const summary = await getProjectSummary(slug);
    if (summary) {
      if (summary.branch) activeBranch = summary.branch;
      if (summary.total_cost_usd !== undefined) {
        activeCost = `$${summary.total_cost_usd.toFixed(4)}`;
      }
    }
  }

  async function refreshProjects() {
    const stored = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    const projs = await listProjects();
    if (projs && projs.length > 0) {
      projects = projs.map((p) => ({ slug: p.slug, name: p.name }));
      if (stored && projs.some((p) => p.slug === stored)) {
        currentProject = stored;
      } else {
        currentProject = projs[0].slug;
      }
    }
  }

  function handleProjectChange(slug: string) {
    currentProject = slug;
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, slug);
    }
    loadProjectSummary(slug);
  }

  function handleProjectCreated(created: ProjectRecord) {
    refreshProjects().then(() => {
      handleProjectChange(created.slug);
    });
  }


  async function handleOpenPath(path: string) {
    const fileName = path.split("/").pop() || path;
    const existing = openTabs.find((t) => t.path === path);
    if (!existing) {
      openTabs = [...openTabs, { path, name: fileName, isDirty: false }];
    }
    activeTabPath = path;

    if (fileContents[path] === undefined) {
      try {
        const fileData = await readFile(currentProject, path);
        fileContents[path] = fileData.content;
      } catch {
        fileContents[path] = `// Erro ao carregar arquivo: ${path}`;
      }
    }
  }

  function handleCloseTab(path: string) {
    openTabs = openTabs.filter((t) => t.path !== path);
    if (activeTabPath === path && openTabs.length > 0) {
      activeTabPath = openTabs[openTabs.length - 1].path;
    }
  }

  function handleCodeChange(newCode: string) {
    fileContents[activeTabPath] = newCode;
    openTabs = openTabs.map((t) => (t.path === activeTabPath ? { ...t, isDirty: true } : t));
  }

  function handleInsertCodeSnippet(snippet: string) {
    const currentText = fileContents[activeTabPath] || "";
    const updatedText = currentText ? `${currentText}\n\n${snippet}` : snippet;
    fileContents[activeTabPath] = updatedText;
    openTabs = openTabs.map((t) => (t.path === activeTabPath ? { ...t, isDirty: true } : t));
  }

  async function handleSaveFile() {
    if (!activeTabPath) return;
    const contentToSave = fileContents[activeTabPath] ?? "";
    try {
      await writeFile(currentProject, activeTabPath, contentToSave);
      openTabs = openTabs.map((t) => (t.path === activeTabPath ? { ...t, isDirty: false } : t));
      editorRef?.notifySaved();
    } catch (err: any) {
      alert(`Erro ao salvar arquivo: ${err.message || err}`);
    }
  }

  let commands = $derived.by((): Command[] => [
    { id: "save", title: "Salvar arquivo ativo", shortcut: "Ctrl+S", run: handleSaveFile },
    { id: "toggle-sidebar", title: "Alternar barra lateral", shortcut: "Ctrl+B", run: () => (showSidebar = !showSidebar) },
    { id: "toggle-terminal", title: "Alternar terminal", run: () => (showTerminal = !showTerminal) },
    { id: "toggle-agent", title: "Alternar painel do agente", run: () => (showAgent = !showAgent) },
    { id: "view-explorer", title: "Ir para: Explorador", run: () => { showSidebar = true; sidebarView = "explorer"; } },
    { id: "view-git", title: "Ir para: Git", run: () => { showSidebar = true; sidebarView = "git"; } },
    { id: "view-search", title: "Ir para: Busca", run: () => { showSidebar = true; sidebarView = "search"; } },
    { id: "quick-open", title: "Abrir arquivo por nome…", shortcut: "Ctrl+P", run: () => (showQuickOpen = true) },
    { id: "new-project", title: "Criar / vincular novo projeto…", run: () => (isProjectModalOpen = true) },
    { id: "user-login", title: "Entrar / Autenticação de usuário…", run: () => (isLoginModalOpen = true) },
  ]);

  onMount(() => {
    onUnauthorized(() => {
      isLoginModalOpen = true;
    });

    refreshProjects();
    loadProjectSummary(currentProject);

    const handleKeyDown = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (showQuickOpen || showCommandPalette) return;
      if (mod && e.shiftKey && e.key.toLowerCase() === "p") {
        e.preventDefault();
        showCommandPalette = true;
      } else if (mod && e.key.toLowerCase() === "p") {
        e.preventDefault();
        showQuickOpen = true;
      } else if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        handleSaveFile();
      } else if (mod && e.key.toLowerCase() === "b") {
        e.preventDefault();
        showSidebar = !showSidebar;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });
</script>

<div class="lite-shell">
  <TopMenuBar
    project={currentProject}
    {projects}
    {profile}
    {showSidebar}
    {showTerminal}
    {showAgent}
    onProjectChange={handleProjectChange}
    onProfileChange={(prof) => (profile = prof)}
    onToggleSidebar={() => (showSidebar = !showSidebar)}
    onToggleTerminal={() => (showTerminal = !showTerminal)}
    onToggleAgent={() => (showAgent = !showAgent)}
    onSaveFile={handleSaveFile}
    onOpenProjectModal={() => (isProjectModalOpen = true)}
    onOpenLoginModal={() => (isLoginModalOpen = true)}
  />

  <ProjectModal
    isOpen={isProjectModalOpen}
    onClose={() => (isProjectModalOpen = false)}
    onProjectCreated={handleProjectCreated}
  />

  <LoginModal
    isOpen={isLoginModalOpen}
    dismissible={hasAuthToken()}
    onSaved={() => {
      isLoginModalOpen = false;
      refreshProjects();
    }}
  />

  <div class="workspace-body">
    {#if showSidebar}
      <div class="sidebar-wrap">
        <div class="sidebar-tabs">
          <button
            class="sidebar-tab {sidebarView === 'explorer' ? 'active' : ''}"
            onclick={() => (sidebarView = "explorer")}
          >
            📁 Explorador
          </button>
          <button
            class="sidebar-tab {sidebarView === 'git' ? 'active' : ''}"
            onclick={() => (sidebarView = "git")}
          >
            🌿 Git
          </button>
          <button
            class="sidebar-tab {sidebarView === 'search' ? 'active' : ''}"
            onclick={() => (sidebarView = "search")}
          >
            🔍 Busca
          </button>
        </div>
        <div class="sidebar-panel-slot">
          {#if sidebarView === "explorer"}
            <FileExplorer
              project={currentProject}
              activeFilePath={activeTabPath}
              onSelectFile={handleOpenPath}
            />
          {:else if sidebarView === "git"}
            <GitPanel project={currentProject} onOpenFile={handleOpenPath} />
          {:else}
            <SearchPanel project={currentProject} onOpenMatch={handleNavigate} />
          {/if}
        </div>
      </div>
    {/if}

    <div class="editor-area">
      <TabStrip
        tabs={openTabs}
        activePath={activeTabPath}
        onSelectTab={(path) => (activeTabPath = path)}
        onCloseTab={handleCloseTab}
      />

      {#if pendingAgentDiff}
        <InlineDiffApprovalBar
          sessionId={pendingAgentDiff.sessionId}
          path={pendingAgentDiff.path}
          beforeContent={pendingAgentDiff.beforeContent}
          existed={pendingAgentDiff.existed}
          onResolved={() => (pendingAgentDiff = null)}
        />
      {/if}

      <div class="editor-terminal-split">
        <div class="editor-container">
          <Editor
            bind:this={editorRef}
            value={activeCode}
            language={getLanguageFromPath(activeTabPath)}
            path={activeTabPath}
            project={currentProject}
            {revealTarget}
            onchange={handleCodeChange}
            onNavigate={handleNavigate}
          />
        </div>

        {#if showTerminal}
          <div class="terminal-container">
            <Terminal />
          </div>
        {/if}
      </div>
    </div>

    {#if showAgent}
      <div class="agent-side-panel">
        <AgentDock
          project={currentProject}
          activeFile={activeTabPath}
          onInsertCode={handleInsertCodeSnippet}
        />
      </div>
    {/if}
  </div>

  <StatusBar branch={activeBranch} model={`Router (${profile})`} cost={activeCost} />

  {#if showQuickOpen}
    <QuickOpen
      project={currentProject}
      onOpenFile={handleOpenPath}
      onClose={() => (showQuickOpen = false)}
    />
  {/if}

  {#if showCommandPalette}
    <CommandPalette {commands} onClose={() => (showCommandPalette = false)} />
  {/if}
</div>

<style>
  .lite-shell {
    display: flex;
    flex-direction: column;
    width: 100vw;
    height: 100vh;
    overflow: hidden;
    background-color: var(--bg-dark);
  }
  .sidebar-wrap {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .sidebar-tabs {
    display: flex;
    flex-shrink: 0;
    background-color: var(--bg-dark);
    border-bottom: 1px solid var(--border-color);
  }
  .sidebar-tab {
    flex: 1;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--text-muted);
    padding: 6px 4px;
    font-size: 0.7rem;
    cursor: pointer;
  }
  .sidebar-tab:hover {
    color: var(--text-main);
  }
  .sidebar-tab.active {
    color: var(--accent-cyan);
    border-bottom-color: var(--accent-cyan);
  }
  .sidebar-panel-slot {
    flex: 1;
    min-height: 0;
    display: flex;
  }
  .workspace-body {
    display: flex;
    flex: 1;
    height: calc(100vh - 60px);
    width: 100%;
    overflow: hidden;
  }
  .editor-area {
    display: flex;
    flex-direction: column;
    flex: 1;
    height: 100%;
    overflow: hidden;
  }
  .editor-terminal-split {
    display: flex;
    flex-direction: column;
    flex: 1;
    height: calc(100% - 32px);
    overflow: hidden;
  }
  .editor-container {
    flex: 1;
    height: 65%;
    width: 100%;
    overflow: hidden;
  }
  .terminal-container {
    height: 35%;
    width: 100%;
    overflow: hidden;
  }
  .agent-side-panel {
    width: 380px;
    height: 100%;
    overflow: hidden;
  }
</style>
