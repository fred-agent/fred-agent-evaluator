# Wiki search ablation (W0)

Evaluation fixture only. `without_search.patch` removes `wiki_search` from both
tool lists and its search-before-read guidance. The browsing instruction, title
index, rules, reading, proposals, errors and admission stay unchanged. There is
no product switch or replacement capability. Never apply this patch to a shared
checkout or deployment.

`manifest.json` pins Fred's commit, original/patched source and patch SHA-256.
Source drift is rejected before `git apply --check` and `git apply` operate in a
disposable archive. The tests require a clean checkout at that commit. They reuse
its installed Wiki package dependencies, without dependency installation or sync.
The default evaluator suite skips these checks when `FRED_REPO` is unset.

From the evaluator repository root:

```bash
export FRED_REPO=/home/dimi/Work/weaver/fred
"$FRED_REPO/libs/capabilities/fred-capability-team-wiki/.venv/bin/python" -m pytest \
  libs/fred-deepeval-cli/tests/fixtures/wiki_search_ablation/test_ablation.py \
  -q --disable-socket --allow-unix-socket
```

The checks use the native fake port and invoke the real tool executor without a
model: the baseline rejects a `wiki_search` call in both modes. They compare exact
tool order, schemas, descriptions and composed prompts, and read the same page in
both variants. The native package's `make test` and `make code-quality` run in each
temporary copy (`make -o dev`, `UV_NO_SYNC=1`, `UV_OFFLINE=1`); imports are checked
to resolve to that copy. Logs are retained as `test.log` and `code-quality.log`
under pytest's temporary `current0` and `ablated0` directories.

Current suite: 122 tests. Ablated suite: 90 applicable tests, with 32 current-search
contract cases explicitly deselected: search behavior/run-stop scenarios, the
search guidance assertion and two inventories that require search. No native test
is edited or marked as an expected failure. The fixture checks replace the two
inventories and guidance assertion with the exact intended delta; native reading,
proposals, registry, error and non-search run-stop checks still run unchanged.

`build_sha256` is deliberately null: no build, deployed comparison, model call or
campaign has happened. Record actual artifact digests for both variants, runtime,
model settings, rights and frozen corpus before a separately authorized run.
Offline checks establish the ablation, not model quality or live admission.
