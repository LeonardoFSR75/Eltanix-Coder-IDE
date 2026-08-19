"use client";

import { useRef, useState } from "react";

import type { NetworkLogEntry, ReplayDetail } from "@/lib/api/browser";
import { PanelState } from "./PanelState";

interface BrowserReplayPanelProps {
  loading: boolean;
  error: string | null;
  data: ReplayDetail | null;
}

const SNAPSHOT_WINDOW_MS = 2000;

/** Timeline de sessão de teste (Fase 4c) — substitui a antiga visão de
 * `BrowserCard` isolado por chamada de ferramenta por uma sequência única:
 * marcadores clicáveis fazem seek no vídeo e mostram as requisições de rede
 * feitas perto daquele instante (mesma base `t_offset_ms` do log de ações). */
export function BrowserReplayPanel({ loading, error, data }: BrowserReplayPanelProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);

  if (loading) {
    return <PanelState kind="loading" message="Carregando replay..." />;
  }
  if (error) {
    return <PanelState kind="error" message={error} />;
  }
  if (!data) {
    return (
      <PanelState
        kind="empty"
        icon="🎬"
        message='Nenhum replay disponível ainda — feche a sessão ("Reiniciar") para gerar vídeo + trace.'
      />
    );
  }

  const marcadorSelecionado = selectedIdx !== null ? data.actions[selectedIdx] : null;
  const rede: NetworkLogEntry[] = data.network ?? [];
  const redeProxima = marcadorSelecionado
    ? rede.filter(
        (r) =>
          r.t_offset_ms !== undefined &&
          Math.abs(r.t_offset_ms - marcadorSelecionado.t_offset_ms) <= SNAPSHOT_WINDOW_MS,
      )
    : [];

  return (
    <div className="browser-replay-panel">
      {data.video_url && (
        <video ref={videoRef} src={data.video_url} controls className="browser-replay-video" />
      )}

      {data.actions.length > 0 && (
        <div className="browser-replay-timeline">
          {data.actions.map((a, idx) => (
            <button
              key={idx}
              type="button"
              className={`browser-replay-marker ${selectedIdx === idx ? "active" : ""}`}
              onClick={() => {
                setSelectedIdx(idx);
                const video = videoRef.current;
                if (video) {
                  video.currentTime = a.t_offset_ms / 1000;
                  void video.play();
                }
              }}
            >
              <span className="browser-replay-marker-time">{(a.t_offset_ms / 1000).toFixed(1)}s</span>
              <span className="browser-replay-marker-action">{a.action}</span>
              <span className="browser-replay-marker-summary">{a.summary}</span>
            </button>
          ))}
        </div>
      )}

      {marcadorSelecionado && (
        <div className="browser-replay-snapshot">
          <div className="browser-replay-snapshot-header">
            Rede perto de {(marcadorSelecionado.t_offset_ms / 1000).toFixed(1)}s (
            {marcadorSelecionado.action})
          </div>
          {redeProxima.length === 0 ? (
            <p className="text-xs text-muted" style={{ padding: "4px 8px" }}>
              Nenhuma requisição registrada perto deste instante.
            </p>
          ) : (
            <ul className="browser-replay-snapshot-list">
              {redeProxima.map((r, idx) => (
                <li key={idx} className="browser-replay-snapshot-item">
                  <span className={`method-badge method-${r.method.toLowerCase()}`}>{r.method}</span>
                  <span
                    className={`status-badge ${r.status && r.status < 400 ? "status-ok" : "status-err"}`}
                  >
                    {r.status ?? "—"}
                  </span>
                  <span className="network-url-cell" title={r.url}>
                    {r.url}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {data.trace_url && (
        <a
          className="browser-replay-trace-link"
          href={data.trace_url}
          target="_blank"
          rel="noreferrer"
        >
          ⬇ Baixar trace.zip (abrir em trace.playwright.dev)
        </a>
      )}
    </div>
  );
}
