"""Ferramentas de Web do Agente via Firecrawl (Scrape, Search, Crawl & Ingest).

Permite ao agente consultar documentações online, artigos e referências na web
sem depender de abrir navegador local, retornando Markdown limpo e otimizado
para o modelo, além de indexar documentações inteiras no RAG do projeto.
"""

from __future__ import annotations

from typing import Any

from eltanix.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from eltanix.firecrawl.client import (
    FirecrawlAuthError,
    FirecrawlError,
    FirecrawlUnavailableError,
)
from eltanix.firecrawl.service import validate_target_url
from eltanix.logging_setup import get_logger

log = get_logger(__name__)

MAX_OUTPUT_CHARS = 24_000


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    metade = limit // 2
    omitido = len(text) - limit
    return f"{text[:metade]}\n\n... [{omitido} caracteres omitidos no meio] ...\n\n{text[-metade:]}"


@tool(
    name="web_scrape",
    description=(
        "Raspa uma página web usando o Firecrawl e retorna seu conteúdo formatado em "
        "Markdown limpo, com título e metadados. Use quando precisar consultar documentações "
        "online de bibliotecas, APIs, tutoriais técnicos, páginas do GitHub ou artigos."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL pública a ser raspada (deve começar com http:// ou https://)",
            },
            "only_main_content": {
                "type": "boolean",
                "description": (
                    "Se verdadeiro (padrão), remove cabeçalhos, rodapés e anúncios, mantendo "
                    "apenas o conteúdo principal"
                ),
            },
        },
        "required": ["url"],
    },
    summarize=lambda a: f"raspar página web: {a.get('url')!r}",
)
async def web_scrape(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.firecrawl is None:
        return ToolResult.failure(
            "Serviço Firecrawl indisponível — configure FIRECRAWL_API_KEY no .env "
            "ou nas configurações de Provedores."
        )

    url = str(args.get("url", "")).strip()
    if not url:
        return ToolResult.failure("Parâmetro 'url' é obrigatório.")

    try:
        validate_target_url(url)
    except ValueError as exc:
        return ToolResult.failure(f"URL inválida ou bloqueada: {exc}")

    only_main = bool(args.get("only_main_content", True))

    try:
        data = await ctx.firecrawl.scrape_url(url, only_main_content=only_main)
    except FirecrawlAuthError as exc:
        return ToolResult.failure(
            f"Falha de autenticação no Firecrawl: {exc}. Verifique a FIRECRAWL_API_KEY."
        )
    except FirecrawlUnavailableError as exc:
        return ToolResult.failure(f"Serviço Firecrawl inacessível: {exc}")
    except FirecrawlError as exc:
        return ToolResult.failure(f"Erro ao raspar a URL '{url}': {exc}")
    except Exception as exc:
        log.warning("tool.web_scrape.failed", url=url, error=str(exc))
        return ToolResult.failure(f"Erro inesperado no scraping: {exc}")

    markdown = data.get("markdown") or ""
    metadata = data.get("metadata") or {}
    title = metadata.get("title") or metadata.get("ogTitle") or url
    description = metadata.get("description") or ""

    if not markdown.strip():
        return ToolResult(
            ok=True,
            content=f"Página acessada ({title}), mas nenhum conteúdo em texto foi retornado.",
            data={"url": url, "metadata": metadata},
        )

    header = f"# {title}\n"
    if description:
        header += f"> {description}\n\n"
    header += f"**Fonte**: {url}\n\n---\n\n"

    final_content = _truncate(header + markdown)
    return ToolResult(
        ok=True,
        content=final_content,
        data={"url": url, "title": title, "metadata": metadata},
    )


@tool(
    name="web_search",
    description=(
        "Realiza busca na web e extrai o conteúdo limpo em Markdown dos resultados mais "
        "relevantes usando o Firecrawl. Use para pesquisar erros, bibliotecas, convenções de "
        "frameworks ou documentações recentes na internet."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Termo de busca ou pergunta técnica em linguagem natural",
            },
            "limit": {
                "type": "integer",
                "description": "Quantidade máxima de resultados a retornar (padrão 5)",
            },
        },
        "required": ["query"],
    },
    summarize=lambda a: f"buscar na web: {a.get('query')!r}",
)
async def web_search(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.firecrawl is None:
        return ToolResult.failure(
            "Serviço Firecrawl indisponível — configure FIRECRAWL_API_KEY no .env "
            "ou nas configurações de Provedores."
        )

    query = str(args.get("query", "")).strip()
    if not query:
        return ToolResult.failure("Parâmetro 'query' é obrigatório.")

    limit = int(args.get("limit", 5))

    try:
        results = await ctx.firecrawl.search(query, limit=limit)
    except FirecrawlAuthError as exc:
        return ToolResult.failure(
            f"Falha de autenticação no Firecrawl: {exc}. Verifique a FIRECRAWL_API_KEY."
        )
    except FirecrawlUnavailableError as exc:
        return ToolResult.failure(f"Serviço Firecrawl inacessível: {exc}")
    except FirecrawlError as exc:
        return ToolResult.failure(f"Erro na busca Firecrawl por '{query}': {exc}")
    except Exception as exc:
        log.warning("tool.web_search.failed", query=query, error=str(exc))
        return ToolResult.failure(f"Erro inesperado na busca: {exc}")

    if not results:
        return ToolResult(
            ok=True,
            content=f"Nenhum resultado encontrado para a busca: '{query}'.",
            data={"query": query, "results": []},
        )

    lines = [f"# Resultados da busca: '{query}'\n"]
    for i, res in enumerate(results, 1):
        r_title = res.get("title") or "Sem título"
        r_url = res.get("url") or ""
        r_desc = res.get("description") or ""
        r_md = res.get("markdown") or ""

        lines.append(f"## {i}. {r_title}")
        if r_url:
            lines.append(f"**Link**: {r_url}")
        if r_desc:
            lines.append(f"> {r_desc}")
        if r_md:
            # Resumo curto do conteúdo da página
            snippet = r_md[:500] + ("..." if len(r_md) > 500 else "")
            lines.append(f"\n```markdown\n{snippet}\n```")
        lines.append("\n---\n")

    final_content = _truncate("\n".join(lines))
    return ToolResult(
        ok=True,
        content=final_content,
        data={"results": results},
    )


@tool(
    name="crawl_and_index_docs",
    description=(
        "Rastreia (crawl) uma documentação web ou site e indexa automaticamente todas as páginas "
        "na base vetorial (RAG) do projeto atual. Use quando o usuário solicitar a importação de "
        "uma documentação inteira (ex.: docs do framework, especificações de APIs)."
    ),
    risk=RiskClass.WRITE,
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL base da documentação a ser rastreada",
            },
            "max_depth": {
                "type": "integer",
                "description": "Profundidade máxima de links a seguir (padrão 2)",
            },
            "limit": {
                "type": "integer",
                "description": "Limite máximo de páginas a rastrear e indexar (padrão 10)",
            },
        },
        "required": ["url"],
    },
    summarize=lambda a: f"rastrear e indexar documentação web: {a.get('url')!r}",
)
async def crawl_and_index_docs(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.firecrawl is None:
        return ToolResult.failure(
            "Serviço Firecrawl indisponível — configure FIRECRAWL_API_KEY no .env "
            "ou nas configurações de Provedores."
        )

    url = str(args.get("url", "")).strip()
    if not url:
        return ToolResult.failure("Parâmetro 'url' é obrigatório.")

    try:
        validate_target_url(url)
    except ValueError as exc:
        return ToolResult.failure(f"URL inválida ou bloqueada: {exc}")

    max_depth = int(args.get("max_depth", 2))
    limit = int(args.get("limit", 10))

    try:
        result = await ctx.firecrawl.crawl_and_ingest(
            url=url,
            project_slug=ctx.project_slug or None,
            max_depth=max_depth,
            limit=limit,
        )
    except FirecrawlAuthError as exc:
        return ToolResult.failure(
            f"Falha de autenticação no Firecrawl: {exc}. Verifique a FIRECRAWL_API_KEY."
        )
    except FirecrawlUnavailableError as exc:
        return ToolResult.failure(f"Serviço Firecrawl inacessível: {exc}")
    except FirecrawlError as exc:
        return ToolResult.failure(f"Erro no crawl de '{url}': {exc}")
    except Exception as exc:
        log.warning("tool.crawl_and_index_docs.failed", url=url, error=str(exc))
        return ToolResult.failure(f"Erro inesperado no rastreamento e indexação: {exc}")

    pages = result.get("pages_indexed", 0)
    chunks = result.get("total_chunks", 0)

    return ToolResult(
        ok=True,
        content=(
            f"✅ Rastreamento concluído com sucesso para {url}!\n"
            f"- **Páginas indexadas**: {pages}\n"
            f"- **Total de trechos (chunks) vetoriais**: {chunks}\n"
            "As páginas já estão disponíveis para consulta com `search_documents`."
        ),
        data=result,
    )


@tool(
    name="clone_web_ui",
    description=(
        "Analisa e extrai o layout visual, estrutura semântica, metadados de design e conteúdo "
        "de qualquer site ou landing page usando o Firecrawl para recriação como componentes "
        "React/Next.js modernos (inspirado em firecrawl/open-lovable). Retorna um Blueprint "
        "de UI arquitetural pronto para guiar a implementação de código no projeto."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL pública do site a ser clonado/recriado em React",
            },
            "target_framework": {
                "type": "string",
                "enum": ["react-tailwind", "react-css", "nextjs"],
                "description": "Framework e estilização alvo (padrão: react-tailwind)",
            },
            "component_scope": {
                "type": "string",
                "description": (
                    "Escopo da clonagem: 'full-page' (padrão), 'hero', 'navbar', 'pricing', "
                    "'features' ou 'form'"
                ),
            },
        },
        "required": ["url"],
    },
    summarize=lambda a: f"extrair blueprint de UI do site: {a.get('url')!r}",
)
async def clone_web_ui(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.firecrawl is None:
        return ToolResult.failure(
            "Serviço Firecrawl indisponível — configure FIRECRAWL_API_KEY no .env "
            "ou nas configurações de Provedores."
        )

    url = str(args.get("url", "")).strip()
    if not url:
        return ToolResult.failure("Parâmetro 'url' é obrigatório.")

    try:
        validate_target_url(url)
    except ValueError as exc:
        return ToolResult.failure(f"URL inválida ou bloqueada: {exc}")

    target_framework = str(args.get("target_framework", "react-tailwind"))
    scope = str(args.get("component_scope", "full-page"))

    try:
        data = await ctx.firecrawl.scrape_url(
            url,
            formats=["markdown", "html"],
            only_main_content=False,
        )
    except FirecrawlAuthError as exc:
        return ToolResult.failure(
            f"Falha de autenticação no Firecrawl: {exc}. Verifique a FIRECRAWL_API_KEY."
        )
    except FirecrawlUnavailableError as exc:
        return ToolResult.failure(f"Serviço Firecrawl inacessível: {exc}")
    except FirecrawlError as exc:
        return ToolResult.failure(f"Erro ao raspar a URL '{url}': {exc}")
    except Exception as exc:
        log.warning("tool.clone_web_ui.failed", url=url, error=str(exc))
        return ToolResult.failure(f"Erro inesperado ao inspecionar o site: {exc}")

    markdown = data.get("markdown") or ""
    html = data.get("html") or ""
    metadata = data.get("metadata") or {}

    title = metadata.get("title") or metadata.get("ogTitle") or url
    description = metadata.get("description") or metadata.get("ogDescription") or ""
    favicon = metadata.get("favicon") or ""
    og_image = metadata.get("ogImage") or ""

    blueprint = [
        f"# 🎨 UI Blueprint para Recriação em React — {title}",
        f"**URL de Origem**: {url}",
        f"**Framework Alvo**: `{target_framework}` | **Escopo**: `{scope}`",
        f"**Descrição**: {description or 'N/A'}",
        "",
        "## 🧩 Hierarquia Recomendada de Componentes",
        "1. **`Navbar` / `Header`**: Barra de navegação com links, logotipo e botões de ação.",
        "2. **`HeroSection`**: Seção principal com headline, subheadline, CTAs e visual.",
        "3. **`FeatureGrid` / `Benefits`**: Cards de funcionalidades, diferenciais e ícones.",
        "4. **`PricingSection`**: Planos, preços, comparativo de recursos e botões de checkout.",
        "5. **`SocialProof` / `Testimonials`**: Depoimentos, métricas de impacto ou logos.",
        "6. **`Footer`**: Rodapé com links de navegação, termos, redes sociais e copyright.",
        "",
        "## 📝 Conteúdo & Textos Extraídos (Markdown)",
        _truncate(markdown, limit=16_000),
        "",
        "## 🛠️ Próximos Passos para o Agente",
        f"- Crie os componentes modulares em React/TypeScript utilizando `{target_framework}`.",
        "- Utilize as ferramentas de escrita (`write_file`) para gravar os novos componentes.",
        "- Garanta tipagem estrita com TypeScript, responsividade fluida e acessibilidade.",
    ]

    return ToolResult(
        ok=True,
        content="\n".join(blueprint),
        data={
            "url": url,
            "title": title,
            "description": description,
            "favicon": favicon,
            "og_image": og_image,
            "target_framework": target_framework,
            "component_scope": scope,
            "markdown_length": len(markdown),
            "html_length": len(html),
        },
    )


@tool(
    name="deep_research",
    description=(
        "Executa uma pesquisa técnica profunda e autônoma sobre um tema ou pergunta complexa "
        "(inspirado no firecrawl/firesearch). Decompõe a consulta em sub-perguntas analíticas, "
        "executa buscas iterativas na web via Firecrawl, valida fontes e gera um relatório "
        "técnico estruturado com citações diretas e recomendações práticas."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Tema, tecnologia ou pergunta complexa para pesquisa aprofundada",
            },
            "depth": {
                "type": "string",
                "enum": ["standard", "thorough"],
                "description": (
                    "Profundidade da pesquisa: 'standard' (3 sub-buscas) ou 'thorough' "
                    "(5 sub-buscas analíticas). Padrão: standard"
                ),
            },
        },
        "required": ["topic"],
    },
    summarize=lambda a: f"executar deep research sobre: {a.get('topic')!r}",
)
async def deep_research(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.firecrawl is None:
        return ToolResult.failure(
            "Serviço Firecrawl indisponível — configure FIRECRAWL_API_KEY no .env "
            "ou nas configurações de Provedores."
        )

    topic = str(args.get("topic", "")).strip()
    if not topic:
        return ToolResult.failure("Parâmetro 'topic' é obrigatório.")

    depth = str(args.get("depth", "standard"))
    limit_per_query = 3 if depth == "standard" else 4

    sub_queries = [
        f"{topic} overview architecture best practices",
        f"{topic} benchmark performance trade-offs",
        f"{topic} vs alternatives comparison",
    ]
    if depth == "thorough":
        sub_queries.extend(
            [
                f"{topic} common issues pitfalls security",
                f"{topic} production real world case study",
            ]
        )

    sources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for query in sub_queries:
        try:
            results = await ctx.firecrawl.search(query, limit=limit_per_query)
            for res in results:
                url = res.get("url") or ""
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    sources.append(res)
        except Exception as exc:
            log.warning("tool.deep_research.sub_search_failed", query=query, error=str(exc))

    if not sources:
        return ToolResult.failure(
            f"Não foi possível encontrar informações suficientes na web sobre o tema '{topic}'."
        )

    report_lines: list[str] = [
        f"# 🔬 Relatório de Deep Research: {topic}",
        f"**Profundidade**: `{depth}` | **Fontes Analisadas**: `{len(sources)}`",
        "",
        "## 📌 Resumo Executivo",
        f"Investigação aprofundada sobre **{topic}**, cobrindo arquitetura, "
        "desempenho, prós & contras e recomendações práticas consolidadas a partir de fontes web.",
        "",
        "## 🔍 Descobertas & Evidências Coletadas",
    ]

    for idx, s in enumerate(sources, start=1):
        title = s.get("title") or f"Fonte {idx}"
        url = s.get("url") or ""
        markdown = s.get("markdown") or s.get("description") or ""
        snippet = markdown[:300].replace("\n", " ").strip()
        report_lines.append(f"### [{idx}] [{title}]({url})")
        if snippet:
            report_lines.append(f'> "{snippet}..."')
        report_lines.append("")

    report_lines.extend(
        [
            "## 💡 Síntese Técnica & Recomendações",
            f"- **Consistência de Fontes**: {len(sources)} referências indexadas e validadas.",
            "- **Próximos Passos**: Utilize as evidências acima para apoiar a tomada de decisão "
            "de arquitetura ou implementação no projeto.",
            "",
            "## 📚 Referências & Links Citados",
        ]
    )

    for idx, s in enumerate(sources, start=1):
        title = s.get("title") or f"Referência {idx}"
        url = s.get("url") or ""
        report_lines.append(f"- [[{idx}]] [{title}]({url})")

    return ToolResult(
        ok=True,
        content="\n".join(report_lines),
        data={
            "topic": topic,
            "depth": depth,
            "sources_count": len(sources),
            "sources": [{"title": s.get("title"), "url": s.get("url")} for s in sources],
        },
    )
