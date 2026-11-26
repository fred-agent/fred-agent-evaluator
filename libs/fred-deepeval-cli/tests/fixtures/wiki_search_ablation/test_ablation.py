"""Offline W0 fixture; never applies the patch to FRED_REPO itself."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict, cast

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool


class _Manifest(TypedDict):
    fred_commit: str
    source_path: str
    source_sha256: str
    ablated_source_sha256: str
    patch_sha256: str


# Only the surface exercised below is shared by the dynamically loaded variants.
class _Capability(Protocol):
    def tools(self, ctx: object) -> Sequence[BaseTool]: ...
    def middleware(self, ctx: object) -> Sequence[object]: ...


class _CapabilityModule(Protocol):
    def TeamWikiCapability(self) -> _Capability: ...


class _FakePort(Protocol):
    search_calls: list[object]


class _PortFactory(Protocol):
    def __call__(
        self,
        *,
        pages: tuple[object, ...] = (),
        content: str = "",
        rules: str = "",
    ) -> _FakePort: ...


_Call = Callable[[_FakePort, str, dict[str, str], dict[str, BaseTool]], ToolMessage]


@dataclass(frozen=True)
class _NativeHelpers:
    fake_port: _PortFactory
    page: Callable[[str, str], object]
    context: Callable[[_FakePort, str], object]
    call: _Call

    @classmethod
    def from_module(cls, module: object) -> _NativeHelpers:
        # Private helpers belong to the pinned native test module, not a public SDK.
        return cls(
            fake_port=cast(_PortFactory, getattr(module, "_FakePort")),
            page=cast(Callable[[str, str], object], getattr(module, "_page")),
            context=cast(Callable[[_FakePort, str], object], getattr(module, "_ctx")),
            call=cast(_Call, getattr(module, "_call")),
        )


async def _compose(middleware: object) -> str:
    compose = cast(Callable[[], Awaitable[str]], getattr(middleware, "_compose"))
    return await compose()


_Modules = tuple[_CapabilityModule, _CapabilityModule, _NativeHelpers]

HERE = Path(__file__).parent
MANIFEST = cast(_Manifest, json.loads((HERE / "manifest.json").read_text()))
PACKAGE = Path("libs/capabilities/fred-capability-team-wiki")
GUIDANCE = (
    "Search before you read: use wiki_search to find published ordinary "
    "pages by their content, optionally filtered by type or tag, then "
    "wiki_read_page on the returned path. Search excludes files and rules; "
)
# These current-contract tests require an exposed search tool. The exact surface
# and remaining prompt are checked below for the ablated variant instead.
ABLATED_SELECTION = (
    "not search and not test_read_mode_exposes_no_way_to_change_the_wiki "
    "and not test_read_write_mode_adds_proposing_and_publishing_only"
)


def _run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> bytes:
    return subprocess.check_output(args, cwd=cwd, env=env, stderr=subprocess.STDOUT)


def _verify_source(root: Path) -> None:
    actual = hashlib.sha256((root / MANIFEST["source_path"]).read_bytes()).hexdigest()
    if actual != MANIFEST["source_sha256"]:
        raise ValueError("Pinned Wiki source differs; refuse the ablation")


@pytest.fixture(scope="module")
def variants(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Path]]:
    configured = os.environ.get("FRED_REPO")
    if not configured:
        pytest.skip("Set FRED_REPO to the pinned Weaver checkout for W0 offline checks")
    repo = Path(configured).resolve()
    assert (
        _run("git", "rev-parse", "HEAD", cwd=repo).decode().strip()
        == MANIFEST["fred_commit"]
    )
    _verify_source(repo)
    assert _run("git", "status", "--porcelain", cwd=repo) == b""
    patch = HERE / "without_search.patch"
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == MANIFEST["patch_sha256"]
    archive = _run(
        "git",
        "archive",
        MANIFEST["fred_commit"],
        str(PACKAGE),
        "scripts/makefiles",
        "ruff.toml",
        cwd=repo,
    )
    roots = {}
    for name in ("current", "ablated"):
        root = tmp_path_factory.mktemp(name)
        with tarfile.open(fileobj=io.BytesIO(archive)) as files:
            files.extractall(root, filter="data")
        _verify_source(root)
        if name == "ablated":
            _ = _run("git", "apply", "--check", str(patch), cwd=root)
            _ = _run("git", "apply", str(patch), cwd=root)
            assert (
                hashlib.sha256(
                    (root / MANIFEST["source_path"]).read_bytes()
                ).hexdigest()
                == MANIFEST["ablated_source_sha256"]
            )
        # Native quality scans require a Git file inventory; no commit/worktree.
        _ = _run("git", "init", "--quiet", cwd=root)
        _ = _run("git", "add", ".", cwd=root)
        (root / PACKAGE / ".venv").symlink_to(
            repo / PACKAGE / ".venv", target_is_directory=True
        )
        for dependency in ("fred-pod", "fred-core", "fred-sdk", "fred-runtime"):
            (root / "libs" / dependency).symlink_to(
                repo / "libs" / dependency, target_is_directory=True
            )
        roots[name] = root
    yield roots
    _verify_source(repo)
    assert _run("git", "status", "--porcelain", cwd=repo) == b""


def _load(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def modules(variants: dict[str, Path]) -> _Modules:
    return (
        cast(
            _CapabilityModule,
            _load("w0_current", variants["current"] / MANIFEST["source_path"]),
        ),
        cast(
            _CapabilityModule,
            _load("w0_ablated", variants["ablated"] / MANIFEST["source_path"]),
        ),
        _NativeHelpers.from_module(
            _load("w0_native", variants["current"] / PACKAGE / "tests/test_team_wiki.py"),
        ),
    )


def test_source_drift_is_rejected(variants: dict[str, Path], tmp_path: Path) -> None:
    source = tmp_path / MANIFEST["source_path"]
    source.parent.mkdir(parents=True)
    _ = source.write_bytes(
        (variants["current"] / MANIFEST["source_path"]).read_bytes() + b"\n"
    )
    with pytest.raises(ValueError, match="refuse the ablation"):
        _verify_source(tmp_path)


@pytest.mark.parametrize("mode", ["read", "read_write"])
def test_exact_tool_and_prompt_delta(modules: _Modules, mode: str) -> None:
    current, ablated, native = modules
    port = native.fake_port(
        pages=(native.page("a", "Onboarding"),),
        rules="Never guess.",
        content="Evidence.",
    )
    ctx = native.context(port, mode)
    tools = {t.name: t for t in current.TeamWikiCapability().tools(ctx)}
    baseline = {t.name: t for t in ablated.TeamWikiCapability().tools(ctx)}
    assert list(baseline) == [name for name in tools if name != "wiki_search"]
    for name in baseline:
        assert baseline[name].description == tools[name].description
        assert baseline[name].args == tools[name].args
    before = asyncio.run(_compose(current.TeamWikiCapability().middleware(ctx)[0]))
    after = asyncio.run(_compose(ablated.TeamWikiCapability().middleware(ctx)[0]))
    assert before.count(GUIDANCE) == 1
    assert after == before.replace(GUIDANCE, "", 1)
    assert "Never guess." in after and "- Onboarding" in after
    assert "wiki_list_pages browses all pages and files" in after
    result = native.call(port, "wiki_read_page", {"path": "Onboarding"}, baseline)
    assert "Evidence." in result.content
    assert (
        result.content
        == native.call(port, "wiki_read_page", {"path": "Onboarding"}, tools).content
    )


@pytest.mark.parametrize("mode", ["read", "read_write"])
def test_search_cannot_execute(modules: _Modules, mode: str) -> None:
    from langchain_core.messages import AIMessage
    from langgraph.prebuilt import ToolNode
    from langgraph.runtime import Runtime

    _, ablated, native = modules
    port = native.fake_port()
    tools = ablated.TeamWikiCapability().tools(native.context(port, mode))
    node = ToolNode(list(tools))
    assert "wiki_search" not in node.tools_by_name
    result = cast(
        dict[str, list[ToolMessage]],
        asyncio.run(
            node.ainvoke(
                {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "wiki_search",
                                    "args": {"query": "secret"},
                                    "id": "w0-search",
                                }
                            ],
                        )
                    ]
                },
                runtime=Runtime(),
            )
        ),
    )
    assert result["messages"][0].status == "error"
    assert port.search_calls == []


@pytest.mark.parametrize("variant", ["current", "ablated"])
def test_native_package_checks(variants: dict[str, Path], variant: str) -> None:
    root = variants[variant]
    package = root / PACKAGE
    env = dict(os.environ, UV_NO_SYNC="1", UV_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
    # PYTHONPATH prevents editable installs from loading the shared source.
    env["PYTHONPATH"] = str(package)
    imported = _run(
        str(package / ".venv/bin/python"),
        "-c",
        "import fred_capability_team_wiki.wiki.capability as c; print(c.__file__)",
        cwd=package,
        env=env,
    )
    assert Path(imported.decode().strip()).resolve() == root / MANIFEST["source_path"]
    options = "-q"
    if variant == "ablated":
        options += f' -k "{ABLATED_SELECTION}"'
    for target, extra in (("test", [f"PYTEST_OPTS={options}"]), ("code-quality", [])):
        # -o dev reuses installed dependencies without sync/bootstrap/shim writes.
        command = ["make", "-o", "dev", target, *extra]
        result = subprocess.run(
            command,
            cwd=package,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log = root / f"{target}.log"
        _ = log.write_bytes(result.stdout)
        assert result.returncode == 0, (
            f"{variant} {target}: {log}\n{result.stdout.decode()}"
        )
