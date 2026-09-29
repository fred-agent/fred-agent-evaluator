import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Checkbox, Select, Spinner } from "@fred-oss/ui";
import { useAppNavigate } from "../../app/router";
import { useLoad } from "../../shared/api/useLoad";
import type {
  AgentInstance,
  EvaluationDetail,
  MetricChoice,
  ModelProfile,
} from "../../shared/api/schemas";
import { LoadFailure } from "./LoadFailure";
import { describeError } from "./presentation";
import { useEvaluationApi } from "./useEvaluationApi";

interface Choices {
  evaluation: EvaluationDetail;
  agents: AgentInstance[];
  models: ModelProfile[];
  metrics: MetricChoice[];
}

const DEFAULT_METRIC = "answer_relevancy";

function RunForm({
  evaluationId,
  choices,
}: {
  evaluationId: string;
  choices: Choices;
}) {
  const { t } = useTranslation();
  const api = useEvaluationApi();
  const go = useAppNavigate();
  const minimal = choices.evaluation.completeness !== "complete";
  const usable = (metric: MetricChoice) =>
    !(minimal && metric.requires_expected_output);

  const [agentId, setAgentId] = useState<string | undefined>(
    choices.agents.length === 1
      ? choices.agents[0].agent_instance_id
      : undefined,
  );
  const [metrics, setMetrics] = useState<Set<string>>(
    () =>
      new Set(
        choices.metrics.some((m) => m.metric_id === DEFAULT_METRIC)
          ? [DEFAULT_METRIC]
          : [],
      ),
  );
  const [model, setModel] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (metricId: string, on: boolean) =>
    setMetrics((current) => {
      const next = new Set(current);
      if (on) next.add(metricId);
      else next.delete(metricId);
      return next;
    });

  const valid = Boolean(agentId) && metrics.size > 0;

  const submit = async () => {
    if (!agentId || !valid) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.startRun(evaluationId, {
        target: { kind: "managed_instance", agent_instance_id: agentId },
        metrics: [...metrics].sort(),
        custom_metrics: [],
        agent_model_override: model || null,
      });
      go(`runs/${created.run_id}`);
    } catch (reason) {
      setError(describeError(reason, t));
      setSubmitting(false);
    }
  };

  if (choices.agents.length === 0) {
    return <p>{t("runCreate.noAgent")}</p>;
  }

  return (
    <form
      className="evaluation-form"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <Select
        label={t("runCreate.agent")}
        size="medium"
        placeholder={t("runCreate.agentPlaceholder")}
        value={agentId}
        onChange={setAgentId}
        options={choices.agents.map((agent) => ({
          key: agent.agent_instance_id,
          value: agent.agent_instance_id,
          label: agent.display_name,
          description: agent.role ?? undefined,
        }))}
      />
      <fieldset className="evaluation-fieldset">
        <legend>{t("runCreate.metrics")}</legend>
        {choices.metrics.map((metric) => (
          <label key={metric.metric_id} className="evaluation-check">
            <Checkbox
              checked={metrics.has(metric.metric_id)}
              disabled={!usable(metric)}
              onChange={(event) =>
                toggle(metric.metric_id, event.target.checked)
              }
            />
            <span>
              {t(`metrics.${metric.metric_id}`, {
                defaultValue: metric.metric_id,
              })}
            </span>
            {!usable(metric) && (
              <span className="evaluation-muted">
                {t("runCreate.needsExpectedOutput")}
              </span>
            )}
          </label>
        ))}
      </fieldset>
      <Select
        label={t("runCreate.model")}
        size="medium"
        value={model}
        onChange={setModel}
        options={[
          { key: "", value: "", label: t("runCreate.teamDefault") },
          ...choices.models.map((profile) => ({
            key: profile.profile_id,
            value: profile.profile_id,
            label: profile.profile_id,
          })),
        ]}
      />
      {error && (
        <p role="alert" className="evaluation-error">
          {error}
        </p>
      )}
      <div className="evaluation-actions">
        <Button
          type="button"
          color="on-surface"
          variant="text"
          size="small"
          onClick={() => go(`evaluations/${evaluationId}`)}
        >
          {t("cancel")}
        </Button>
        <Button
          type="submit"
          color="primary"
          variant="filled"
          size="small"
          disabled={!valid || submitting}
        >
          {submitting ? t("runCreate.starting") : t("runs.start")}
        </Button>
      </div>
    </form>
  );
}

/** Start a run of one evaluation against one of the team's agents. */
export function RunCreatePage({ evaluationId }: { evaluationId: string }) {
  const { t } = useTranslation();
  const api = useEvaluationApi();
  const load = useCallback(async (): Promise<Choices> => {
    const [evaluation, agents, models, metrics] = await Promise.all([
      api.getEvaluation(evaluationId),
      api.listAgentInstances(),
      api.listModelProfiles(),
      api.listMetrics(),
    ]);
    return { evaluation, agents, models, metrics };
  }, [api, evaluationId]);
  const { state, retry } = useLoad(load);

  return (
    <section aria-labelledby="run-create-title">
      <header className="evaluation-toolbar">
        <div>
          <h1 id="run-create-title">{t("runs.start")}</h1>
          {state.status === "ready" && (
            <span>
              {state.data.evaluation.name} {state.data.evaluation.version}
            </span>
          )}
        </div>
      </header>
      {state.status === "loading" && <Spinner statusText={t("loadingPage")} />}
      {state.status === "error" && (
        <LoadFailure error={state.error} onRetry={retry} />
      )}
      {state.status === "ready" && (
        <RunForm evaluationId={evaluationId} choices={state.data} />
      )}
    </section>
  );
}
