"use client";

/**
 * Gutter intelligence do editor (Onda 1.5): três camadas de decoração na
 * margem do Monaco, ligáveis independentemente e lembradas por navegador.
 *
 * - **blame**  — barra fina na gutter, colorida pela idade do commit; hover na
 *   linha mostra autor · quando · assunto · sha.
 * - **coverage** — realce de fundo da linha (verde/vermelho/âmbar) a partir de
 *   um relatório de cobertura já gerado no projeto.
 * - **cve** — ⚠ no glyph margin nas linhas de `requirements.txt` /
 *   `package.json` cujo pacote tem CVE conhecida.
 *
 * Tudo READ-only e à prova de falha: qualquer erro de fetch simplesmente não
 * desenha aquela camada.
 */

import { useEffect, useRef } from "react";
import { getBlame } from "@/lib/api/git";
import { getCoverage, getDependencyMarkers } from "@/lib/api/quality";

export interface GutterLayers {
  blame: boolean;
  coverage: boolean;
  cve: boolean;
}

export const DEFAULT_GUTTER_LAYERS: GutterLayers = {
  blame: false,
  coverage: false,
  cve: false,
};

const STORAGE_KEY = "eltanix.ide.gutterLayers";

export function loadGutterLayers(): GutterLayers {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_GUTTER_LAYERS };
    const parsed = JSON.parse(raw) as Partial<GutterLayers>;
    return {
      blame: !!parsed.blame,
      coverage: !!parsed.coverage,
      cve: !!parsed.cve,
    };
  } catch {
    return { ...DEFAULT_GUTTER_LAYERS };
  }
}

export function saveGutterLayers(layers: GutterLayers): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layers));
  } catch {
    /* modo privado / storage cheio — a preferência só não persiste */
  }
}

const DAY = 86_400_000;

function ageBucket(iso: string): number {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 4;
  const days = (Date.now() - t) / DAY;
  if (days < 7) return 0;
  if (days < 30) return 1;
  if (days < 120) return 2;
  if (days < 365) return 3;
  return 4;
}

function relTime(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const days = Math.floor((Date.now() - t) / DAY);
  if (days <= 0) return "hoje";
  if (days === 1) return "ontem";
  if (days < 30) return `há ${days} dias`;
  if (days < 365) return `há ${Math.floor(days / 30)} meses`;
  return `há ${Math.floor(days / 365)} anos`;
}

function cveTier(severity: string): "high" | "mod" | "low" {
  if (severity === "critical" || severity === "high") return "high";
  if (severity === "moderate" || severity === "medium") return "mod";
  return "low";
}

export function useGutterIntelligence(opts: {
  editor: unknown;
  monaco: unknown;
  project: string | null;
  path: string | null;
  language: string | null;
  layers: GutterLayers;
  /** bump para forçar recomputo (ex.: após salvar o arquivo). */
  refreshKey?: number | string;
}): void {
  const { editor, monaco, project, path, layers, language, refreshKey } = opts;
  const idsRef = useRef<string[]>([]);

  useEffect(() => {
    const ed = editor as any;
    const mon = monaco as any;
    if (!ed || !mon || !project || !path) return;
    const model = ed.getModel?.();
    if (!model) return;

    const clear = () => {
      try {
        idsRef.current = ed.deltaDecorations(idsRef.current, []);
      } catch {
        /* editor já desmontado */
      }
    };

    if (!layers.blame && !layers.coverage && !layers.cve) {
      clear();
      return;
    }

    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      const [blame, coverage, cve] = await Promise.all([
        layers.blame
          ? getBlame(project, path).catch(() => null)
          : Promise.resolve(null),
        layers.coverage
          ? getCoverage(project, path, controller.signal).catch(() => null)
          : Promise.resolve(null),
        layers.cve
          ? getDependencyMarkers(project, path, controller.signal).catch(() => null)
          : Promise.resolve(null),
      ]);
      if (cancelled) return;

      const lineCount: number = model.getLineCount();
      const Range = mon.Range;
      const rulerRight = mon.editor?.OverviewRulerLane?.Right ?? 4;
      const decos: unknown[] = [];

      if (blame) {
        for (const h of blame) {
          const start = Math.max(1, h.start_line);
          const end = Math.min(lineCount, h.end_line);
          if (end < start) continue;
          const bucket = ageBucket(h.date);
          const sha = (h.sha || "").slice(0, 7);
          decos.push({
            range: new Range(start, 1, end, 1),
            options: {
              isWholeLine: true,
              linesDecorationsClassName: `gt-blame gt-blame-a${bucket}`,
              hoverMessage: {
                value:
                  `**${h.author || "?"}** · ${relTime(h.date)}\n\n` +
                  `${(h.message || "(sem mensagem)").replace(/\n[\s\S]*/, "")}\n\n` +
                  `\`${sha}\``,
              },
            },
          });
        }
      }

      if (coverage?.file) {
        const band = (lines: number[], kind: "hit" | "part" | "miss") => {
          for (const ln of lines) {
            if (ln < 1 || ln > lineCount) continue;
            decos.push({
              range: new Range(ln, 1, ln, 1),
              options: {
                isWholeLine: true,
                className: `gt-cov-${kind}`,
                // Sem a barra quando o blame já ocupa a gutter, para não brigar.
                linesDecorationsClassName: layers.blame
                  ? undefined
                  : `gt-covbar gt-covbar-${kind}`,
                overviewRuler:
                  kind === "miss"
                    ? { color: "rgba(248,113,113,0.75)", position: rulerRight }
                    : undefined,
              },
            });
          }
        };
        band(coverage.file.covered, "hit");
        band(coverage.file.partial, "part");
        band(coverage.file.uncovered, "miss");
      }

      if (cve?.markers?.length) {
        for (const m of cve.markers) {
          if (m.line < 1 || m.line > lineCount) continue;
          const tier = cveTier(m.severity);
          const ids = m.ids?.length ? `\n\n${m.ids.join(", ")}` : "";
          const fix = m.fix ? `\n\nCorreção: \`${m.fix}\`` : "";
          decos.push({
            range: new Range(m.line, 1, m.line, 1),
            options: {
              isWholeLine: true,
              glyphMarginClassName: `gt-cve gt-cve-${tier}`,
              glyphMarginHoverMessage: {
                value: `⚠ **${m.package}** — ${m.severity}\n\n${m.summary}${ids}${fix}`,
              },
              className: "gt-cve-row",
              overviewRuler: { color: "rgba(251,191,36,0.85)", position: rulerRight },
            },
          });
        }
      }

      if (cancelled) return;
      try {
        idsRef.current = ed.deltaDecorations(idsRef.current, decos);
      } catch {
        /* editor desmontou no meio */
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
      clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, monaco, project, path, language, layers.blame, layers.coverage, layers.cve, refreshKey]);
}
