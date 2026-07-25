import { ErrorNotice } from "@/components/ErrorNotice";
import {
  apiGet,
  type CatalogModel,
  type CatalogProfile,
  type ProviderCheck,
} from "@/lib/api";
import { formatMs } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ProvidersPage() {
  const [health, catalog] = await Promise.all([
    apiGet<{ healthy: number; total: number; providers: ProviderCheck[] }>(
      "/api/health/providers",
    ),
    apiGet<{ models: CatalogModel[]; profiles: CatalogProfile[] }>("/api/providers"),
  ]);

  if (!health.ok) return <ErrorNotice error={health.error} />;

  const checks = new Map(health.data.providers.map((p) => [p.model, p]));

  return (
    <>
      <div className="grid">
        <div className="card">
          <div className="label">Provedores saudáveis</div>
          <div className="value">
            {health.data.healthy}/{health.data.total}
          </div>
          <div className="hint">sondados agora</div>
        </div>
      </div>

      <section>
        <h2>
          Modelos<span className="sub">catálogo de config/providers.yaml</span>
        </h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Modelo</th>
                <th>Estado</th>
                <th className="num">Janela</th>
                <th className="num">Sonda</th>
                <th className="num">p95</th>
                <th className="num">$/1M in</th>
                <th className="num">$/1M out</th>
                <th>Detalhe</th>
              </tr>
            </thead>
            <tbody>
              {(catalog.ok ? catalog.data.models : []).map((m) => {
                const check = checks.get(m.id);
                return (
                  <tr key={m.id}>
                    <td>
                      <code>{m.id}</code>
                    </td>
                    <td>
                      <StateBadge model={m} check={check} />
                    </td>
                    <td className="num">{(m.context_window / 1000).toFixed(0)}k</td>
                    <td className="num">{formatMs(check?.probe_latency_ms)}</td>
                    <td className="num">{formatMs(check?.latency_p95_ms)}</td>
                    <td className="num">{m.price?.input ?? "—"}</td>
                    <td className="num">{m.price?.output ?? "—"}</td>
                    <td style={{ whiteSpace: "normal", color: "var(--text-dim)" }}>
                      {m.unavailable_reason ?? check?.detail ?? "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2>
          Perfis de roteamento<span className="sub">config/routes.yaml</span>
        </h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Perfil</th>
                <th>Estratégia</th>
                <th>Cadeia de fallback</th>
              </tr>
            </thead>
            <tbody>
              {(catalog.ok ? catalog.data.profiles : []).map((p) => (
                <tr key={p.name}>
                  <td>
                    <code>{p.name}</code>{" "}
                    {p.is_default && <span className="pill">padrão</span>}
                  </td>
                  <td>{p.strategy}</td>
                  <td style={{ whiteSpace: "normal" }}>
                    {p.models.length > 0 ? p.models.join("  →  ") : <em>vazio</em>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function StateBadge({ model, check }: { model: CatalogModel; check?: ProviderCheck }) {
  if (!model.enabled) return <span className="pill">desligado</span>;
  if (!model.available) return <span className="pill warn">sem credencial</span>;
  if (check?.circuit_open) {
    return <span className="pill bad">circuito aberto ({check.cooldown_remaining_s}s)</span>;
  }
  if (check?.ok) return <span className="pill ok">online</span>;
  return <span className="pill bad">offline</span>;
}
