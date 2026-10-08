import { useTranslation } from "react-i18next";
import type { DataTableLabels } from "@fred-oss/ui";

export function useTableLabels(): DataTableLabels {
  const { t } = useTranslation();
  return {
    pagination: {
      totalItems: (count) => t("ui.items", { count }),
      itemsPerPage: t("ui.perPage"),
      pageNumber: (page, pages) => t("ui.page", { page, pages }),
      first: t("ui.first"),
      prev: t("ui.previous"),
      next: t("ui.next"),
      last: t("ui.last"),
    },
  };
}
