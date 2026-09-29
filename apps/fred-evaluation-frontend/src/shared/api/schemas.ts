import type { components } from "./openapi";

/** Backend models, generated from its OpenAPI (`npm run generate:api`). */
type Schemas = components["schemas"];

export type EvaluationSummary = Schemas["EvaluationSummaryResponse"];
export type EvaluationList = Schemas["EvaluationListResponse"];
