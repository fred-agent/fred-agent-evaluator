# Write an evaluation dataset (JSON)

**For:** the analyst on a Fred team who wants to evaluate their agent.
**Result:** a JSON file of questions (± expected answers) ready to launch a campaign.

> 🇫🇷 Version française : [`write-a-dataset.fr.md`](write-a-dataset.fr.md).

A *dataset* is simply **a list of cases**. A case = a question asked to the agent, and —
if you know it — the reference answer. Nothing else to write: the agent produces its
answers at campaign time, and the platform scores them.

> This is the starting point of every evaluation. You write it **by hand**, up front,
> from what you know about the corpus.

---

## The reference scenario

Your team has ingested the **ArxivAi** corpus (a dozen arXiv papers on AI) and has a
**ReAct agent equipped with the search tool** over that corpus. You want to verify that
it answers correctly, without hallucinating, grounding itself in the documents.

So you will write questions **whose answer is in the corpus**, and give the expected
answer for each.

---

## The shape of a case

```jsonc
{
  "input":           "The question asked to the agent",         // REQUIRED
  "expected_output": "The reference (ideal) answer",            // optional — see below
  "external_id":     "raguard-goal",                            // optional — your readable id
  "tags":            ["rag", "safety"]                           // optional — to filter/group
}
```

| Field             | Required | Role |
| ----------------- | :------: | ---- |
| `input`           |    ✅    | What the agent receives. Write it the way a real user would ask. |
| `expected_output` |    —     | The reference answer. Providing it **unlocks more metrics** (see below). |
| `external_id`     |    —     | A stable, readable id of your own, to find the case back in the results. |
| `tags`            |    —     | Free labels (theme, difficulty…) to sort your cases. |

A dataset is a **JSON array of these cases**.

---

## `minimal` vs `complete` — why fill in `expected_output`

The platform inspects your cases and derives the dataset level:

- **`minimal`** — at least one case has no `expected_output`. Only "reference-free"
  metrics apply (faithfulness, answer relevancy, hallucination…).
- **`complete`** — **every** case has an `expected_output`. All metrics become available,
  including those that compare against the reference (*Contextual Precision*,
  *Contextual Recall*).

| Do you provide `expected_output`? | Level      | Extra metrics unlocked                            |
| --------------------------------- | ---------- | ------------------------------------------------- |
| No (or only some cases)           | `minimal`  | —                                                 |
| Yes, on **every** case            | `complete` | *Contextual Precision*, *Contextual Recall*       |

> The level is **always derived from your cases**, never declared. A single case without
> an expected answer drops the whole dataset back to `minimal`. Details in
> [`../rfc/EVAL-DATASET-RFC.md`](../rfc/EVAL-DATASET-RFC.md) (§9, metric → required-fields matrix).

`expected_output` is a **reference answer**, not a string to match verbatim: the judge
compares meaning, not characters.

---

## Full example — ArxivAi corpus

`arxiv-ai-eval.json` — six `complete` cases, each answerable from one paper in the corpus:

```json
[
  {
    "external_id": "raguard-goal",
    "input": "What problem does the RAGuard approach aim to solve?",
    "expected_output": "Making retrieval-augmented generation (RAG) safer when the retrieved context contains misleading or malicious passages, by filtering/neutralizing those passages before they influence the LLM's answer.",
    "tags": ["rag", "safety"]
  },
  {
    "external_id": "policymaking-eval",
    "input": "What does the study \"What Would an LLM Do?\" set out to measure about LLMs?",
    "expected_output": "The policymaking capabilities of large language models: their ability to reason about and propose public-policy decisions.",
    "tags": ["evaluation", "governance"]
  },
  {
    "external_id": "mcp-medical",
    "input": "Which protocol does the agentic framework for medical concept standardization use?",
    "expected_output": "The Model Context Protocol (MCP), used within an agentic architecture to standardize medical concepts.",
    "tags": ["agent", "healthcare"]
  },
  {
    "external_id": "fama-marketplace",
    "input": "What kind of marketplace is the FaMA assistant designed to operate on?",
    "expected_output": "A consumer-to-consumer (C2C) marketplace, where FaMA acts as an LLM-empowered agentic assistant.",
    "tags": ["agent", "e-commerce"]
  },
  {
    "external_id": "planning-infinite-domains",
    "input": "Which search method is proposed to handle infinite domain parameters in planning?",
    "expected_output": "Best-First Search with Delayed Partial Expansions.",
    "tags": ["planning"]
  },
  {
    "external_id": "cot-space",
    "input": "What does the CoT-Space framework propose?",
    "expected_output": "A theoretical framework for the internal slow-thinking of LLMs, formalized through reinforcement learning.",
    "tags": ["reasoning", "theory"]
  }
]
```

**`minimal` variant:** drop the `expected_output` fields. Useful for a quick first pass,
when you just want to see whether the agent hallucinates or stays faithful to the corpus,
before writing the reference answers.

---

## Writing good questions

- **Answerable from the corpus.** The agent must be able to find the answer via its
  search tool. An out-of-corpus question mostly measures its ability to say "I don't know".
- **One intent per case.** Avoid multi-part questions; they make the score ambiguous.
- **Phrase it like a real user.** That's what the agent will see in production.
- **Concise, factual reference answer.** Meaning matters, not length or exact wording.
- **Cover several documents.** One case per paper avoids a dataset biased toward a single
  topic. Use `tags` to check the balance.
- **10–30 cases** are enough for a first reliable signal; no need to write hundreds to start.

---

## What's next — from your file to the results

Two steps, two objects. First **save** your cases as an **evaluation**: the immutable,
versioned definition. You name it; the server assigns the version.

```jsonc
POST /evaluation/v1/evaluations      // → 201, returns evaluation_id (+ version, completeness)
{
  "team_id": "<your team>",
  "name": "ArxivAi — analyst set",
  "origin": "upload",
  "source_filename": "arxiv-ai-eval.json",
  "cases": [ /* … the contents of your file … */ ]
}
```

Then start a **run**: one execution of that evaluation against a target agent. The
server owns the scoring profile, the judge and the concurrency defaults — you only
choose the agent.

```jsonc
POST /evaluation/v1/evaluations/{evaluation_id}/runs   // → 202, returns run_id
{
  "team_id": "<your team>",
  "target": { "kind": "managed_instance", "agent_instance_id": "<instance>" }
}
```

- **Evaluation vs run:** the evaluation is written once; each execution is a new run.
  Re-running never overwrites previous results — that's how you compare agent versions
  on the same questions.
- The target is a **managed agent instance** only (EVAL-04); a bare
  `runtime_id`/`agent_id` pair is no longer accepted at creation.
- RAG mode is detected automatically as soon as the agent returns a retrieval context:
  nothing to configure on the metrics side.
- Following progress and reading scores: [`evaluate-an-agent.md`](evaluate-an-agent.md).
- The full API contract (routes, statuses) is in
  [`../DEVELOPER_CONTRACT.md`](../DEVELOPER_CONTRACT.md).

---

## Checklist before launching

- [ ] Every case has a non-empty `input`.
- [ ] The questions are answerable from the ingested corpus.
- [ ] To reach `complete`: **every** case has an `expected_output`.
- [ ] `external_id`s are unique and readable (you'll find them in the results).
- [ ] The JSON is valid (an array of objects).
