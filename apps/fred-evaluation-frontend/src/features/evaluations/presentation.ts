import type { StatusBadgeTone } from "@fred-oss/ui";
import type { TFunction } from "i18next";
import { ApplicationHttpError } from "../../shared/api/applicationService";

/** A run in one of these states never changes again (backend TERMINAL_RUN_STATES). */
export const TERMINAL_STATES = new Set([
  "completed",
  "succeeded",
  "failed",
  "cancelled",
  "error",
]);

export const isTerminal = (state: string) => TERMINAL_STATES.has(state);

const KNOWN_CODES = new Set([
  "analysis_unavailable",
  "application_not_granted",
  "target_forbidden",
  "target_not_found",
  "target_unavailable",
  "evaluation_not_found",
  "run_not_found",
  "control_plane_unavailable",
]);

/** A localized sentence for a failed call, keyed by the backend's error code. */
export function describeError(error: unknown, t: TFunction): string {
  if (error instanceof ApplicationHttpError) {
    if (error.code && KNOWN_CODES.has(error.code)) {
      return t(`errors.${error.code}`);
    }
    if (error.status === 409) return t("errors.conflict");
    if (error.status === 422) return t("errors.invalid");
  }
  return t("errors.generic");
}

export function stateLabel(state: string, t: TFunction): string {
  return t(`states.${state}`, { defaultValue: state });
}

export function verdictLabel(verdict: string, t: TFunction): string {
  return t(`verdicts.${verdict}`, { defaultValue: verdict });
}

export function formatDate(value: string | null | undefined, locale: string) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatScore(score: number | null | undefined): string {
  return score === null || score === undefined ? "—" : score.toFixed(2);
}

export function statusPresentation(
  value: string,
  group: "states" | "verdicts" | "evaluations" | "risk",
  t: TFunction,
) {
  const tones: Record<string, StatusBadgeTone> = {
    passed: "success",
    complete: "success",
    completed: "success",
    succeeded: "success",
    low: "success",
    failed: "error",
    error: "error",
    high: "error",
    critical: "error",
    insufficient: "warning",
    inconclusive: "warning",
    minimal: "warning",
    medium: "warning",
    running: "info",
    pending: "neutral",
    cancelled: "neutral",
    cancelling: "info",
    skipped: "neutral",
  };
  return {
    label: t(`${group}.${value}`, { defaultValue: value }),
    tone: tones[value] ?? "neutral",
  };
}

export function downloadJson(filename: string, content: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(content, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
