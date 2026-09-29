import type { components } from "./openapi";

/** Backend models, generated from its OpenAPI (`npm run generate:api`). */
type Schemas = components["schemas"];

export type EvaluationSummary = Schemas["EvaluationSummaryResponse"];
export type EvaluationList = Schemas["EvaluationListResponse"];
export type EvaluationDetail = Schemas["EvaluationDetailResponse"];
export type EvaluationDocument = Schemas["EvaluationDocument"];
export type EvaluationCase = Schemas["EvaluationCase"];
export type EvaluationRun = Schemas["EvaluationRun"];
export type EvaluationRunList = Schemas["EvaluationRunListResponse"];
export type EvaluationRunSummary = Schemas["EvaluationRunSummaryResponse"];
export type RunCase = Schemas["EvaluationCaseResponse"];
export type RunCaseList = Schemas["EvaluationCaseListResponse"];
export type RunSpec = Schemas["RunSpec"];
export type RunCreated = Schemas["RunCreatedResponse"];
export type RunAnalysis = Schemas["RunAnalysisResponse"];
export type RunReport = Schemas["RunReportResponse"];
export type AgentInstance = Schemas["TeamAgentInstance"];
export type ModelProfile = Schemas["TeamModelProfile"];
export type MetricChoice = Schemas["MetricChoice"];
