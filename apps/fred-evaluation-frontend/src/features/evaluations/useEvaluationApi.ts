import { useMemo } from "react";
import { useFredApplication } from "../../app/providers/FredApplicationProvider";
import { createApplicationService } from "../../shared/api/applicationService";
import { createEvaluationApi, type EvaluationApi } from "./api";

export function useEvaluationApi(): EvaluationApi {
  const { request } = useFredApplication();
  return useMemo(
    () => createEvaluationApi(createApplicationService({ request })),
    [request],
  );
}
