import { ErrorNotice } from "@/components/ErrorNotice";
import { ProviderStudio } from "@/components/providers/ProviderStudio";
import {
  apiGet,
  type CatalogModel,
  type CatalogProfile,
  type ProviderCheck,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ProvidersPage() {
  const [health, catalog] = await Promise.all([
    apiGet<{ healthy: number; total: number; providers: ProviderCheck[] }>(
      "/api/health/providers",
    ),
    apiGet<{ models: CatalogModel[]; profiles: CatalogProfile[] }>("/api/providers"),
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
        />
      </div>
    </div>
  );
}
