import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../../app/App";
import { FredApplicationProvider } from "../../app/providers/FredApplicationProvider";
import i18n from "../../shared/i18n";
import type { EvaluationSummary } from "../../shared/api/schemas";
import { fakeFredClient } from "../../test/fakeFredClient";

const golden: EvaluationSummary = {
  evaluation_id: "eval-1",
  name: "golden-set",
  version: "v2",
  author: "Data team",
  created_by: "alice",
  team_id: "team-one",
  origin: "upload",
  completeness: "complete",
  case_count: 12,
  created_at: "2026-09-20T10:00:00Z",
};

function renderWith(respond: Parameters<typeof fakeFredClient>[0]) {
  const fake = fakeFredClient(respond);
  render(
    <FredApplicationProvider
      hostOrigin="https://fred.example"
      clientFactory={() => fake.client}
    >
      <App />
    </FredApplicationProvider>,
  );
  return fake;
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

describe("evaluations page", () => {
  it("lists the team's evaluations, newest first, through the host", async () => {
    const fake = renderWith(() =>
      Response.json({ evaluations: [golden], total: 1 }),
    );
    const row = (await screen.findByRole("rowheader", { name: "golden-set" }))
      .parentElement as HTMLElement;
    expect(within(row).getByText("v2")).toBeInTheDocument();
    expect(within(row).getByText("12")).toBeInTheDocument();
    expect(within(row).getByText("Complete")).toBeInTheDocument();
    expect(within(row).getByText("Data team")).toBeInTheDocument();
    expect(screen.getByText("1 evaluation")).toBeInTheDocument();
    // Team-relative: the host, not this code, names the team and adds the token.
    expect(fake.request).toHaveBeenCalledExactlyOnceWith(
      "evaluations?limit=50&sort=created_at%3Adesc",
      undefined,
    );
  });

  it("says so when the team has no evaluation", async () => {
    renderWith(() => Response.json({ evaluations: [], total: 0 }));
    await screen.findByText("No evaluation yet for this team.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("explains a team without access to the application", async () => {
    renderWith(() =>
      Response.json(
        { detail: { code: "application_not_granted", message: "denied" } },
        { status: 403 },
      ),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This team does not have access to the evaluation application.",
    );
  });

  it("offers a retry after a failure, and recovers", async () => {
    let calls = 0;
    const fake = renderWith(() =>
      ++calls === 1
        ? new Response("upstream down", { status: 503 })
        : Response.json({ evaluations: [golden], total: 1 }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The evaluations could not be loaded.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("rowheader", { name: "golden-set" });
    expect(fake.request).toHaveBeenCalledTimes(2);
  });
});
