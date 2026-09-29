import type { ApplicationService } from "../../shared/api/applicationService";
import type { EvaluationList } from "../../shared/api/schemas";

/** GET /teams/{team_id}/evaluations — newest first; the team is the host's. */
export async function listEvaluations(
  service: ApplicationService,
  { limit = 50 }: { limit?: number } = {},
): Promise<EvaluationList> {
  const query = new URLSearchParams({
    limit: String(limit),
    sort: "created_at:desc",
  });
  const list = await service.request<EvaluationList>(`evaluations?${query}`);
  if (list === null) throw new Error("Empty evaluation list response");
  return list;
}
