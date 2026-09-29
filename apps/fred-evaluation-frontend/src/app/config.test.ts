import { describe, expect, it, vi } from "vitest";
import { loadRuntimeConfig, validateRuntimeConfig } from "./config";

describe("runtime host origin", () => {
  it("accepts only an explicit exact HTTP(S) origin", () => {
    expect(
      validateRuntimeConfig({ hostOrigin: "https://fred.example" }),
    ).toEqual({
      hostOrigin: "https://fred.example",
    });
    for (const value of [
      {},
      { hostOrigin: "" },
      { hostOrigin: "/relative" },
      { hostOrigin: "https://fred.example/path" },
      { hostOrigin: "https://fred.example?theme=dark" },
      { hostOrigin: "https://fred.example#fragment" },
      { hostOrigin: "https://user@fred.example" },
      { hostOrigin: "javascript:alert(1)" },
    ]) {
      expect(() => validateRuntimeConfig(value)).toThrow();
    }
  });

  it("does not infer trust when config is unavailable", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response("", { status: 404 }));
    await expect(loadRuntimeConfig(fetcher)).rejects.toThrow(
      "config.json unavailable",
    );
    expect(fetcher).toHaveBeenCalledWith("/apps/evaluation/config.json", {
      cache: "no-store",
    });
  });
});
