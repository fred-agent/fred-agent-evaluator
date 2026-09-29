import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, IconButton, TextInput } from "@fred-oss/ui";
import { useAppNavigate } from "../../app/router";
import { DOCUMENT_ERRORS, MAX_CASES, parseDocument } from "./document";
import { describeError } from "./presentation";
import { useEvaluationApi } from "./useEvaluationApi";

interface Row {
  key: number;
  input: string;
  expected: string;
}

let nextKey = 0;
const emptyRow = (): Row => ({ key: nextKey++, input: "", expected: "" });

/** Create an evaluation, from a JSON document or typed in case by case. */
export function EvaluationCreatePage() {
  const { t } = useTranslation();
  const api = useEvaluationApi();
  const go = useAppNavigate();
  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const [author, setAuthor] = useState("");
  const [rows, setRows] = useState<Row[]>(() => [emptyRow()]);
  const [sourceFilename, setSourceFilename] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const cases = rows.filter((row) => row.input.trim());
  const valid =
    name.trim() !== "" && cases.length > 0 && cases.length <= MAX_CASES;

  const importFile = async (file: File) => {
    setImportError(null);
    try {
      const doc = parseDocument(await file.text());
      setName(doc.name);
      setVersion(doc.version);
      setAuthor(doc.author);
      setRows(
        doc.cases.map((c) => ({
          key: nextKey++,
          input: c.input,
          expected: c.expected_output ?? "",
        })),
      );
      setSourceFilename(file.name);
    } catch (reason) {
      const code =
        reason instanceof Error && DOCUMENT_ERRORS.has(reason.message)
          ? reason.message
          : "notJson";
      setImportError(t(`create.importErrors.${code}`, { max: MAX_CASES }));
    }
  };

  const update = (key: number, patch: Partial<Row>) =>
    setRows((current) =>
      current.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    );

  const submit = async () => {
    if (!valid) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.createEvaluation({
        name: name.trim(),
        version: version.trim() || null,
        author: author.trim() || null,
        origin: sourceFilename ? "upload" : "manual",
        source_filename: sourceFilename,
        cases: cases.map((row) => ({
          input: row.input,
          expected_output: row.expected.trim() ? row.expected : null,
        })),
      });
      go(`evaluations/${created.evaluation_id}`);
    } catch (reason) {
      setError(describeError(reason, t));
      setSubmitting(false);
    }
  };

  return (
    <section aria-labelledby="create-title">
      <header className="evaluation-toolbar">
        <h1 id="create-title">{t("evaluations.new")}</h1>
      </header>
      <form
        className="evaluation-form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="evaluation-file">
          <span>{t("create.import")}</span>
          <input
            type="file"
            accept="application/json,.json"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void importFile(file);
            }}
          />
        </label>
        {importError && (
          <p role="alert" className="evaluation-error">
            {importError}
          </p>
        )}
        <TextInput
          label={t("evaluations.name")}
          value={name}
          required
          maxLength={255}
          onChange={(event) => setName(event.target.value)}
        />
        <TextInput
          label={t("evaluations.version")}
          explanation={t("create.versionHint")}
          value={version}
          maxLength={100}
          onChange={(event) => setVersion(event.target.value)}
        />
        <TextInput
          label={t("evaluations.author")}
          value={author}
          maxLength={255}
          onChange={(event) => setAuthor(event.target.value)}
        />
        <fieldset className="evaluation-fieldset">
          <legend>
            {t("evaluations.caseCount", { count: cases.length })} (≤ {MAX_CASES}
            )
          </legend>
          {rows.map((row, index) => (
            <div key={row.key} className="evaluation-case-row">
              <label>
                <span>{t("create.caseInput", { n: index + 1 })}</span>
                <textarea
                  value={row.input}
                  rows={2}
                  onChange={(event) =>
                    update(row.key, { input: event.target.value })
                  }
                />
              </label>
              <label>
                <span>{t("cases.expected")}</span>
                <textarea
                  value={row.expected}
                  rows={2}
                  onChange={(event) =>
                    update(row.key, { expected: event.target.value })
                  }
                />
              </label>
              <IconButton
                variant="icon"
                color="on-surface-retreat"
                size="small"
                icon={{ type: "delete" }}
                aria-label={t("create.removeCase", { n: index + 1 })}
                disabled={rows.length === 1}
                onClick={() =>
                  setRows((current) => current.filter((r) => r.key !== row.key))
                }
              />
            </div>
          ))}
          <div>
            <Button
              type="button"
              color="primary"
              variant="text"
              size="small"
              disabled={rows.length >= MAX_CASES}
              onClick={() => setRows((current) => [...current, emptyRow()])}
            >
              {t("create.addCase")}
            </Button>
          </div>
        </fieldset>
        {error && (
          <p role="alert" className="evaluation-error">
            {error}
          </p>
        )}
        <div className="evaluation-actions">
          <Button
            type="button"
            color="on-surface"
            variant="text"
            size="small"
            onClick={() => go("")}
          >
            {t("cancel")}
          </Button>
          <Button
            type="submit"
            color="primary"
            variant="filled"
            size="small"
            disabled={!valid || submitting}
          >
            {submitting ? t("create.creating") : t("create.create")}
          </Button>
        </div>
      </form>
    </section>
  );
}
