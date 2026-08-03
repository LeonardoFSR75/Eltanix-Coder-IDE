import { describe, expect, it } from "vitest";
import { MODE_HINT, MODES } from "./modes";

// Sem React — captura do lado frontend a mesma classe de bug que a
// duplicação de Literal em api/routes/agent.py causou do lado backend
// (um modo novo esquecido num dos dois lugares).

describe("modes", () => {
  it("has a MODE_HINT entry for every mode in MODES", () => {
    for (const mode of MODES) {
      expect(MODE_HINT[mode]).toBeTruthy();
    }
  });

  it("has no duplicate modes in MODES", () => {
    expect(new Set(MODES).size).toBe(MODES.length);
  });

  it("MODES covers exactly the keys of MODE_HINT — no missing, no extra", () => {
    expect(new Set(MODES)).toEqual(new Set(Object.keys(MODE_HINT)));
  });

  it("includes orchestra as a selectable mode", () => {
    expect(MODES).toContain("orchestra");
  });
});
