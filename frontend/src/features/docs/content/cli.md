# CLI and CI

The `raglabs` command runs the app and gates a build on the retrieval quality of an external RAG endpoint. It is built for CI: it needs no project and no database.

Run it from the `backend` folder with `uv run raglabs ...`.

## raglabs serve

```bash
uv run raglabs serve --host 127.0.0.1 --port 8000
```

Starts the backend, the same as `uvicorn app.main:app`.

## raglabs eval

Scores an HTTP endpoint on an eval CSV and exits non-zero if it falls below your thresholds.

```bash
uv run raglabs eval \
  --endpoint https://staging.example.com/ask \
  --set eval.csv \
  --header "Authorization: Bearer $RAG_TOKEN" \
  --min-mrr 0.6 --min-hit 0.8
```

### The eval CSV

| Column | Required | Meaning |
| --- | --- | --- |
| `question` | Yes | The question to send |
| `evidence` | Yes | A verbatim quote from the source that answers it |
| `document` | No | The file name; when the system names a source it must match |
| `valid` | No | Set to `no` to skip a row |

Export a ready-made file from the Evaluate tab (**Export CSV**) and it works as is.

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--endpoint` | required | The URL to POST questions to; must be http or https and not contain credentials |
| `--set` | required | The eval CSV |
| `--min-mrr` | none | Fail if MRR is below this |
| `--min-hit` | none | Fail if Hit@top-k is below this |
| `--header "Name: value"` | none | Repeatable; for authentication |
| `--question-field` | `question` | JSON key the question is sent in |
| `--answer-path` | `answer` | Where the answer is in the response |
| `--contexts-path` | `contexts` | The list of retrieved passages |
| `--text-path` | `text` | Passage text inside one context |
| `--source-path` | `source` | The passage's document |
| `--top-k` | 8 | Passages scored per question |
| `--timeout` | 30 | Seconds per request |
| `--json` | off | Print the metrics as JSON |

The endpoint contract and the scoring rules are the same as in [Evaluate your own RAG](/docs/your-rag).

### Output and exit codes

```
30 questions · Hit@1 0.63 · Hit@3 0.80 · Hit@8 0.90 · MRR 0.731 · nDCG@8 0.762 · p50 412 ms · p95 980 ms
PASS
```

| Exit code | Meaning |
| --- | --- |
| 0 | Every threshold you set was met |
| 1 | A threshold was missed (the output says which) |
| 2 | Bad input: a malformed CSV, a bad option, or the endpoint could not be reached or returned something that does not match the mapping |

## GitHub Actions

Put the command in a workflow step after installing uv, and store the token as a repository secret:

```yaml
- uses: astral-sh/setup-uv@v5
- name: Retrieval quality gate
  working-directory: backend
  run: >
    uv run raglabs eval --endpoint ${{ vars.RAG_URL }} --set ../eval.csv
    --header "Authorization: Bearer ${{ secrets.RAG_TOKEN }}"
    --min-mrr 0.6 --min-hit 0.8
```

> **Tip** Pick thresholds a little below your current numbers so that real regressions fail the build but noise does not. With a small CSV a difference of a few points is within noise; use 50 questions or more for a gate.
