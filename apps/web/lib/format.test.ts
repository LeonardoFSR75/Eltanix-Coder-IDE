import { describe, expect, it } from "vitest";
import { formatDateTime, formatMs, formatPercent, formatTokens, formatUsd } from "./format";

describe("formatUsd", () => {
  it("shows exactly $0.00 for zero", () => {
    expect(formatUsd(0)).toBe("$0.00");
  });

  it("uses 4 decimals for values under a cent, to avoid rounding to $0.00", () => {
    expect(formatUsd(0.0016)).toBe("$0.0016");
  });

  it("uses 2 decimals for values a cent or above", () => {
    expect(formatUsd(1.5)).toBe("$1.50");
  });
});

describe("formatTokens", () => {
  it("keeps small counts as plain integers", () => {
    expect(formatTokens(500)).toBe("500");
  });

  it("abbreviates thousands with one decimal", () => {
    expect(formatTokens(1500)).toBe("1.5k");
  });

  it("abbreviates millions with two decimals", () => {
    expect(formatTokens(1_500_000)).toBe("1.50M");
  });
});

describe("formatMs", () => {
  it("shows a dash for null/undefined", () => {
    expect(formatMs(null)).toBe("—");
    expect(formatMs(undefined)).toBe("—");
  });

  it("shows whole milliseconds under a second", () => {
    expect(formatMs(500)).toBe("500ms");
  });

  it("shows seconds with two decimals at or above 1000ms", () => {
    expect(formatMs(1500)).toBe("1.50s");
  });
});

describe("formatPercent", () => {
  it("multiplies by 100 and keeps one decimal", () => {
    expect(formatPercent(0.456)).toBe("45.6%");
  });
});

describe("formatDateTime", () => {
  it("renders day/month and time in pt-BR shape", () => {
    const resultado = formatDateTime("2026-03-05T14:30:00Z");
    // Timezone do runner pode variar o horário exato — verifica só o formato.
    expect(resultado).toMatch(/^\d{2}\/\d{2}, \d{2}:\d{2}:\d{2}$/);
  });
});
