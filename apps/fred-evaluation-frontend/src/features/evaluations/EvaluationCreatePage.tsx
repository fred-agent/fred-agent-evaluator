import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  IconButton,
  TextInput,
  TextArea,
  SelectableCard,
  FileDropzone,
  PageHeader,
  useToast,
} from "@fred-oss/ui";
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
  const toast = useToast();
  const [mode, setMode] = useState<"manual" | "upload">("manual");
  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const [author, setAuthor] = useState("");
  const [rows, setRows] = useState<Row[]>(() => [emptyRow()]);
  const [sourceFilename, setSourceFilename] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);

  const cases = rows.filter((row) => row.input.trim());
  const valid =
    name.trim() !== "" &&
    cases.length > 0 &&
    cases.length <= MAX_CASES &&
    (mode === "manual" || sourceFilename !== null);

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

    try {
      const created = await api.createEvaluation({
        name: name.trim(),
        version: version.trim() || null,
        author: author.trim() || null,
        origin: mode,
        source_filename: mode === "upload" ? sourceFilename : null,
        cases: cases.map((row) => ({
          input: row.input,
          expected_output: row.expected.trim() ? row.expected : null,
        })),
      });
      toast.showSuccess({ summary: t("ui.created") });
      go(`evaluations/${created.evaluation_id}`);
    } catch (reason) {
      toast.showError({ summary: describeError(reason, t) });
      setSubmitting(false);
    }
  };

  return (
    <section className="evaluation-create-page">
      <PageHeader title={t("evaluations.new")} />
      <form
        className="evaluation-form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <div className="evaluation-columns">
          <SelectableCard
            selected={mode === "upload"}
            title={t("create.import")}
            description={t("ui.importHint")}
            onSelect={() => setMode("upload")}
          />
          <SelectableCard
            selected={mode === "manual"}
            title={t("ui.manual")}
            description={t("ui.manualHint")}
            onSelect={() => setMode("manual")}
          />
        </div>
        {mode === "upload" && (
          <div>
            <FileDropzone
              accept="application/json,.json"
              hint={t("create.import")}
              subHint={t("ui.importHint")}
              error={importError ?? undefined}
              onFile={(file) => void importFile(file)}
            />
            {sourceFilename && (
              <p>
                {sourceFilename} · {t("ui.imported", { count: cases.length })}
              </p>
            )}
          </div>
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
            <section
              key={row.key}
              className="evaluation-case-card"
              aria-labelledby={`case-${row.key}-title`}
            >
              <div className="evaluation-case-header">
                <h3 id={`case-${row.key}-title`}>
                  {t("create.caseTitle", { n: index + 1 })}
                </h3>
                <IconButton
                  variant="icon"
                  color="on-surface-retreat"
                  size="small"
                  icon={{ type: "delete" }}
                  aria-label={t("create.removeCase", { n: index + 1 })}
                  disabled={rows.length === 1}
                  onClick={() =>
                    setRows((current) =>
                      current.filter((r) => r.key !== row.key),
                    )
                  }
                />
              </div>
              <div className="evaluation-case-row">
                <TextArea
                  label={t("create.caseInput", { n: index + 1 })}
                  value={row.input}
                  rows={5}
                  className="evaluation-case-field"
                  onChange={(event) =>
                    update(row.key, { input: event.target.value })
                  }
                />
                <TextArea
                  label={t("cases.expected")}
                  value={row.expected}
                  rows={5}
                  className="evaluation-case-field"
                  onChange={(event) =>
                    update(row.key, { expected: event.target.value })
                  }
                />
              </div>
            </section>
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
