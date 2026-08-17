"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ErrorNotice } from "@/components/ErrorNotice";
import { ProviderStudio } from "@/components/providers/ProviderStudio";
import { getProvidersHealth, type ProvidersHealthResponse } from "@/lib/api/health";
import { getCatalog, getCredentials, type CatalogResponse, type CredentialsView } from "@/lib/api/providers";

const EMPTY_CREDENTIAL = { configured: false, value: "", masked: null };
const EMPTY_CREDENTIALS: CredentialsView = {
  ollama_base_url: EMPTY_CREDENTIAL,
  azure_api_base: EMPTY_CREDENTIAL,
  azure_api_key: EMPTY_CREDENTIAL,
  databricks_host: EMPTY_CREDENTIAL,
  databricks_token: EMPTY_CREDENTIAL,
  openai_api_key: EMPTY_CREDENTIAL,
  anthropic_api_key: EMPTY_CREDENTIAL,
  groq_api_key: EMPTY_CREDENTIAL,
  github_token: EMPTY_CREDENTIAL,
  firecrawl_api_key: EMPTY_CREDENTIAL,
  firecrawl_api_url: EMPTY_CREDENTIAL,
};
const EMPTY_CATALOG: CatalogResponse = { models: [], profiles: [] };

interface LoadedData {
  health: ProvidersHealthResponse;
  catalog: CatalogResponse;
  credentials: CredentialsView;
}

export default function ProvidersPage() {
  const [data, setData] = useState<LoadedData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      // Saúde é o que decide se a página é utilizável; catálogo/credenciais
      // degradam para vazio em vez de derrubar a tela inteira. As três
      // resolvem juntas antes de montar ProviderStudio: ele só lê
      // `initial*` uma vez (useState), então um set em duas etapas deixaria
      // o catálogo travado vazio para sempre depois da primeira montagem.
      try {
        const [health, catalog, credentials] = await Promise.all([
          getProvidersHealth(),
          getCatalog().catch(() => EMPTY_CATALOG),
          getCredentials().catch(() => EMPTY_CREDENTIALS),
        ]);
        if (cancelled) return;
        setData({ health, catalog, credentials });
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <ErrorNotice error={error} />;
  if (!data) return null;

  return (
    <div className="shell">
      <div className="providers-page">
        <div className="page-header" style={{ marginBottom: 20 }}>
          <div>
            <span className="page-badge">🌐 Provedores LLM & Gateway</span>
            <h1 className="page-title" style={{ margin: "4px 0 0 0" }}>
              Estúdio de Configuração de Provedores
            </h1>
            <p className="text-xs text-muted" style={{ margin: "4px 0 0 0" }}>
              Gerencie chaves de API, modelos suportados e regras de fallback para LiteLLM.
            </p>
          </div>
          <div className="header-actions">
            <Link href="/settings" className="btn-secondary-sm">
              ⚙️ Infraestrutura & Cache
            </Link>
            <Link href="/settings/git" className="btn-secondary-sm">
              🐙 Conta Git & GitHub
            </Link>
          </div>
        </div>
        <ProviderStudio
          initialHealth={data.health}
          initialCatalog={data.catalog}
          initialCredentials={data.credentials}
        />
      </div>
    </div>
  );
}
