"use client";

import { useState } from "react";
import { formatUsd } from "@/lib/format";

interface Point {
  day: string;
  cost_usd: number;
  requests: number;
}

export function CostChart({ points }: { points: Point[] }) {
  const [hovered, setHovered] = useState<Point | null>(null);

  if (!points || points.length === 0) return null;

  const maxCost = Math.max(...points.map((p) => p.cost_usd), 0.001);
  const height = 120;
  const width = 800;
  const padding = 20;

  const dx = (width - padding * 2) / Math.max(points.length - 1, 1);

  // Generate SVG path coordinates
  const coords = points.map((p, i) => {
    const x = padding + i * dx;
    const y = height - padding - (p.cost_usd / maxCost) * (height - padding * 2);
    return { x, y, point: p };
  });

  const linePath = coords.reduce(
    (acc, curr, i) => (i === 0 ? `M ${curr.x} ${curr.y}` : `${acc} L ${curr.x} ${curr.y}`),
    "",
  );

  const areaPath = `${linePath} L ${coords[coords.length - 1].x} ${height} L ${coords[0].x} ${height} Z`;

  return (
    <div className="card cost-chart-card">
      <div className="chart-header">
        <div>
          <span className="chart-title">Custo Diário</span>
          <span className="sub" style={{ marginLeft: 8 }}>Últimos 30 dias</span>
        </div>
        {hovered && (
          <div className="chart-tooltip-badge">
            <strong>{hovered.day}</strong>: {formatUsd(hovered.cost_usd)} ({hovered.requests} reqs)
          </div>
        )}
      </div>

      <div className="chart-svg-container">
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="chart-svg">
          <defs>
            <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.4" />
              <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Area Fill */}
          <path d={areaPath} fill="url(#costGradient)" />

          {/* Line Stroke */}
          <path d={linePath} fill="none" stroke="#38bdf8" strokeWidth="2.5" strokeLinecap="round" />

          {/* Data Points */}
          {coords.map((c, i) => (
            <circle
              key={i}
              cx={c.x}
              cy={c.y}
              r={hovered?.day === c.point.day ? "5" : "3"}
              fill={hovered?.day === c.point.day ? "#38bdf8" : "#818cf8"}
              stroke="#090b0e"
              strokeWidth="1.5"
              className="chart-dot"
              onMouseEnter={() => setHovered(c.point)}
              onMouseLeave={() => setHovered(null)}
            />
          ))}
        </svg>
      </div>
    </div>
  );
}
