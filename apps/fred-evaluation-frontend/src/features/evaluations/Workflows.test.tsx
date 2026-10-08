import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../shared/i18n";
import { evaluation, run, runCase } from "../../test/fixtures";
import { ok, renderApp } from "../../test/renderApp";

const summary = {
  total_runs: 42,
  running_count: 0,
  completed_count: 42,
  total_cases_completed: 168,
  critical_error_cases: 2,
};
const evaluationRoutes = {
  "GET evaluations/eval-1": ok(evaluation),
  "GET evaluations/eval-1/runs/summary": ok(summary),
  "GET evaluations/eval-1/runs": ok({
    runs: [run({ operational_state: "completed" })],
    total: 42,
  }),
  "GET agent-instances": ok([
    { agent_instance_id: "agent-1", display_name: "Support bot", role: null },
  ]),
};
beforeEach(async () => {
  await i18n.changeLanguage("en");
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("list and run workflows", () => {
  it("debounces search, pages with server totals, and resets offset on sort/search", async () => {
    const queries: URLSearchParams[] = [];
    renderApp({
      "GET evaluations": (_init, path) => {
        queries.push(new URLSearchParams(path.split("?")[1]));
        return Response.json({ evaluations: [evaluation], total: 42 });
      },
    });
    await screen.findByRole("button", { name: "golden-set" });
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(queries.at(-1)?.get("offset")).toBe("20"));
    fireEvent.change(screen.getByLabelText("Search evaluations"), {
      target: { value: "gold" },
    });
    expect(queries.at(-1)?.get("q")).toBeNull();
    await waitFor(() => expect(queries.at(-1)?.get("q")).toBe("gold"));
    expect(queries.at(-1)?.get("offset")).toBe("0");
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(queries.at(-1)?.get("offset")).toBe("20"));
    fireEvent.click(screen.getByRole("button", { name: /Sort/ }));
    fireEvent.click(screen.getByRole("option", { name: "Name A–Z" }));
    await waitFor(() => expect(queries.at(-1)?.get("sort")).toBe("name:asc"));
    expect(queries.at(-1)?.get("offset")).toBe("0");
  });

  it("confirms deletion and reports failure while keeping the list", async () => {
    const remove = vi.fn(() =>
      Response.json(
        { detail: { code: "target_forbidden", message: "denied" } },
        { status: 403 },
      ),
    );
    renderApp({
      "GET evaluations": ok({ evaluations: [evaluation], total: 1 }),
      "DELETE evaluations/eval-1": remove,
    });
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Cancel",
      }),
    );
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Delete",
      }),
    );
    await screen.findByText("You do not have access to this team or agent.");
    expect(
      screen.getByRole("button", { name: "golden-set" }),
    ).toBeInTheDocument();
  });

  it("reruns the original target, metrics, custom metrics and model", async () => {
    const source = run({
      operational_state: "completed",
      metrics: ["faithfulness"],
      custom_metrics: [
        {
          name: "style",
          criteria: "Be concise",
          parameters: ["ACTUAL_OUTPUT"],
          threshold: 0.7,
        },
      ],
      agent_model_override: "model-x",
    });
    let sent: unknown;
    const { fake } = renderApp(
      {
        ...evaluationRoutes,
        "GET evaluations/eval-1/runs": ok({ runs: [source], total: 1 }),
        "POST evaluations/eval-1/runs": (init) => {
          sent = JSON.parse(init?.body ?? "null");
          return Response.json({ run_id: "run-2" });
        },
      },
      "evaluations/eval-1",
    );
    fireEvent.click(await screen.findByRole("button", { name: "Rerun" }));
    await waitFor(() =>
      expect(fake.client.navigate).toHaveBeenCalledWith("runs/run-2"),
    );
    expect(sent).toEqual({
      target: source.target,
      metrics: source.metrics,
      custom_metrics: source.custom_metrics,
      agent_model_override: source.agent_model_override,
    });
  });

  it("keeps rerun pending per row and leaves other actions available", async () => {
    let finish!: (response: Response) => void;
    renderApp(
      {
        ...evaluationRoutes,
        "GET evaluations/eval-1/runs": ok({
          runs: [
            run({ operational_state: "completed" }),
            run({ run_id: "run-2", operational_state: "completed" }),
          ],
          total: 2,
        }),
        "POST evaluations/eval-1/runs": () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      },
      "evaluations/eval-1",
    );
    const buttons = await screen.findAllByRole("button", { name: "Rerun" });
    fireEvent.click(buttons[0]);
    expect(buttons[0]).toBeDisabled();
    expect(buttons[1]).toBeEnabled();
    await act(async () =>
      finish(Response.json({ detail: {} }, { status: 503 })),
    );
    await waitFor(() => expect(buttons[0]).toBeEnabled());
  });

  it("polls when a live run is outside the visible page", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const loadSummary = vi.fn(ok({ ...summary, running_count: 1 }));
    renderApp(
      {
        ...evaluationRoutes,
        "GET evaluations/eval-1/runs/summary": loadSummary,
      },
      "evaluations/eval-1",
    );
    await screen.findByRole("heading", { name: /golden-set/ });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(loadSummary).toHaveBeenCalledTimes(2);
  });

  it("previews a run and follows a case link to its full drawer", async () => {
    renderApp(
      {
        ...evaluationRoutes,
        "GET runs/run-1": ok(run({ operational_state: "completed" })),
        "GET runs/run-1/cases": ok({ cases: [runCase], total: 1 }),
        "GET runs/run-1/cases/case-1": ok(runCase),
      },
      "evaluations/eval-1",
    );
    const runs = await screen.findByRole("region", { name: "Runs" });
    fireEvent.click(within(runs).getAllByRole("button")[3]);
    const drawer = await screen.findByRole("complementary");
    fireEvent.click(
      await within(drawer).findByRole("button", { name: "What is Fred?" }),
    );
    await screen.findByText("A platform.");
    expect(screen.getByRole("complementary")).toHaveTextContent("On topic.");
  });

  it("loads a linked case and copies the complete JSON", async () => {
    const copy = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: copy },
    });
    renderApp(
      {
        "GET runs/run-1": ok(run({ operational_state: "completed" })),
        "GET runs/run-1/cases": ok({ cases: [runCase], total: 1 }),
        "GET runs/run-1/cases/case-1": ok(runCase),
      },
      "runs/run-1/cases/case-1",
    );
    fireEvent.click(await screen.findByRole("button", { name: "Copy JSON" }));
    await screen.findByText("JSON copied");
    expect(JSON.parse(copy.mock.calls[0][0])).toEqual(runCase);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("complementary")).toBeNull());
  });
});

it("submits complete G-Eval rows and omits half-filled rows", async () => {
  let sent: unknown;
  renderApp(
    {
      "GET evaluations/eval-1": ok(evaluation),
      "GET agent-instances": ok([
        {
          agent_instance_id: "agent-1",
          display_name: "Support bot",
          role: null,
        },
      ]),
      "GET model-profiles": ok([]),
      "GET metrics": ok([
        { metric_id: "answer_relevancy", requires_expected_output: false },
      ]),
      "POST evaluations/eval-1/runs": (init) => {
        sent = JSON.parse(init?.body ?? "null");
        return Response.json({ run_id: "run-9" });
      },
    },
    "evaluations/eval-1/runs/new",
  );
  const custom = await screen.findByRole("button", {
    name: "Custom metrics (G-Eval)",
  });
  expect(custom).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(custom);
  const add = await screen.findByRole("button", { name: "Add custom metric" });
  fireEvent.click(add);
  fireEvent.click(add);
  fireEvent.change(screen.getByLabelText("Metric name 1"), {
    target: { value: "Style" },
  });
  fireEvent.change(screen.getByLabelText("Criteria 1"), {
    target: { value: "Clear and concise" },
  });
  fireEvent.change(screen.getByLabelText("Threshold 1"), {
    target: { value: "0.7" },
  });
  fireEvent.change(screen.getByLabelText("Metric name 2"), {
    target: { value: "Incomplete" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Start a run" }));
  await waitFor(() => expect(sent).toBeDefined());
  expect(sent).toMatchObject({
    custom_metrics: [
      {
        name: "Style",
        criteria: "Clear and concise",
        parameters: ["INPUT", "ACTUAL_OUTPUT"],
        threshold: 0.7,
      },
    ],
  });
});

it("opens a run's preview from its row without confusing its detail action", async () => {
  renderApp(
    {
      ...evaluationRoutes,
      "GET runs/run-1": ok(run({ operational_state: "completed" })),
      "GET runs/run-1/cases": ok({ cases: [runCase], total: 1 }),
    },
    "evaluations/eval-1",
  );
  const region = await screen.findByRole("region", { name: "Runs" });
  const row = region.querySelector('[data-activatable="true"]') as HTMLElement;
  fireEvent.click(row);
  expect(await screen.findByRole("complementary")).toHaveTextContent("Preview");
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  await waitFor(() => expect(screen.queryByRole("complementary")).toBeNull());
  fireEvent.click(within(region).getByRole("button", { name: "Detail" }));
  await screen.findByRole("heading", { name: "Metric averages" });
  expect(screen.queryByRole("complementary")).toBeNull();
});
