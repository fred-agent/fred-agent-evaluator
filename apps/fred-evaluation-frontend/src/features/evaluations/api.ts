import type { FredApplicationRequestInit } from "@fred-oss/iframe-sdk";
import type { ApplicationService } from "../../shared/api/applicationService";
import type {
  AgentInstance,
  EvaluationDetail,
  EvaluationDocument,
  EvaluationList,
  EvaluationRun,
  EvaluationRunList,
  EvaluationRunSummary,
  MetricChoice,
  ModelProfile,
  RunAnalysis,
  RunCaseList,
  RunCase,
  RunCreated,
  RunReport,
  RunSpec,
} from "../../shared/api/schemas";

// Every path is relative to the team: the host prefixes
// /app-services/evaluation/teams/<team id>/ and adds the caller's token.

const id = encodeURIComponent;

function json(
  method: "POST" | "PUT",
  body: unknown,
): FredApplicationRequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

async function required<T>(response: Promise<T | null>): Promise<T> {
  const value = await response;
  if (value === null) throw new Error("Empty response");
  return value;
}

export interface ListOptions {
  limit?: number;
  offset?: number;
  sort?: string;
  q?: string;
}

function listQuery(options: ListOptions) {
  return new URLSearchParams({
    limit: String(options.limit ?? 20),
    offset: String(options.offset ?? 0),
    sort: options.sort ?? "created_at:desc",
    ...(options.q ? { q: options.q } : {}),
  });
}

export function createEvaluationApi(service: ApplicationService) {
  return {
    listEvaluations: (options: ListOptions = {}) =>
      required(
        service.request<EvaluationList>(`evaluations?${listQuery(options)}`),
      ),
    getEvaluation: (evaluationId: string) =>
      required(
        service.request<EvaluationDetail>(`evaluations/${id(evaluationId)}`),
      ),
    createEvaluation: (document: EvaluationDocument) =>
      required(
        service.request<EvaluationDetail>(
          "evaluations",
          json("POST", document),
        ),
      ),
    deleteEvaluation: (evaluationId: string) =>
      service.request<null>(`evaluations/${id(evaluationId)}`, {
        method: "DELETE",
      }),
    listRuns: (evaluationId: string, options: ListOptions = {}) =>
      required(
        service.request<EvaluationRunList>(
          `evaluations/${id(evaluationId)}/runs?${listQuery(options)}`,
        ),
      ),
    getRunsSummary: (evaluationId: string) =>
      required(
        service.request<EvaluationRunSummary>(
          `evaluations/${id(evaluationId)}/runs/summary`,
        ),
      ),
    startRun: (evaluationId: string, spec: RunSpec) =>
      required(
        service.request<RunCreated>(
          `evaluations/${id(evaluationId)}/runs`,
          json("POST", spec),
        ),
      ),
    getRun: (runId: string) =>
      required(service.request<EvaluationRun>(`runs/${id(runId)}`)),
    listRunCases: (runId: string, limit = 200) =>
      required(
        service.request<RunCaseList>(
          `runs/${id(runId)}/cases?${new URLSearchParams({ limit: String(limit) })}`,
        ),
      ),
    getRunCase: (runId: string, caseId: string) =>
      required(
        service.request<RunCase>(`runs/${id(runId)}/cases/${id(caseId)}`),
      ),
    cancelRun: (runId: string) =>
      service.request<unknown>(`runs/${id(runId)}/cancel`, { method: "POST" }),
    deleteRun: (runId: string) =>
      service.request<null>(`runs/${id(runId)}`, { method: "DELETE" }),
    // An LLM writes the analysis on first request: allow it longer than the
    // SDK's default 30 s. A gateway timeout upstream still applies.
    analyzeRun: (runId: string) =>
      required(
        service.request<RunAnalysis>(`runs/${id(runId)}/analyze`, {
          method: "POST",
          timeoutMs: 180_000,
        }),
      ),
    getRunReport: (runId: string) =>
      required(service.request<RunReport>(`runs/${id(runId)}/report`)),
    listAgentInstances: () =>
      required(service.request<AgentInstance[]>("agent-instances")),
    listModelProfiles: () =>
      required(service.request<ModelProfile[]>("model-profiles")),
    listMetrics: () => required(service.request<MetricChoice[]>("metrics")),
  };
}

export type EvaluationApi = ReturnType<typeof createEvaluationApi>;
