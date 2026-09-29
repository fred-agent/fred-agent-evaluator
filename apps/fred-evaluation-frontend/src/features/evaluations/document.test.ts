import { describe, expect, it } from "vitest";
import { MAX_CASES, parseDocument } from "./document";

const errorOf = (text: string) => {
  try {
    parseDocument(text);
    return null;
  } catch (error) {
    return (error as Error).message;
  }
};

describe("evaluation document", () => {
  it("reads a document's identity and cases", () => {
    const doc = parseDocument(
      JSON.stringify({
        name: "golden",
        version: "1.0.0",
        author: "Data team",
        cases: [
          {
            input: "q1",
            expected_output: "a1",
            external_id: "c1",
            tags: ["x"],
          },
          { input: "q2" },
        ],
      }),
    );
    expect(doc).toEqual({
      name: "golden",
      version: "1.0.0",
      author: "Data team",
      cases: [
        { input: "q1", expected_output: "a1", external_id: "c1", tags: ["x"] },
        { input: "q2", expected_output: null, external_id: null, tags: [] },
      ],
    });
  });

  it("names what is wrong with a document", () => {
    expect(errorOf("{")).toBe("notJson");
    expect(errorOf("[]")).toBe("notObject");
    expect(errorOf('{"name": "x", "cases": []}')).toBe("noCases");
    expect(errorOf('{"cases": [{"input": " "}]}')).toBe("badCase");
    // A misspelt field would silently lose the expected answer: refused.
    expect(errorOf('{"cases": [{"input": "q", "expectd_output": "a"}]}')).toBe(
      "unknownCaseField",
    );
    const many = {
      cases: Array.from({ length: MAX_CASES + 1 }, () => ({ input: "q" })),
    };
    expect(errorOf(JSON.stringify(many))).toBe("tooManyCases");
  });
});
