import { afterEach, describe, expect, it, vi } from "vitest";
import { del, get, post, streamEvents } from "./client";

function jsonResponse(body: unknown, init?: { ok?: boolean; status?: number }): Response {
  return {
    ok: init?.ok ?? true,
    status: init?.status ?? 200,
    statusText: "",
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("get/post/del", () => {
  it("get() calls the gateway path and returns the parsed body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ hello: "world" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await get<{ hello: string }>("/api/health");

    expect(result).toEqual({ hello: "world" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/gateway/api/health",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("get() throws with the backend's detail message on a non-ok response", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "chave inválida" }, { ok: false, status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(get("/api/health")).rejects.toThrow("chave inválida");
  });

  it("post() sends method, JSON content-type and the serialized body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await post("/api/notes", { title: "x" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/gateway/api/notes");
    expect(init.method).toBe("POST");
    expect(init.headers["content-type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ title: "x" }));
  });

  it("del() sends the DELETE method", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await del("/api/notes/1");

    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
  });
});

describe("streamEvents", () => {
  function streamedResponse(chunks: string[]): Response {
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });
    return { ok: true, body } as unknown as Response;
  }

  it("parses a single complete SSE event", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(streamedResponse(['data: {"node":"think"}\n\n']));
    vi.stubGlobal("fetch", fetchMock);

    const events: unknown[] = [];
    await streamEvents("/api/agent/sessions/1/run", {}, (e) => events.push(e));

    expect(events).toEqual([{ node: "think" }]);
  });

  it("reassembles an event split across two network chunks", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(streamedResponse(['data: {"nod', 'e":"act"}\n\n']));
    vi.stubGlobal("fetch", fetchMock);

    const events: unknown[] = [];
    await streamEvents("/api/agent/sessions/1/run", {}, (e) => events.push(e));

    expect(events).toEqual([{ node: "act" }]);
  });

  it("stops at the [DONE] sentinel without emitting it as an event", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(streamedResponse(['data: {"node":"think"}\n\n', "data: [DONE]\n\n"]));
    vi.stubGlobal("fetch", fetchMock);

    const events: unknown[] = [];
    await streamEvents("/api/agent/sessions/1/run", {}, (e) => events.push(e));

    expect(events).toEqual([{ node: "think" }]);
  });

  it("swallows a malformed event instead of throwing", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        streamedResponse(["data: {not json}\n\n", 'data: {"node":"think"}\n\n']),
      );
    vi.stubGlobal("fetch", fetchMock);

    const events: unknown[] = [];
    await expect(
      streamEvents("/api/agent/sessions/1/run", {}, (e) => events.push(e)),
    ).resolves.toBeUndefined();

    expect(events).toEqual([{ node: "think" }]);
  });
});
