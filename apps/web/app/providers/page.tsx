"use client";

import { useEffect, useState } from "react";
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
};
const EMPTY_CATALOG: CatalogResponse = { models: [], profiles: [] };

export default function ProvidersPage() {
  const [health, setHealth] = useState<ProvidersHealthResponse | null>(null);
  const [catalog, setCatalog] = useState<CatalogResponse>(EMPTY_CATALOG);
  const [credentials, setCredentials] = useState<CredentialsView>(EMPTY_CREDENTIALS);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      // Saúde é o que decide se a página é utilizável; catálogo/credenciais
      // degradam para vazio em vez de derrubar a tela inteira.
      try {
        const h = await getProvidersHealth();
        if (cancelled) return;
        setHealth(h);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        return;
      }

      const [c, cr] = await Promise.allSettled([getCatalog(), getCredentials()]);
      if (cancelled) return;
      if (c.status === "fulfilled") setCatalog(c.value);
      if (cr.status === "fulfilled") setCredentials(cr.value);
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <ErrorNotice error={error} />;
  if (!health) return null;

  return (
    <div className="shell">
      <div className="providers-page">
        <h1 className="page-title" style={{ marginBottom: 20 }}>
          Estúdio de Configuração de Provedores
        </h1>
        <ProviderStudio
          initialHealth={health}
          initialCatalog={catalog}
          initialCredentials={credentials}
        />
      </div>
    </div>
  );
}
