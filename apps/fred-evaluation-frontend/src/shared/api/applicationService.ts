import type {
  FredApplicationClient,
  FredApplicationRequestInit,
} from "@fred-oss/iframe-sdk";

/** The backend's one error envelope: `{"detail": {"code", "message"}}`. */
export interface EvaluatorError {
  code: string;
  message: string;
}

export class ApplicationHttpError extends Error {
  constructor(
    readonly status: number,
    readonly evaluatorError: EvaluatorError | null,
  ) {
    super(
      evaluatorError?.message ?? `Application request failed (HTTP ${status})`,
    );
  }

  get code(): string | null {
    return this.evaluatorError?.code ?? null;
  }
}

export class ApplicationTransportError extends Error {
  constructor(readonly cause: unknown) {
    super("Application transport failed");
  }
}

function parseEvaluatorError(body: string): EvaluatorError | null {
  try {
    const detail: unknown = (JSON.parse(body) as { detail?: unknown }).detail;
    if (
      typeof detail === "object" &&
      detail !== null &&
      "code" in detail &&
      "message" in detail &&
      typeof detail.code === "string" &&
      typeof detail.message === "string"
    ) {
      return { code: detail.code, message: detail.message };
    }
  } catch {
    // Not JSON: an upstream or gateway page, not the evaluator's envelope.
  }
  return null;
}

/**
 * Calls the evaluator through Fred's host. Paths are relative to the team:
 * the host prefixes `/app-services/evaluation/teams/<team id>/` and adds the
 * caller's token, so this code never sees either.
 */
export function createApplicationService(
  client: Pick<FredApplicationClient, "request">,
) {
  return {
    async request<T>(
      path: string,
      init?: FredApplicationRequestInit,
    ): Promise<T | null> {
      if (
        !path ||
        path.startsWith("/") ||
        /^[a-z][a-z\d+.-]*:/i.test(path) ||
        path.includes("..")
      ) {
        throw new Error("Application-service path must be relative");
      }
      let response: Response;
      try {
        response = await client.request(path, init);
      } catch (error) {
        throw new ApplicationTransportError(error);
      }
      if (!response.ok) {
        throw new ApplicationHttpError(
          response.status,
          parseEvaluatorError(await response.text()),
        );
      }
      if (response.status === 204 || response.status === 205) return null;
      const body = await response.text();
      return body ? (JSON.parse(body) as T) : null;
    },
  };
}

export type ApplicationService = ReturnType<typeof createApplicationService>;
