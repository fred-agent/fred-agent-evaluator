import { useTranslation } from "react-i18next";
import { Button } from "@fred-oss/ui";
import { describeError } from "./presentation";

export function LoadFailure({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div role="alert" className="evaluation-error">
      <p>{describeError(error, t)}</p>
      <Button color="primary" variant="outlined" size="small" onClick={onRetry}>
        {t("retry")}
      </Button>
    </div>
  );
}
