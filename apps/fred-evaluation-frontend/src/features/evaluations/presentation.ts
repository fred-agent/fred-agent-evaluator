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
