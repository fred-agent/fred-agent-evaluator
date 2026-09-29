import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import i18n from "../../shared/i18n";
import { evaluation, run } from "../../test/fixtures";
import { ok, renderApp } from "../../test/renderApp";

const summary = {
  total_runs: 1,
  running_count: 0,
  completed_count: 1,
  total_cases_completed: 4,
  critical_error_cases: 0,
};

const routes = {
  "GET evaluations/eval-1": ok(evaluation),
  "GET evaluations/eval-1/runs/summary": ok(summary),
  "GET evaluations/eval-1/runs": ok({
    runs: [run({ operational_state: "completed", verdict: "passed" })],
    total: 1,
  }),
  "GET agent-instances": ok([
    { agent_instance_id: "agent-1", display_name: "Support bot", role: null },
  ]),
};

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

describe("evaluation page", () => {
  it("shows the evaluation, its KPIs and its runs by agent name", async () => {
    const { fake } = renderApp(routes, "evaluations/eval-1");
    await screen.findByRole("heading", { name: /golden-set/ });
    expect(screen.getByText("Cases scored").nextSibling).toHaveTextContent("4");
    const table = screen.getByRole("table", { name: "Runs" });
    expect(within(table).getByText("Support bot")).toBeInTheDocument();
    expect(within(table).getByText("Completed")).toBeInTheDocument();

    fireEvent.click(within(table).getAllByRole("button")[0]);
    expect(fake.client.navigate).toHaveBeenCalledWith("runs/run-1");
  });

  it("goes to the run form", async () => {
    const { fake } = renderApp(routes, "evaluations/eval-1");
    fireEvent.click(await screen.findByRole("button", { name: "Start a run" }));
    expect(fake.client.navigate).toHaveBeenCalledWith(
      "evaluations/eval-1/runs/new",
    );
  });

  it("deletes the evaluation after confirmation, then returns to the list", async () => {
    let deleted = false;
    const { fake } = renderApp(
      {
        ...routes,
        "DELETE evaluations/eval-1": () => {
          deleted = true;
          return new Response(null, { status: 204 });
        },
        "GET evaluations": ok({ evaluations: [], total: 0 }),
      },
      "evaluations/eval-1",
    );
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Delete “golden-set” and all its runs?");
    // The dialog is portalled into the themed application root.
    expect(dialog.closest(".evaluation-shell")).not.toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(fake.client.navigate).toHaveBeenCalledWith(""));
    expect(deleted).toBe(true);
  });

  it("says so when the evaluation belongs to no team it can see", async () => {
    const { fake } = renderApp(
      {
        "GET evaluations/eval-1": () =>
          Response.json(
            { detail: { code: "evaluation_not_found", message: "x" } },
            { status: 404 },
          ),
      },
      "evaluations/eval-1",
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This evaluation does not exist.",
    );
    // A deep link opens its own screen directly, without loading the list.
    expect(
      fake.request.mock.calls.some(([path]) => path.startsWith("evaluations?")),
    ).toBe(false);
  });
});
