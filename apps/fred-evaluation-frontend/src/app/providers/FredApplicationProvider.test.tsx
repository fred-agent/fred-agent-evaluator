import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { FredApplicationProvider } from "./FredApplicationProvider";
import i18n from "../../shared/i18n";
import { fakeFredClient, initialContext } from "../../test/fakeFredClient";

const emptyList = () => Response.json({ evaluations: [], total: 0 });

function renderApp(fake: ReturnType<typeof fakeFredClient>) {
  const factory = vi.fn(() => fake.client);
  const view = render(
    <FredApplicationProvider
      hostOrigin="https://fred.example"
      clientFactory={factory}
    >
      <App />
    </FredApplicationProvider>,
  );
  return { factory, view };
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

describe("Fred application provider", () => {
  it("connects as the evaluation application and follows theme and locale", async () => {
    const fake = fakeFredClient(emptyList);
    const { factory, view } = renderApp(fake);
    expect(factory).toHaveBeenCalledWith({
      hostOrigin: "https://fred.example",
      applicationId: "evaluation",
    });
    await screen.findByRole("heading", { name: "Evaluations" });
    expect(document.querySelector(".evaluation-shell")).toHaveAttribute(
      "data-theme",
      "dark",
    );

    act(() =>
      fake.emitContext({ ...initialContext, theme: "light", locale: "fr-FR" }),
    );
    await screen.findByRole("heading", { name: "Évaluations" });
    expect(document.querySelector(".evaluation-shell")).toHaveAttribute(
      "data-theme",
      "light",
    );

    view.unmount();
    expect(fake.contexts.size).toBe(0);
    expect(fake.routes.size).toBe(0);
    expect(fake.client.dispose).toHaveBeenCalledOnce();
  });

  it("reloads the list when the host switches team", async () => {
    const fake = fakeFredClient(emptyList);
    renderApp(fake);
    await screen.findByText("No evaluation yet for this team.");
    expect(fake.request).toHaveBeenCalledTimes(1);
    act(() =>
      fake.emitContext({
        ...initialContext,
        team: { id: "team-two", name: "Team Two", isPersonal: false },
      }),
    );
    await waitFor(() => expect(fake.request).toHaveBeenCalledTimes(2));
  });

  it("maps an unknown host subpath back to the root without echoing it", async () => {
    const fake = fakeFredClient(emptyList, {
      ...initialContext,
      route: { ...initialContext.route, subPath: "nowhere" },
    });
    renderApp(fake);
    fireEvent.click(await screen.findByRole("button", { name: "Back" }));
    expect(fake.client.navigate).toHaveBeenCalledExactlyOnceWith("");
    await screen.findByRole("heading", { name: "Evaluations" });
  });

  it("surfaces a connection failure instead of an endless spinner", async () => {
    const fake = fakeFredClient(emptyList);
    fake.client.connect = vi
      .fn()
      .mockRejectedValue(new Error("connection timed out"));
    renderApp(fake);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "connection timed out",
      ),
    );
    expect(screen.queryByText("Connecting to Fred…")).not.toBeInTheDocument();
  });
});
