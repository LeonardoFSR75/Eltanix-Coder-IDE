---
name: vue-ui-components
description: Guia e convenções para desenvolvimento de interfaces, layouts e componentes reativos utilizando Vue.js (via CDN ou SPA com Vite/Node) no ecossistema Eltanix Coder IDE.
category: frontend
---

# Vue.js UI & Layout Components - Eltanix Coder IDE

Este guia orienta o desenvolvimento e montagem de layouts com Vue.js de forma autônoma e sem necessidade de conexão com a internet externa.

## 1. Modos de Uso Suportados

### A. Modo CDN Reativo (Ideal para Flask, Django, FastAPI ou HTML Estático)
Integre o Vue 3 diretamente no `index.html` ou template Jinja/HTML através do script global ou bundle local:

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Aplicação Reativa</title>
  <!-- Vue 3 Global Build -->
  <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
  <!-- Tailwind ou CSS local -->
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen">
  <div id="app" class="max-w-4xl mx-auto p-6">
    <header class="mb-8 border-b border-slate-800 pb-4 flex justify-between items-center">
      <h1 class="text-2xl font-bold text-emerald-400">{{ titulo }}</h1>
      <button @click="executarAcao" class="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg transition-all shadow-md">
        {{ botaoTexto }}
      </button>
    </header>

    <main class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <section class="bg-slate-800/80 p-5 rounded-xl border border-slate-700 shadow-xl">
        <h2 class="text-lg font-semibold mb-3 text-slate-200">Painel de Controle</h2>
        <input v-model="novoItem" @keyup.enter="adicionar" placeholder="Digite um valor..." class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-white mb-3 focus:outline-none focus:border-emerald-500" />
        <ul class="divide-y divide-slate-700/50">
          <li v-for="(item, idx) in lista" :key="idx" class="py-2 flex justify-between items-center">
            <span>{{ item }}</span>
            <button @click="remover(idx)" class="text-rose-400 hover:text-rose-300 text-sm">Remover</button>
          </li>
        </ul>
      </section>
    </main>
  </div>

  <script>
    const { createApp, ref } = Vue;
    createApp({
      setup() {
        const titulo = ref("Sorteador & Painel Reativo");
        const botaoTexto = ref("Sortear Agora 🎲");
        const lista = ref(["Item 1", "Item 2", "Item 3"]);
        const novoItem = ref("");

        const adicionar = () => {
          if (novoItem.value.trim()) {
            lista.value.push(novoItem.value.trim());
            novoItem.value = "";
          }
        };

        const remover = (idx) => {
          lista.value.splice(idx, 1);
        };

        const executarAcao = async () => {
          // Comunicação com rotas do backend (ex: Flask /api/sortear)
          const resp = await fetch('/api/sortear', { method: 'POST' });
          const data = await resp.json();
          alert(`Sorteado: ${data.resultado}`);
        };

        return { titulo, botaoTexto, lista, novoItem, adicionar, remover, executarAcao };
      }
    }).mount('#app');
  </script>
</body>
</html>
```

### B. Modo Node / Vite (SPA Completa)
Se o projeto for puramente JavaScript/TypeScript:
- Estrutura com `src/App.vue`, `src/main.js` e componentes em `src/components/`.
- Inicie o servidor via `run_command(command='npm run dev')` ou `run_command(command='npx vite')`.
- Inspecione a UI via `browser_action(action='navigate', url='http://localhost:5173')`.

---

## 2. Boas Práticas do Agente
1. Nunca busque documentação externa na internet: use as convenções do Composition API (`ref`, `reactive`, `computed`, `onMounted`) diretamente no código.
2. Ao terminar a edição, inicie o servidor com `run_command` e valide a interface com `browser_action`.
