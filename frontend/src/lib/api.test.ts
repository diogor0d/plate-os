import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("api errors", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("provides a message when an HTTP error has no status text or body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 502 })));

    const request = api("/api/vision/parse-label");

    await expect(request).rejects.toMatchObject({
      status: 502,
      message: "Request failed with HTTP 502",
    });
  });
});
