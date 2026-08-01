import { ErrorNotice } from "@/components/ErrorNotice";
import { ProviderStudio } from "@/components/providers/ProviderStudio";
import {
  apiGet,
  type CatalogModel,
  type CatalogProfile,
  type CredentialsView,
  type ProviderCheck,
} from "@/lib/api";

export const dynamic = "force-dynamic";

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

export default async function ProvidersPage() {
  const [health, catalog, credentials] = await Promise.all([
    apiGet<{ healthy: number; total: number; providers: ProviderCheck[] }>(
      "/api/health/providers",
    ),
    apiGet<{ models: CatalogModel[]; profiles: CatalogProfile[] }>("/api/providers"),
    apiGet<{ credentials: CredentialsView }>("/api/providers/credentials"),
  ]);

  if (!health.ok) return <ErrorNotice error={health.error} />;

  return (
    <div className="shell">
      <div className="providers-page">
        <h1 className="page-title" style={{ marginBottom: 20 }}>
          Estúdio de Configuração de Provedores
        </h1>
        <ProviderStudio
          initialHealth={health.data}
          initialCatalog={catalog.ok ? catalog.data : { models: [], profiles: [] }}
          initialCredentials={credentials.ok ? credentials.data.credentials : EMPTY_CREDENTIALS}
        />
      </div>
    </div>
  );
}
