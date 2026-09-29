import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Chip, Dialog, Spinner } from "@fred-oss/ui";
import { useAppNavigate } from "../../app/router";
import { useShellElement } from "../../app/shell";
import { useLoad } from "../../shared/api/useLoad";
import type {
  EvaluationDetail,
  EvaluationRun,
  EvaluationRunSummary,
} from "../../shared/api/schemas";
import { LoadFailure } from "./LoadFailure";
import {
  describeError,
  formatDate,
  isTerminal,
  stateLabel,
  verdictLabel,
} from "./presentation";
import { useEvaluationApi } from "./useEvaluationApi";

const POLL_MS = 5000;

interface EvaluationView {
  evaluation: EvaluationDetail;
  summary: EvaluationRunSummary;
  runs: EvaluationRun[];
  agentNames: Map<string, string>;
}

function targetName(run: EvaluationRun, agentNames: Map<string, string>) {
  const target = run.target;
  if (target.kind === "managed_instance") {
    return agentNames.get(target.agent_instance_id) ?? target.agent_instance_id;
  }
  return target.agent_id;
}

function RunsTable({ view }: { view: EvaluationView }) {
  const { t, i18n } = useTranslation();
  const go = useAppNavigate();
  return (
    <div className="evaluation-table-wrap">
      <table>
        <caption className="visually-hidden">{t("runs.title")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("runs.started")}</th>
            <th scope="col">{t("runs.target")}</th>
            <th scope="col">{t("runs.state")}</th>
            <th scope="col">{t("runs.verdict")}</th>
            <th scope="col">{t("runs.progress")}</th>
            <th scope="col">{t("runs.passed")}</th>
          </tr>
        </thead>
        <tbody>
          {view.runs.map((run) => (
            <tr key={run.run_id}>
              <th scope="row">
                <button
                  type="button"
                  className="evaluation-link"
                  onClick={() => go(`runs/${run.run_id}`)}
                >
                  {formatDate(run.created_at, i18n.language)}
                </button>
              </th>
              <td>{targetName(run, view.agentNames)}</td>
              <td>
                <Chip label={stateLabel(run.operational_state, t)} />
              </td>
              <td>
                <Chip label={verdictLabel(run.verdict, t)} />
              </td>
              <td>
                {run.completed_cases} / {run.total_cases}
              </td>
              <td>
                {run.passed_cases} / {run.total_cases}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One evaluation: what it asks, and every run of it. */
export function EvaluationPage({ evaluationId }: { evaluationId: string }) {
  const { t, i18n } = useTranslation();
  const api = useEvaluationApi();
  const go = useAppNavigate();
  const shell = useShellElement();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(async (): Promise<EvaluationView> => {
    const [evaluation, summary, runs, agents] = await Promise.all([
      api.getEvaluation(evaluationId),
      api.getRunsSummary(evaluationId),
      api.listRuns(evaluationId),
      // Names are a convenience: the runs still show without them.
      api.listAgentInstances().catch(() => []),
    ]);
    return {
      evaluation,
      summary,
      runs: runs.runs,
      agentNames: new Map(
        agents.map((a) => [a.agent_instance_id, a.display_name]),
      ),
    };
  }, [api, evaluationId]);
  const { state, retry } = useLoad(load, (view) =>
    view.runs.some((run) => !isTerminal(run.operational_state))
      ? POLL_MS
      : null,
  );

  const remove = async () => {
    setConfirmDelete(false);
    try {
      await api.deleteEvaluation(evaluationId);
      go("");
    } catch (error) {
      setDeleteError(describeError(error, t));
    }
  };

  return (
    <section aria-labelledby="evaluation-title">
      <div>
        <Button
          color="on-surface"
          variant="text"
          size="small"
          onClick={() => go("")}
        >
          {t("evaluations.backToList")}
        </Button>
      </div>
      {state.status === "loading" && <Spinner statusText={t("loadingPage")} />}
      {state.status === "error" && (
        <LoadFailure error={state.error} onRetry={retry} />
      )}
      {state.status === "ready" && (
        <>
          <header className="evaluation-toolbar">
            <div>
              <h1 id="evaluation-title">
                {state.data.evaluation.name}{" "}
                <span className="evaluation-muted">
                  {state.data.evaluation.version}
                </span>
              </h1>
              <span>
                {t("evaluations.caseCount", {
                  count: state.data.evaluation.case_count,
                })}{" "}
                ·{" "}
                {state.data.evaluation.author ??
                  state.data.evaluation.created_by}{" "}
                · {formatDate(state.data.evaluation.created_at, i18n.language)}
              </span>
            </div>
            <div className="evaluation-actions">
              <Chip
                label={t(`evaluations.${state.data.evaluation.completeness}`)}
              />
              <Button
                color="error"
                variant="outlined"
                size="small"
                onClick={() => setConfirmDelete(true)}
              >
                {t("delete")}
              </Button>
              <Button
                color="primary"
                variant="filled"
                size="small"
                onClick={() => go(`evaluations/${evaluationId}/runs/new`)}
              >
                {t("runs.start")}
              </Button>
            </div>
          </header>
          {deleteError && (
            <p role="alert" className="evaluation-error">
              {deleteError}
            </p>
          )}
          <dl className="evaluation-kpis">
            <div>
              <dt>{t("runs.kpi.total")}</dt>
              <dd>{state.data.summary.total_runs}</dd>
            </div>
            <div>
              <dt>{t("runs.kpi.running")}</dt>
              <dd>{state.data.summary.running_count}</dd>
            </div>
            <div>
              <dt>{t("runs.kpi.completed")}</dt>
              <dd>{state.data.summary.completed_count}</dd>
            </div>
            <div>
              <dt>{t("runs.kpi.cases")}</dt>
              <dd>{state.data.summary.total_cases_completed}</dd>
            </div>
            <div>
              <dt>{t("runs.kpi.critical")}</dt>
              <dd>{state.data.summary.critical_error_cases}</dd>
            </div>
          </dl>
          <h2>{t("runs.title")}</h2>
          {state.data.runs.length === 0 ? (
            <p>{t("runs.empty")}</p>
          ) : (
            <RunsTable view={state.data} />
          )}
          <details className="evaluation-details">
            <summary>
              {t("evaluations.caseCount", {
                count: state.data.evaluation.case_count,
              })}
            </summary>
            <div className="evaluation-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">{t("cases.input")}</th>
                    <th scope="col">{t("cases.expected")}</th>
                  </tr>
                </thead>
                <tbody>
                  {state.data.evaluation.cases.map((c, index) => (
                    <tr key={c.external_id ?? index}>
                      <td>{c.input}</td>
                      <td>{c.expected_output ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <Dialog
            open={confirmDelete}
            title={t("evaluations.deleteTitle")}
            confirmLabel={t("delete")}
            cancelLabel={t("cancel")}
            confirmColor="error"
            onConfirm={() => void remove()}
            onCancel={() => setConfirmDelete(false)}
            portalContainer={shell}
          >
            <p>
              {t("evaluations.deletePrompt", {
                name: state.data.evaluation.name,
              })}
            </p>
          </Dialog>
        </>
      )}
    </section>
  );
}
