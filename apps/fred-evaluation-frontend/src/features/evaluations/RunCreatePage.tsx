import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Breadcrumb,
  Checkbox,
  Switch,
  Select,
  Spinner,
  TextInput,
  TextArea,
  Disclosure,
  PageHeader,
  PageEmptyState,
  useToast,
} from "@fred-oss/ui";
import { useAppNavigate } from "../../app/router";
import { useLoad } from "../../shared/api/useLoad";
import type {
  AgentInstance,
  EvaluationDetail,
  MetricChoice,
  ModelProfile,
  RunSpec,
} from "../../shared/api/schemas";
import { LoadFailure } from "./LoadFailure";
import { describeError } from "./presentation";
import { useEvaluationApi } from "./useEvaluationApi";

import styles from "./RunCreatePage.module.css";

interface Choices {
  evaluation: EvaluationDetail;
  agents: AgentInstance[];
  models: ModelProfile[];
  metrics: MetricChoice[];
}

const PARAMETERS = [
  "INPUT",
  "ACTUAL_OUTPUT",
  "EXPECTED_OUTPUT",
  "RETRIEVAL_CONTEXT",
] as const;
interface CustomRow {
  key: number;
  name: string;
  criteria: string;
  parameters: string[];
  threshold: string;
}
let nextMetricKey = 0;

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
  const toast = useToast();
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
  const [customRows, setCustomRows] = useState<CustomRow[]>([]);
  const completeRows = customRows.filter(
    (row) => row.name.trim() && row.criteria.trim() && row.parameters.length,
  );
  const validThresholds = completeRows.every(
    (row) =>
      row.threshold.trim() &&
      Number.isFinite(Number(row.threshold)) &&
      Number(row.threshold) >= 0 &&
      Number(row.threshold) <= 1,
  );
  const customMetrics: NonNullable<RunSpec["custom_metrics"]> =
    completeRows.map((row) => ({
      name: row.name.trim(),
      criteria: row.criteria.trim(),
      parameters: row.parameters,
      threshold: Number(row.threshold),
    }));
  const updateCustom = (key: number, patch: Partial<CustomRow>) =>
    setCustomRows((rows) =>
      rows.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    );

  const toggle = (metricId: string, on: boolean) =>
    setMetrics((current) => {
      const next = new Set(current);
      if (on) next.add(metricId);
      else next.delete(metricId);
      return next;
    });

  const valid = Boolean(agentId) && metrics.size > 0 && validThresholds;

  const submit = async () => {
    if (!agentId || !valid) return;
    setSubmitting(true);

    try {
      const created = await api.startRun(evaluationId, {
        target: { kind: "managed_instance", agent_instance_id: agentId },
        metrics: [...metrics].sort(),
        custom_metrics: customMetrics,
        agent_model_override: model || null,
      });
      toast.showSuccess({ summary: t("ui.started") });
      go(`runs/${created.run_id}`);
    } catch (reason) {
      toast.showError({ summary: describeError(reason, t) });
      setSubmitting(false);
    }
  };

  if (choices.agents.length === 0) {
    return <PageEmptyState icon="smart_toy" message={t("runCreate.noAgent")} />;
  }

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className={styles.configuration}>
        <section className={styles.target} aria-labelledby="run-target-heading">
          <h2 id="run-target-heading" className={styles.sectionTitle}>
            {t("runCreate.configuration")}
          </h2>
          <div className={styles.targetFields}>
            <Select
              label={t("runCreate.agent")}
              size="small"
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
            <Select
              label={t("runCreate.model")}
              size="small"
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
          </div>
        </section>
        <fieldset className={styles.metrics}>
          <legend>{t("runCreate.metrics")}</legend>
          <p className={styles.hint}>{t("runCreate.metricsHint")}</p>
          {choices.metrics.map((metric) => (
            <label key={metric.metric_id} className={styles.metric}>
              <span className={styles.metricCopy}>
                <span className={styles.metricName}>
                  {t(`metrics.${metric.metric_id}`, {
                    defaultValue: metric.metric_id,
                  })}
                </span>
                <span className={styles.hint}>
                  {t(`ui.description_${metric.metric_id}`, {
                    defaultValue: metric.metric_id,
                  })}
                </span>
                {!usable(metric) && (
                  <span className={styles.requirement}>
                    {t("runCreate.needsExpectedOutput")}
                  </span>
                )}
              </span>
              <Switch
                aria-label={t(`metrics.${metric.metric_id}`, {
                  defaultValue: metric.metric_id,
                })}
                checked={metrics.has(metric.metric_id)}
                disabled={!usable(metric)}
                onChange={(event) =>
                  toggle(metric.metric_id, event.target.checked)
                }
              />
            </label>
          ))}
        </fieldset>
        <Disclosure title={t("ui.customMetrics")}>
          <div className="evaluation-stack">
            {customRows.map((row, index) => (
              <fieldset key={row.key} className="evaluation-fieldset">
                <legend>
                  {t("ui.customMetrics")} {index + 1}
                </legend>
                <TextInput
                  label={t("ui.metricName", { n: index + 1 })}
                  value={row.name}
                  onChange={(event) =>
                    updateCustom(row.key, { name: event.target.value })
                  }
                />
                <TextArea
                  label={t("ui.criteria", { n: index + 1 })}
                  value={row.criteria}
                  onChange={(event) =>
                    updateCustom(row.key, { criteria: event.target.value })
                  }
                />
                <fieldset className="evaluation-fieldset">
                  <legend>{t("ui.parameters")}</legend>
                  {PARAMETERS.map((parameter) => (
                    <label key={parameter} className="evaluation-check">
                      <Checkbox
                        checked={row.parameters.includes(parameter)}
                        onChange={(event) =>
                          updateCustom(row.key, {
                            parameters: event.target.checked
                              ? [...row.parameters, parameter]
                              : row.parameters.filter(
                                  (value) => value !== parameter,
                                ),
                          })
                        }
                      />
                      <span>{parameter}</span>
                    </label>
                  ))}
                </fieldset>
                <TextInput
                  label={t("ui.threshold", { n: index + 1 })}
                  explanation={t("ui.thresholdHint")}
                  type="number"
                  min={0}
                  max={1}
                  step="0.01"
                  value={row.threshold}
                  onChange={(event) =>
                    updateCustom(row.key, { threshold: event.target.value })
                  }
                />
                <Button
                  type="button"
                  color="error"
                  variant="text"
                  size="small"
                  onClick={() =>
                    setCustomRows((rows) =>
                      rows.filter((value) => value.key !== row.key),
                    )
                  }
                >
                  {t("ui.removeMetric", { n: index + 1 })}
                </Button>
              </fieldset>
            ))}
          </div>
          <Button
            type="button"
            color="primary"
            variant="text"
            size="small"
            onClick={() =>
              setCustomRows((rows) => [
                ...rows,
                {
                  key: nextMetricKey++,
                  name: "",
                  criteria: "",
                  parameters: ["INPUT", "ACTUAL_OUTPUT"],
                  threshold: "0.5",
                },
              ])
            }
          >
            {t("ui.addMetric")}
          </Button>
        </Disclosure>
      </div>
      <section className={styles.summary} aria-labelledby="run-summary-heading">
        <h2 id="run-summary-heading" className={styles.sectionTitle}>
          {t("ui.recap")}
        </h2>
        <div className={styles.dataset}>
          <p className={styles.datasetName}>{choices.evaluation.name}</p>
          <p className={styles.hint}>
            {t("runCreate.datasetSummary", {
              version: choices.evaluation.version,
              count: choices.evaluation.case_count,
            })}
          </p>
        </div>
        <dl className={styles.summaryList}>
          <div>
            <dt>{t("runCreate.agent")}</dt>
            <dd>
              {choices.agents.find(
                (agent) => agent.agent_instance_id === agentId,
              )?.display_name ?? "—"}
            </dd>
          </div>
          <div>
            <dt>{t("runCreate.model")}</dt>
            <dd>{model || t("runCreate.teamDefault")}</dd>
          </div>
          <div>
            <dt>{t("runCreate.metrics")}</dt>
            <dd>
              {[...metrics]
                .map((id) => t(`metrics.${id}`, { defaultValue: id }))
                .join(", ") || "—"}
            </dd>
          </div>
          {customMetrics.length > 0 && (
            <div>
              <dt>{t("ui.customMetrics")}</dt>
              <dd>{customMetrics.map((metric) => metric.name).join(", ")}</dd>
            </div>
          )}
        </dl>
        {completeRows.length < customRows.length && (
          <p role="status" className={styles.hint}>
            {t("ui.incompleteMetrics")}
          </p>
        )}
        <div className={styles.actions}>
          <Button
            type="submit"
            color="primary"
            variant="filled"
            size="small"
            disabled={!valid || submitting}
          >
            {submitting ? t("runCreate.starting") : t("runs.start")}
          </Button>
          <Button
            type="button"
            color="on-surface"
            variant="text"
            size="small"
            onClick={() => go(`evaluations/${evaluationId}`)}
          >
            {t("cancel")}
          </Button>
        </div>
      </section>
    </form>
  );
}

/** Start a run of one evaluation against one of the team's agents. */
export function RunCreatePage({ evaluationId }: { evaluationId: string }) {
  const { t } = useTranslation();
  const go = useAppNavigate();
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
    <section>
      <PageHeader
        breadcrumb={
          <Breadcrumb
            segments={[
              { label: t("evaluations.title"), onClick: () => go("") },
              {
                label:
                  state.status === "ready"
                    ? state.data.evaluation.name
                    : t("runs.title"),
                onClick: () => go(`evaluations/${evaluationId}`),
              },
              { label: t("runs.start") },
            ]}
          />
        }
        title={t("runs.start")}
        subtitle={
          state.status === "ready"
            ? `${state.data.evaluation.name} ${state.data.evaluation.version}`
            : undefined
        }
      />
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
