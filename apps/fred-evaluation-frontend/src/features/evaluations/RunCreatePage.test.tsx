import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import i18n from "../../shared/i18n";
import { evaluation } from "../../test/fixtures";
import { ok, renderApp } from "../../test/renderApp";

const metrics = [
  { metric_id: "answer_relevancy", requires_expected_output: false },
  { metric_id: "contextual_precision", requires_expected_output: true },
  { metric_id: "faithfulness", requires_expected_output: false },
];

function routes(agents: unknown[], onStart?: (body: unknown) => void) {
  return {
    "GET evaluations/eval-1": ok(evaluation),
    "GET agent-instances": ok(agents),
    "GET model-profiles": ok([{ profile_id: "mistral-small", name: "x" }]),
    "GET metrics": ok(metrics),
    "POST evaluations/eval-1/runs": (
      init: { body?: string | null } | undefined,
    ) => {
      onStart?.(JSON.parse(init?.body ?? "null"));
      return Response.json(
        {
          run_id: "run-9",
          evaluation_id: "eval-1",
          task_id: "t",
          state: "pending",
        },
        { status: 202 },
      );
    },
  };
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

describe("run creation", () => {
  it("starts a run with the chosen agent and metrics, then opens it", async () => {
    let sent: unknown = null;
    const { fake } = renderApp(
      routes(
        [
          {
            agent_instance_id: "agent-1",
            display_name: "Support bot",
            role: null,
          },
        ],
        (body) => (sent = body),
      ),
      "evaluations/eval-1/runs/new",
    );
    const faithfulness = await screen.findByRole("checkbox", {
      name: "Faithfulness",
    });
    fireEvent.click(faithfulness);
    fireEvent.click(screen.getByRole("button", { name: "Start a run" }));

    await waitFor(() =>
      expect(fake.client.navigate).toHaveBeenCalledWith("runs/run-9"),
    );
    expect(sent).toEqual({
      target: { kind: "managed_instance", agent_instance_id: "agent-1" },
      metrics: ["answer_relevancy", "faithfulness"],
      custom_metrics: [],
      agent_model_override: null,
    });
  });

  it("disables expected-output metrics on a minimal evaluation", async () => {
    renderApp(
      routes([
        {
          agent_instance_id: "agent-1",
          display_name: "Support bot",
          role: null,
        },
      ]),
      "evaluations/eval-1/runs/new",
    );
    expect(
      await screen.findByRole("checkbox", { name: /Contextual precision/ }),
    ).toBeDisabled();
    expect(
      screen.getByText("needs an expected output on every case"),
    ).toBeInTheDocument();
  });

  it("explains a team without agents", async () => {
    renderApp(routes([]), "evaluations/eval-1/runs/new");
    expect(
      await screen.findByText("This team has no agent to evaluate."),
    ).toBeInTheDocument();
  });
});
