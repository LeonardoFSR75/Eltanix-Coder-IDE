import { afterEach, describe, expect, it } from "vitest";
import {
  DEFAULT_GUTTER_LAYERS,
  loadGutterLayers,
  saveGutterLayers,
} from "@/lib/use-gutter-intelligence";

afterEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* noop */
  }
});

describe("gutter layer persistence", () => {
  it("defaults to every layer off when nothing is stored", () => {
    expect(loadGutterLayers()).toEqual(DEFAULT_GUTTER_LAYERS);
    expect(DEFAULT_GUTTER_LAYERS).toEqual({ blame: false, coverage: false, cve: false });
  });

  it("round-trips a saved selection", () => {
    saveGutterLayers({ blame: true, coverage: false, cve: true });
    expect(loadGutterLayers()).toEqual({ blame: true, coverage: false, cve: true });
  });

  it("coerces a partial / malformed payload to booleans", () => {
    localStorage.setItem("eltanix.ide.gutterLayers", JSON.stringify({ blame: 1 }));
    expect(loadGutterLayers()).toEqual({ blame: true, coverage: false, cve: false });

    localStorage.setItem("eltanix.ide.gutterLayers", "not json");
    expect(loadGutterLayers()).toEqual(DEFAULT_GUTTER_LAYERS);
  });
});
