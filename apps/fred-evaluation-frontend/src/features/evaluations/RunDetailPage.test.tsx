import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../shared/i18n";
import { run, runCase } from "../../test/fixtures";
import { ok, renderApp } from "../../test/renderApp";

const cases = ok({ cases: [runCase], total: 1 });

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("run detail", () => {
  it("polls a running run and stops once it has finished", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const states = [
      run(),
      run({
        operational_state: "completed",
        verdict: "passed",
        completed_cases: 4,
        passed_cases: 4,
      }),
    ];
    let polls = 0;
    renderApp(
      {
        "GET runs/run-1": () => Response.json(states[Math.min(polls++, 1)]),
        "GET runs/run-1/cases": cases,
        "GET runs/run-1/cases/case-1": ok(runCase),
      },
      "runs/run-1",
    );
    await screen.findByText("1 of 4 cases done");
    expect(
      screen.getByRole("button", { name: "Cancel run" }),
    ).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    await screen.findByText("4 of 4 cases done");
    expect(screen.getByRole("button", { name: "Analyze" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();

    const settled = polls;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(polls).toBe(settled);
  });

  it("shows each case's scores and details", async () => {
    renderApp(
      {
        "GET runs/run-1": ok(
          run({ operational_state: "completed", verdict: "passed" }),
        ),
        "GET runs/run-1/cases": cases,
        "GET runs/run-1/cases/case-1": ok(runCase),
      },
      "runs/run-1",
    );
    expect(
      await screen
        .findAllByText("Answer relevancy 0.91")
        .then((items) => items[0]),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "case-1" }));
    await screen.findByText(/Model used:/);
    expect(screen.getByText(/mistral-small-2506/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("complementary")).getByText("A platform."),
    ).toBeInTheDocument();
  });

  it("analyzes a completed run and shows the analysis", async () => {
    renderApp(
      {
        "GET runs/run-1": ok(
          run({ operational_state: "completed", verdict: "passed" }),
        ),
        "GET runs/run-1/cases": cases,
        "GET runs/run-1/cases/case-1": ok(runCase),
        "POST runs/run-1/analyze": ok({
          run_id: "run-1",
          cached: false,
          analysis: {
            summary: "Solid on basics.",
            strengths: ["Relevant"],
            weaknesses: [],
            recommendations: ["Add harder cases"],
            risk_level: "low",
          },
        }),
      },
      "runs/run-1",
    );
    fireEvent.click(await screen.findByRole("button", { name: "Analyze" }));
    expect(await screen.findByText("Solid on basics.")).toBeInTheDocument();
    expect(screen.getByText("Add harder cases")).toBeInTheDocument();
  });

  it("cancels a running run and shows its new state", async () => {
    let cancelled = false;
    renderApp(
      {
        "GET runs/run-1": () =>
          Response.json(
            cancelled ? run({ operational_state: "cancelled" }) : run(),
          ),
        "GET runs/run-1/cases": cases,
        "GET runs/run-1/cases/case-1": ok(runCase),
        "POST runs/run-1/cancel": () => {
          cancelled = true;
          return Response.json(
            { run_id: "run-1", state: "cancelled" },
            { status: 202 },
          );
        },
      },
      "runs/run-1",
    );
    fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    expect(cancelled).toBe(true);
  });

  it("downloads the report of a finished run as JSON", async () => {
    const created: Blob[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      created.push(blob as Blob);
      return "blob:report";
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    renderApp(
      {
        "GET runs/run-1": ok(
          run({ operational_state: "completed", verdict: "passed" }),
        ),
        "GET runs/run-1/cases": cases,
        "GET runs/run-1/cases/case-1": ok(runCase),
        "GET runs/run-1/report": ok({ run: { run_id: "run-1" } }),
      },
      "runs/run-1",
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Download report" }),
    );
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.readAsText(created[0]);
    });
    expect(JSON.parse(text)).toEqual({ run: { run_id: "run-1" } });
  });
});
