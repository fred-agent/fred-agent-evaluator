const CONFIG_PATH = "/apps/evaluation/config.json";

export interface RuntimeConfig {
  hostOrigin: string;
}

export function validateRuntimeConfig(value: unknown): RuntimeConfig {
  if (typeof value !== "object" || value === null || !("hostOrigin" in value)) {
    throw new Error("Missing hostOrigin in runtime config.json");
  }
  const origin = value.hostOrigin;
  if (typeof origin !== "string") {
    throw new Error("hostOrigin must be an absolute HTTP(S) origin");
  }
  let url: URL;
  try {
    url = new URL(origin);
  } catch {
    throw new Error("hostOrigin must be an absolute HTTP(S) origin");
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    !url.hostname ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash ||
    url.origin !== origin
  ) {
    throw new Error(
      "hostOrigin must be an exact HTTP(S) origin without credentials or path",
    );
  }
  return { hostOrigin: origin };
}

export async function loadRuntimeConfig(
  fetcher: typeof fetch = fetch,
): Promise<RuntimeConfig> {
  const response = await fetcher(CONFIG_PATH, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(
      `Runtime config.json unavailable (HTTP ${response.status})`,
    );
  }
  return validateRuntimeConfig(await response.json());
}
