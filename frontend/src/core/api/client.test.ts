import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, onSessionExpired } from "./client";

afterEach(() => vi.unstubAllGlobals());

function respond(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

describe("api client", () => {
  it("treats only EmneKlar's own 401 as an expired session", async () => {
    const expired = vi.fn();
    const stop = onSessionExpired(expired);
    respond(401, { error: { code: "canvas_token_invalid", message: "Canvas avviste tokenet." } });
    const error = await api.post("/api/canvas/test", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("canvas_token_invalid");
    expect(expired, "a rejected Canvas token is not a logout").not.toHaveBeenCalled();

    respond(401, { error: { code: "session_required", message: "Økten er ikke gyldig." } });
    await api.get("/api/session").catch(() => undefined);
    expect(expired).toHaveBeenCalledOnce();
    stop();
  });
});
