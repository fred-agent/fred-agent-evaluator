import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button, Chip, Spinner } from "@fred-oss/ui";
import { useFredApplication } from "../../app/providers/FredApplicationProvider";
import {
  ApplicationHttpError,
  createApplicationService,
} from "../../shared/api/applicationService";
import type { EvaluationSummary } from "../../shared/api/schemas";
import { useEvaluations } from "./useEvaluations";

function errorMessage(error: unknown, t: (key: string) => string): string {
  if (
    error instanceof ApplicationHttpError &&
    error.code === "application_not_granted"
  ) {
    return t("evaluations.notGranted");
  }
  return t("evaluations.loadFailed");
}

function EvaluationsTable({
  evaluations,
}: {
  evaluations: EvaluationSummary[];
}) {
  const { t, i18n } = useTranslation();
  const dates = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });
  return (
    <div className="evaluation-table-wrap">
      <table>
        <caption className="visually-hidden">{t("evaluations.title")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("evaluations.name")}</th>
            <th scope="col">{t("evaluations.version")}</th>
            <th scope="col">{t("evaluations.cases")}</th>
            <th scope="col">{t("evaluations.completeness")}</th>
            <th scope="col">{t("evaluations.author")}</th>
            <th scope="col">{t("evaluations.created")}</th>
          </tr>
        </thead>
        <tbody>
          {evaluations.map((evaluation) => (
            <tr key={evaluation.evaluation_id}>
              <th scope="row">{evaluation.name}</th>
              <td>{evaluation.version}</td>
              <td>{evaluation.case_count}</td>
              <td>
                <Chip label={t(`evaluations.${evaluation.completeness}`)} />
              </td>
              <td>{evaluation.author ?? evaluation.created_by}</td>
              <td>{dates.format(new Date(evaluation.created_at))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The team's evaluations — the application's entry screen. */
export function EvaluationsPage() {
  const { t } = useTranslation();
  const { request } = useFredApplication();
  const service = useMemo(
    () => createApplicationService({ request }),
    [request],
  );
  const { state, retry } = useEvaluations(service);

  return (
    <section aria-labelledby="evaluations-title">
      <header className="evaluation-toolbar">
        <h1 id="evaluations-title">{t("evaluations.title")}</h1>
        {state.status === "ready" && (
          <span>{t("evaluations.count", { count: state.list.total })}</span>
        )}
      </header>
      {state.status === "loading" && (
        <Spinner statusText={t("evaluations.loading")} />
      )}
      {state.status === "error" && (
        <div role="alert" className="evaluation-error">
          <p>{errorMessage(state.error, t)}</p>
          <Button
            color="primary"
            variant="outlined"
            size="small"
            onClick={retry}
          >
            {t("retry")}
          </Button>
        </div>
      )}
      {state.status === "ready" &&
        (state.list.evaluations.length === 0 ? (
          <p>{t("evaluations.empty")}</p>
        ) : (
          <EvaluationsTable evaluations={state.list.evaluations} />
        ))}
    </section>
  );
}
