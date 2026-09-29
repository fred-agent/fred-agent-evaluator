import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import i18n from "../../shared/i18n";
import { evaluation } from "../../test/fixtures";
import { renderApp } from "../../test/renderApp";

function withCreate(onCreate: (body: unknown) => void) {
  return {
    "POST evaluations": (init: { body?: string | null } | undefined) => {
      onCreate(JSON.parse(init?.body ?? "null"));
      return Response.json(evaluation, { status: 201 });
    },
  };
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

describe("evaluation creation", () => {
  it("creates a manual evaluation from typed cases, then opens it", async () => {
    let sent: unknown = null;
    const { fake } = renderApp(
      withCreate((b) => (sent = b)),
      "evaluations/new",
    );
    fireEvent.change(await screen.findByLabelText(/^Name/), {
      target: { value: " golden " },
    });
    fireEvent.change(screen.getByLabelText("Question 1"), {
      target: { value: "What is Fred?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(fake.client.navigate).toHaveBeenCalledWith("evaluations/eval-1"),
    );
    expect(sent).toEqual({
      name: "golden",
      version: null,
      author: null,
      origin: "manual",
      source_filename: null,
      cases: [{ input: "What is Fred?", expected_output: null }],
    });
  });

  it("imports a JSON document, then creates it as an upload", async () => {
    let sent: { origin?: string; source_filename?: string; cases?: unknown[] } =
      {};
    renderApp(
      withCreate((b) => (sent = b as typeof sent)),
      "evaluations/new",
    );
    const file = new File(
      [
        JSON.stringify({
          name: "golden",
          version: "1.0.0",
          cases: [{ input: "q1", expected_output: "a1" }, { input: "q2" }],
        }),
      ],
      "golden.json",
      { type: "application/json" },
    );
    fireEvent.change(await screen.findByLabelText("Import a JSON document"), {
      target: { files: [file] },
    });
    await waitFor(() =>
      expect(screen.getByLabelText(/^Name/)).toHaveValue("golden"),
    );
    expect(screen.getByLabelText("Version")).toHaveValue("1.0.0");
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(sent.origin).toBe("upload"));
    expect(sent.source_filename).toBe("golden.json");
    expect(sent.cases).toEqual([
      { input: "q1", expected_output: "a1" },
      { input: "q2", expected_output: null },
    ]);
  });

  it("explains an unreadable document and keeps the form as it was", async () => {
    renderApp({}, "evaluations/new");
    fireEvent.change(await screen.findByLabelText("Import a JSON document"), {
      target: { files: [new File(["{"], "broken.json")] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This file is not valid JSON.",
    );
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  });
});
