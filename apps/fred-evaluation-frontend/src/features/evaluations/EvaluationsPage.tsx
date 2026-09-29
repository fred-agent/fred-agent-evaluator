import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Button, Chip, Spinner } from "@fred-oss/ui";
import { useAppNavigate } from "../../app/router";
import { useLoad } from "../../shared/api/useLoad";
import type { EvaluationSummary } from "../../shared/api/schemas";
import { describeError, formatDate } from "./presentation";
import { useEvaluationApi } from "./useEvaluationApi";

function EvaluationsTable({
  evaluations,
}: {
  evaluations: EvaluationSummary[];
}) {
  const { t, i18n } = useTranslation();
  const go = useAppNavigate();
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
              <th scope="row">
                <button
                  type="button"
                  className="evaluation-link"
                  onClick={() => go(`evaluations/${evaluation.evaluation_id}`)}
                >
                  {evaluation.name}
                </button>
              </th>
              <td>{evaluation.version}</td>
              <td>{evaluation.case_count}</td>
              <td>
                <Chip label={t(`evaluations.${evaluation.completeness}`)} />
              </td>
              <td>{evaluation.author ?? evaluation.created_by}</td>
              <td>{formatDate(evaluation.created_at, i18n.language)}</td>
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
  const api = useEvaluationApi();
  const go = useAppNavigate();
  const load = useCallback(() => api.listEvaluations(), [api]);
  const { state, retry } = useLoad(load);

  return (
    <section aria-labelledby="evaluations-title">
      <header className="evaluation-toolbar">
        <div>
          <h1 id="evaluations-title">{t("evaluations.title")}</h1>
          {state.status === "ready" && (
            <span>{t("evaluations.count", { count: state.data.total })}</span>
          )}
        </div>
        <Button
          color="primary"
          variant="filled"
          size="small"
          onClick={() => go("evaluations/new")}
        >
          {t("evaluations.new")}
        </Button>
      </header>
      {state.status === "loading" && (
        <Spinner statusText={t("evaluations.loading")} />
      )}
      {state.status === "error" && (
        <div role="alert" className="evaluation-error">
          <p>{describeError(state.error, t)}</p>
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
        (state.data.evaluations.length === 0 ? (
          <p>{t("evaluations.empty")}</p>
        ) : (
          <EvaluationsTable evaluations={state.data.evaluations} />
        ))}
    </section>
  );
}
