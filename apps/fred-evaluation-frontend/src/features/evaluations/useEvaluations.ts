import { useCallback, useEffect, useState } from "react";
import type { ApplicationService } from "../../shared/api/applicationService";
import type { EvaluationList } from "../../shared/api/schemas";
import { listEvaluations } from "./api";

export type EvaluationsState =
  | { status: "loading" }
  | { status: "ready"; list: EvaluationList }
  | { status: "error"; error: unknown };

export function useEvaluations(service: ApplicationService) {
  const [state, setState] = useState<EvaluationsState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    listEvaluations(service).then(
      (list) => active && setState({ status: "ready", list }),
      (error: unknown) => active && setState({ status: "error", error }),
    );
    return () => {
      active = false;
    };
  }, [service, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}
