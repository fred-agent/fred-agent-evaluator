import type { EvaluationCase } from "../../shared/api/schemas";

export const MAX_CASES = 200;

/** What `parseDocument` can say is wrong; anything else reads as `notJson`. */
export const DOCUMENT_ERRORS = new Set([
  "notJson",
  "notObject",
  "noCases",
  "tooManyCases",
  "badCase",
  "unknownCaseField",
]);

export interface ParsedDocument {
  name: string;
  version: string;
  author: string;
  cases: EvaluationCase[];
}

const CASE_KEYS = new Set(["external_id", "input", "expected_output", "tags"]);

/**
 * Reads an evaluation document (docs/guide/write-a-dataset.md): the file names
 * itself and carries its cases. Checks the shape the form needs; the backend
 * remains the authority and refuses anything else it does not accept.
 */
export function parseDocument(text: string): ParsedDocument {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error("notJson");
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("notObject");
  }
  const doc = value as Record<string, unknown>;
  const text_ = (key: string) =>
    typeof doc[key] === "string" ? (doc[key] as string) : "";
  if (!Array.isArray(doc.cases) || doc.cases.length === 0) {
    throw new Error("noCases");
  }
  if (doc.cases.length > MAX_CASES) throw new Error("tooManyCases");
  const cases = doc.cases.map((raw): EvaluationCase => {
    if (typeof raw !== "object" || raw === null) throw new Error("badCase");
    const item = raw as Record<string, unknown>;
    if (typeof item.input !== "string" || !item.input.trim()) {
      throw new Error("badCase");
    }
    if (Object.keys(item).some((key) => !CASE_KEYS.has(key))) {
      throw new Error("unknownCaseField");
    }
    return {
      input: item.input,
      expected_output:
        typeof item.expected_output === "string" ? item.expected_output : null,
      external_id:
        typeof item.external_id === "string" ? item.external_id : null,
      tags: Array.isArray(item.tags)
        ? item.tags.filter((tag): tag is string => typeof tag === "string")
        : [],
    };
  });
  return {
    name: text_("name"),
    version: text_("version"),
    author: text_("author"),
    cases,
  };
}
