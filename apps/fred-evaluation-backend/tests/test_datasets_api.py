"""POST/GET /evaluation/v1/evaluations — evaluation catalog surface.

Drives the real FastAPI route (`datasets/api.py` -> `datasets/service.py`) over
an in-process ASGI transport (no sockets, no real DB, no Temporal). The
`EvaluationStore` is faked with a plain in-memory dict so persistence assertions
don't depend on a live Postgres; the Control Plane client is faked so
team-membership checks are deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fred_core import KeycloakUser, get_config, get_current_user

from fred_evaluation_backend.evaluations.api import (
    _get_control_plane_client,
    _get_evaluation_catalog_store,
    _get_run_store,
    build_evaluation_catalog_router,
)
from fred_evaluation_backend.execution.evaluator_errors import (
    normalize_unstructured_auth_error,
)


class _InMemoryEvaluationStore:
    """Real create/list/get semantics, backed by a dict instead of Postgres."""

    def __init__(self) -> None:
        self.rows: dict[str, SimpleNamespace] = {}

    async def create_evaluation(self, **kwargs):
        row = SimpleNamespace(created_at=datetime.now(timezone.utc), **kwargs)
        self.rows[kwargs["evaluation_id"]] = row
        return row

    async def get_evaluation(self, evaluation_id: str):
        return self.rows.get(evaluation_id)

    def _team_evaluations(self, team_id: str, q: str | None):
        rows = [row for row in self.rows.values() if row.team_id == team_id]
        if q:
            rows = [r for r in rows if q.lower() in r.name.lower()]
        return rows

    async def list_evaluations_by_team(
        self,
        team_id: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        sort: str | None = None,
        q: str | None = None,
    ):
        rows = sorted(
            self._team_evaluations(team_id, q),
            key=lambda r: r.created_at,
            reverse=True,
        )
        return rows[offset:] if limit is None else rows[offset : offset + limit]

    async def count_evaluations_by_team(self, team_id: str, *, q: str | None = None):
        return len(self._team_evaluations(team_id, q))

    async def get_latest_version_number(self, team_id: str, name: str) -> int:
        numbers = []
        for r in self.rows.values():
            if r.team_id == team_id and r.name == name:
                try:
                    numbers.append(int(str(r.version).lstrip("v")))
                except ValueError:
                    continue  # a declared version ("1.0.0") is not in the v<n> series
        return max(numbers, default=0)

    async def version_exists(self, team_id: str, name: str, version: str) -> bool:
        return any(
            r.team_id == team_id and r.name == name and r.version == version
            for r in self.rows.values()
        )

    async def delete_evaluation(self, evaluation_id: str) -> bool:
        return self.rows.pop(evaluation_id, None) is not None


class _InMemoryRunStore:
    """Just enough of RunStore for the evaluation-delete cascade."""

    def __init__(self, runs: list[SimpleNamespace] | None = None) -> None:
        self.runs = runs or []
        self.deleted: list[str] = []

    async def list_runs_by_evaluation(self, evaluation_id: str):
        return [r for r in self.runs if r.evaluation_id == evaluation_id]

    async def delete_run(self, run_id: str) -> bool:
        self.deleted.append(run_id)
        self.runs = [r for r in self.runs if r.run_id != run_id]
        return True


class _MemberControlPlaneClient:
    async def get_team(self, *, team_id: str, auth):
        return SimpleNamespace(team_id=team_id, is_member=True)


class _NonMemberControlPlaneClient:
    async def get_team(self, *, team_id: str, auth):
        return SimpleNamespace(team_id=team_id, is_member=False)


def _build_app(
    *,
    cp_client,
    store: _InMemoryEvaluationStore | None = None,
    run_store: _InMemoryRunStore | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(build_evaluation_catalog_router())
    app.add_exception_handler(HTTPException, normalize_unstructured_auth_error)
    app.dependency_overrides[get_current_user] = lambda: KeycloakUser(
        uid="alice", username="alice", roles=[], email="alice@test.example"
    )
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        security=SimpleNamespace(user=SimpleNamespace(enabled=True))
    )
    app.dependency_overrides[_get_evaluation_catalog_store] = lambda: (
        store or _InMemoryEvaluationStore()
    )
    app.dependency_overrides[_get_control_plane_client] = lambda: cp_client
    app.dependency_overrides[_get_run_store] = lambda: run_store or _InMemoryRunStore()
    return app


@pytest.mark.asyncio
async def test_evaluation_created_via_post_persists_independently_of_any_run() -> None:
    """A created evaluation is standalone; it does not depend on a run to exist."""
    store = _InMemoryEvaluationStore()
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/evaluations",
            json={
                "team_id": "team-1",
                "name": "usage-arxivai",
                "origin": "manual",
                "cases": [{"input": "q1", "expected_output": "a1"}],
            },
            headers={"Authorization": "Bearer alice-token"},
        )
        assert create_resp.status_code == 201
        evaluation_id = create_resp.json()["evaluation_id"]

        list_resp = await client.get(
            "/evaluations",
            params={"team_id": "team-1"},
            headers={"Authorization": "Bearer alice-token"},
        )

    assert list_resp.status_code == 200
    ids = [d["evaluation_id"] for d in list_resp.json()["evaluations"]]
    assert evaluation_id in ids
    assert evaluation_id in store.rows  # persisted, not just echoed back


@pytest.mark.asyncio
async def test_list_evaluations_paginates_searches_and_totals() -> None:
    """The list endpoint honours `q` (name search), `limit`/`offset`, and returns the
    full filtered `total` — not the length of the returned page."""
    store = _InMemoryEvaluationStore()
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for name in ("alpha-set", "beta-set", "alpha-golden"):
            resp = await client.post(
                "/evaluations",
                json={
                    "team_id": "team-1",
                    "name": name,
                    "origin": "manual",
                    "cases": [{"input": "q1", "expected_output": "a1"}],
                },
                headers={"Authorization": "Bearer alice-token"},
            )
            assert resp.status_code == 201

        # Search narrows to the two "alpha*" names; total reflects the filtered set.
        search = await client.get(
            "/evaluations",
            params={"team_id": "team-1", "q": "alpha"},
            headers={"Authorization": "Bearer alice-token"},
        )
        assert search.status_code == 200
        body = search.json()
        assert body["total"] == 2
        assert {e["name"] for e in body["evaluations"]} == {"alpha-set", "alpha-golden"}

        # A page smaller than the result set returns the page but the full total.
        page = await client.get(
            "/evaluations",
            params={"team_id": "team-1", "limit": 1},
            headers={"Authorization": "Bearer alice-token"},
        )
        assert page.status_code == 200
        page_body = page.json()
        assert page_body["total"] == 3
        assert len(page_body["evaluations"]) == 1


@pytest.mark.asyncio
async def test_name_is_user_supplied_and_first_import_is_v1() -> None:
    """EVAL-05: the name comes from the user (not derived), and a brand-new name
    starts at v1. Completeness is still derived from the cases."""
    app = _build_app(cp_client=_MemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/evaluations",
            json={
                "team_id": "team-1",
                "name": "golden-set",
                "origin": "upload",
                "cases": [
                    {"input": "q1", "expected_output": "a1"},
                    {"input": "q2", "expected_output": "a2"},
                ],
            },
            headers={"Authorization": "Bearer alice-token"},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "golden-set"
    assert body["version"] == "v1"
    # EVAL-06: the document declares no author here, so `author` is None while the
    # verified uploader is exposed separately as `created_by`.
    assert body["author"] is None
    assert body["created_by"] == "alice"
    # Every case has an expected_output -> complete.
    assert body["completeness"] == "complete"
    assert body["case_count"] == 2


@pytest.mark.asyncio
async def test_reimporting_same_name_creates_next_version_and_new_id() -> None:
    """EVAL-05 (§8.5): re-importing the same name in the same team creates v2, a
    distinct row with its own id. Different name stays at v1."""
    store = _InMemoryEvaluationStore()
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store)
    transport = httpx.ASGITransport(app=app)

    async def _create(name: str) -> dict:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/evaluations",
                json={
                    "team_id": "team-1",
                    "name": name,
                    "origin": "manual",
                    "cases": [{"input": "q1"}],
                },
                headers={"Authorization": "Bearer alice-token"},
            )
        assert resp.status_code == 201
        return resp.json()

    first = await _create("usage-arxivai")
    second = await _create("usage-arxivai")
    other = await _create("usage-rag")

    assert first["version"] == "v1"
    assert second["version"] == "v2"  # same name -> next version
    assert second["evaluation_id"] != first["evaluation_id"]  # its own row
    assert other["version"] == "v1"  # a different name is independent


@pytest.mark.asyncio
async def test_non_member_cannot_create_or_list_team_datasets() -> None:
    app = _build_app(cp_client=_NonMemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/evaluations",
            json={
                "team_id": "team-1",
                "name": "x",
                "origin": "manual",
                "cases": [{"input": "q1"}],
            },
            headers={"Authorization": "Bearer alice-token"},
        )
        list_resp = await client.get(
            "/evaluations",
            params={"team_id": "team-1"},
            headers={"Authorization": "Bearer alice-token"},
        )

    assert create_resp.status_code == 403
    assert list_resp.status_code == 403


# ── EVAL-06: self-describing document (name / version / author) ───────────────


def _doc(**overrides) -> dict:
    body = {
        "team_id": "team-1",
        "name": "golden-set",
        "origin": "upload",
        "cases": [{"input": "q1", "expected_output": "a1"}],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_declared_version_is_kept_verbatim_instead_of_being_reassigned() -> None:
    """A document that states its own version owns its identity: the server must
    store "1.0.0" as-is rather than overwriting it with the v<n> sequence."""
    app = _build_app(cp_client=_MemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/evaluations",
            json=_doc(version="1.0.0"),
            headers={"Authorization": "Bearer alice-token"},
        )
    assert resp.status_code == 201
    assert resp.json()["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_reusing_a_declared_version_is_rejected_as_a_conflict() -> None:
    """(team, name, version) is an identity — re-uploading the same version must
    not silently create a second, indistinguishable evaluation."""
    store = _InMemoryEvaluationStore()
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/evaluations",
            json=_doc(version="1.0.0"),
            headers={"Authorization": "Bearer alice-token"},
        )
        second = await client.post(
            "/evaluations",
            json=_doc(version="1.0.0"),
            headers={"Authorization": "Bearer alice-token"},
        )
    assert first.status_code == 201
    assert second.status_code == 409
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_declared_version_does_not_disturb_the_auto_increment_sequence() -> None:
    """Mixing a semver document with auto-versioned ones must not make the next
    auto version collide or jump: "1.0.0" is simply not part of the v<n> series."""
    store = _InMemoryEvaluationStore()
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        auto_first = await client.post(
            "/evaluations", json=_doc(), headers={"Authorization": "Bearer t"}
        )
        await client.post(
            "/evaluations",
            json=_doc(version="1.0.0"),
            headers={"Authorization": "Bearer t"},
        )
        auto_second = await client.post(
            "/evaluations", json=_doc(), headers={"Authorization": "Bearer t"}
        )
    assert auto_first.json()["version"] == "v1"
    assert auto_second.json()["version"] == "v2"


@pytest.mark.asyncio
async def test_declared_author_is_kept_and_never_replaces_the_verified_uploader() -> (
    None
):
    """`author` is free-form provenance from the document; `created_by` stays the
    authenticated identity, so a document cannot claim to be someone else."""
    app = _build_app(cp_client=_MemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/evaluations",
            json=_doc(author="Data Team"),
            headers={"Authorization": "Bearer alice-token"},
        )
    body = resp.json()
    assert body["author"] == "Data Team"
    assert body["created_by"] == "alice"


# ── EVAL-06: DELETE /evaluations/{id} ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_deleting_an_evaluation_also_removes_its_runs() -> None:
    """evaluation_run.evaluation_id is a plain FK with no ON DELETE, so the runs
    must be removed first — otherwise the delete would fail on integrity."""
    store = _InMemoryEvaluationStore()
    runs = _InMemoryRunStore(
        [
            SimpleNamespace(
                run_id="run-1", evaluation_id="e1", operational_state="completed"
            ),
            SimpleNamespace(
                run_id="run-2", evaluation_id="e1", operational_state="failed"
            ),
            SimpleNamespace(
                run_id="run-9", evaluation_id="other", operational_state="completed"
            ),
        ]
    )
    store.rows["e1"] = SimpleNamespace(evaluation_id="e1", team_id="team-1")
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store, run_store=runs)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            "/evaluations/e1", headers={"Authorization": "Bearer alice-token"}
        )
    assert resp.status_code == 204
    assert "e1" not in store.rows
    assert sorted(runs.deleted) == ["run-1", "run-2"]  # the other run is untouched


@pytest.mark.asyncio
async def test_deleting_is_refused_while_one_of_its_runs_is_still_running() -> None:
    """Same guard as DELETE /runs/{id}: results being produced are not destroyed
    underneath the worker."""
    store = _InMemoryEvaluationStore()
    runs = _InMemoryRunStore(
        [
            SimpleNamespace(
                run_id="run-1", evaluation_id="e1", operational_state="running"
            )
        ]
    )
    store.rows["e1"] = SimpleNamespace(evaluation_id="e1", team_id="team-1")
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store, run_store=runs)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            "/evaluations/e1", headers={"Authorization": "Bearer alice-token"}
        )
    assert resp.status_code == 409
    assert "e1" in store.rows
    assert runs.deleted == []


@pytest.mark.asyncio
async def test_non_member_cannot_delete_another_teams_evaluation() -> None:
    """Membership is resolved from the stored row's team, not from anything the
    caller supplies, so the check cannot be side-stepped."""
    store = _InMemoryEvaluationStore()
    store.rows["e1"] = SimpleNamespace(evaluation_id="e1", team_id="team-1")
    app = _build_app(
        cp_client=_NonMemberControlPlaneClient(),
        store=store,
        run_store=_InMemoryRunStore(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            "/evaluations/e1", headers={"Authorization": "Bearer mallory-token"}
        )
    assert resp.status_code == 403
    assert "e1" in store.rows


@pytest.mark.asyncio
async def test_deleting_an_unknown_evaluation_is_a_404() -> None:
    app = _build_app(cp_client=_MemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            "/evaluations/nope", headers={"Authorization": "Bearer alice-token"}
        )
    assert resp.status_code == 404


# ── EVAL-06: malformed documents are refused, never half-accepted ─────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "body"),
    [
        # The pre-EVAL-06 format was a bare array of cases. It is not supported and
        # must fail at the boundary rather than be coerced into something partial.
        ("legacy bare array", [{"input": "q1"}]),
        (
            "legacy inline dataset key",
            {
                "team_id": "t",
                "name": "n",
                "origin": "upload",
                "dataset": {"cases": [{"input": "q"}]},
            },
        ),
        # A typo must not be silently dropped: "expectd_output" would cost the case
        # its reference answer and quietly demote the evaluation to `minimal`.
        (
            "typo in a case field",
            {
                "team_id": "t",
                "name": "n",
                "origin": "upload",
                "cases": [{"input": "q", "expectd_output": "a"}],
            },
        ),
        (
            "typo in a document field",
            {
                "team_id": "t",
                "name": "n",
                "origin": "upload",
                "cases": [{"input": "q"}],
                "autor": "X",
            },
        ),
        ("no cases at all", {"team_id": "t", "name": "n", "origin": "upload"}),
        ("empty cases", {"team_id": "t", "name": "n", "origin": "upload", "cases": []}),
        (
            "case without input",
            {
                "team_id": "t",
                "name": "n",
                "origin": "upload",
                "cases": [{"expected_output": "a"}],
            },
        ),
        (
            "input of the wrong type",
            {
                "team_id": "t",
                "name": "n",
                "origin": "upload",
                "cases": [{"input": 123}],
            },
        ),
        (
            "missing name",
            {"team_id": "t", "origin": "upload", "cases": [{"input": "q"}]},
        ),
        (
            "empty name",
            {"team_id": "t", "name": "", "origin": "upload", "cases": [{"input": "q"}]},
        ),
        (
            "unsupported origin",
            {"team_id": "t", "name": "n", "origin": "csv", "cases": [{"input": "q"}]},
        ),
        (
            "over the 200-case ceiling",
            {
                "team_id": "t",
                "name": "n",
                "origin": "upload",
                "cases": [{"input": "q"}] * 201,
            },
        ),
    ],
)
async def test_malformed_documents_are_rejected_and_nothing_is_persisted(
    label: str, body: object
) -> None:
    store = _InMemoryEvaluationStore()
    app = _build_app(cp_client=_MemberControlPlaneClient(), store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/evaluations", json=body, headers={"Authorization": "Bearer alice-token"}
        )
    assert resp.status_code == 422, f"{label} should be refused, got {resp.status_code}"
    assert store.rows == {}, f"{label} left something persisted"


@pytest.mark.asyncio
async def test_rejection_names_the_offending_field_so_a_ui_can_point_at_it() -> None:
    """A refusal is only 'clean' if the author can tell what to fix: the error must
    locate the exact case index and key, not just say the payload is invalid."""
    app = _build_app(cp_client=_MemberControlPlaneClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/evaluations",
            json={
                "team_id": "t",
                "name": "n",
                "origin": "upload",
                "cases": [{"input": "q1"}, {"input": "q2", "expectd_output": "a"}],
            },
            headers={"Authorization": "Bearer alice-token"},
        )
    assert resp.status_code == 422
    assert ["body", "cases", 1, "expectd_output"] in [
        d["loc"] for d in resp.json()["detail"]
    ]
