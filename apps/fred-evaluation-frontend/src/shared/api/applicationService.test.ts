import { describe, expect, it, vi } from "vitest";
import {
  ApplicationHttpError,
  ApplicationTransportError,
  createApplicationService,
} from "./applicationService";

describe("application-service adapter", () => {
  it("uses only a team-relative path and parses a typed response", async () => {
    const request = vi.fn().mockResolvedValue(Response.json([{ id: "one" }]));
    const result = await createApplicationService({ request }).request<
      Array<{ id: string }>
    >("evaluations");
    expect(result).toEqual([{ id: "one" }]);
    expect(request).toHaveBeenCalledExactlyOnceWith("evaluations", undefined);
    for (const path of [
      "/evaluations",
      "../teams/other",
      "https://x.example",
    ]) {
      await expect(
        createApplicationService({ request }).request(path),
      ).rejects.toThrow("must be relative");
    }
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("exposes the evaluator's error code and message", async () => {
    const request = vi.fn().mockResolvedValue(
      Response.json(
        {
          detail: {
            code: "application_not_granted",
            message: "Your team does not have access.",
          },
        },
        { status: 403 },
      ),
    );
    const failure = await createApplicationService({ request })
      .request("evaluations")
      .catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApplicationHttpError);
    const httpError = failure as ApplicationHttpError;
    expect(httpError.status).toBe(403);
    expect(httpError.code).toBe("application_not_granted");
    expect(httpError.message).toBe("Your team does not have access.");
  });

  it("distinguishes non-envelope errors, transport errors and empty bodies", async () => {
    const request = vi.fn();
    request.mockResolvedValueOnce(new Response("bad gateway", { status: 502 }));
    const failure = await createApplicationService({ request })
      .request("evaluations")
      .catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApplicationHttpError);
    expect((failure as ApplicationHttpError).code).toBeNull();

    request.mockRejectedValueOnce(new Error("connection lost"));
    await expect(
      createApplicationService({ request }).request("evaluations"),
    ).rejects.toBeInstanceOf(ApplicationTransportError);

    request.mockResolvedValueOnce(new Response(null, { status: 204 }));
    expect(
      await createApplicationService({ request }).request("evaluations"),
    ).toBeNull();
    expect(request).toHaveBeenCalledTimes(3);
  });
});
