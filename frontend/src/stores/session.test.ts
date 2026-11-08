import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSession } from "@/stores/session";

function reset() {
  useSession.setState({
    status: "unknown",
    user: null,
    error: null,
    checking: false,
    attempted: false,
  });
}

function respond(status: number, body: unknown = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("the session check", () => {
  beforeEach(() => {
    reset();
    vi.restoreAllMocks();
  });

  it("records the signed-in user", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respond(200, {
          authenticated: true,
          user: { id: "u1", email: "a@b.test", name: null, timezone: "UTC" },
        }),
      ),
    );

    await useSession.getState().load();

    expect(useSession.getState().status).toBe("authenticated");
    expect(useSession.getState().user?.email).toBe("a@b.test");
  });

  it("treats 401 as signed out", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(401, { detail: "no" })));
    await useSession.getState().load();
    expect(useSession.getState().status).toBe("anonymous");
    expect(useSession.getState().error).toBeNull();
  });

  it("does not treat an unreachable API as signed out", async () => {
    // Otherwise a blink of wifi logs the user out and loses their work.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    await useSession.getState().load();
    expect(useSession.getState().status).toBe("unknown");
    expect(useSession.getState().error).toBe("network down");
  });

  it("does not retry itself after a failure", async () => {
    // The regression this guards: the gate's effect was keyed on a status
    // that a failed check leaves unchanged, so every render fired another
    // request at an API that was already unhappy.
    const fetchMock = vi.fn().mockRejectedValue(new Error("network down"));
    vi.stubGlobal("fetch", fetchMock);

    await useSession.getState().load();
    await useSession.getState().load();
    await useSession.getState().load();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(useSession.getState().attempted).toBe(true);
  });

  it("retries when asked explicitly", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(
        respond(200, {
          authenticated: true,
          user: { id: "u1", email: "a@b.test", name: null, timezone: "UTC" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await useSession.getState().load();
    await useSession.getState().load({ force: true });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(useSession.getState().status).toBe("authenticated");
  });

  it("shares one request between concurrent callers", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve(respond(401)), 5)),
      );
    vi.stubGlobal("fetch", fetchMock);

    await Promise.all([
      useSession.getState().load(),
      useSession.getState().load(),
      useSession.getState().load(),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
