import { act, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import i18n from "../../shared/i18n";
import { run, runCase } from "../../test/fixtures";
import { ok, renderApp } from "../../test/renderApp";

describe("analysis availability", () => {
  it.each([
    ["en", "Ask an administrator", "Your evaluation results are preserved."],
    [
      "fr",
      "Demandez à un administrateur",
      "Vos résultats d'évaluation sont conservés.",
    ],
  ])(
    "explains an unavailable analysis in %s",
    async (locale, action, preserved) => {
      renderApp(
        {
          "GET runs/run-1": ok(
            run({ operational_state: "completed", verdict: "passed" }),
          ),
          "GET runs/run-1/cases": ok({ cases: [runCase], total: 1 }),
          "POST runs/run-1/analyze": () =>
            Response.json(
              {
                detail: {
                  code: "analysis_unavailable",
                  message: "Analysis model unavailable.",
                },
              },
              { status: 503 },
            ),
        },
        "runs/run-1",
      );
      await screen.findByRole("button", { name: "Analyze" });
      await act(async () => {
        await i18n.changeLanguage(locale);
      });
      fireEvent.click(
        screen.getByRole("button", { name: i18n.t("analysis.run") }),
      );
      const explanation = await screen.findByText(new RegExp(action));
      expect(explanation).toHaveTextContent(preserved);
      expect(
        screen.queryByText("Something went wrong."),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: i18n.t("analysis.run") }),
      ).toBeEnabled();
    },
  );
});
