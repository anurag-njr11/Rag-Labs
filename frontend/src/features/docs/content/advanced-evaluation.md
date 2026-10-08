# Advanced evaluation

Three tools in the Evaluate tab go beyond scoring retrieval: an embedding adapter, prompt optimisation and injection-resistance testing. The adapter and prompt optimisation appear once the eval set has at least 50 questions, or when **Labs** is switched on under **LLM providers**. Injection resistance is always available.

## Embedding adapter

An adapter is a small linear map applied to the question's vector so that questions land closer to the passages that answer them, trained on your eval set's labels.

1. Open **Evaluate**, then **Embedding adapter**, and train one for a version.
2. Training runs on your CPU in seconds (NumPy). The strength of the adapter (lambda) is chosen by cross-validation inside the training questions.
3. Results are reported before and after on **held-out** questions the adapter never saw. It is only **recommended** when it beats the plain embedder on both Recall@k and MRR.
4. To use it, enable the retrieve option `adapter` (an instant setting). If the version later uses a different embedding model, the adapter is skipped, with a note in the trace.

An adapter is specific to one embedding model and corpus. It ships in the repository export as `data/adapter.npy`.

> **Tip** Adapters need enough labelled questions to generalise. With a small eval set the held-out numbers will not clear the bar, and RAGLabs will say so rather than recommend it.

## Prompt optimisation

Prompt optimisation improves the answer prompt using your eval set, in the style of DSPy but without the framework.

1. It bootstraps few-shot examples from the model's own best answers.
2. It asks the model to propose alternative instruction blocks.
3. It selects the best candidates on validation questions.
4. It reports before and after on **test** questions that were never used to choose.

The result is written to the prompt options `extra_instructions` and `examples`, and ships in the repository export. It uses LLM calls to generate and grade answers, so expect a real cost on a larger set.

## Injection resistance

Documents are untrusted input: a passage can contain text that tries to steer the model ("ignore your instructions and ..."). **Evaluate**, then **Injection resistance** measures how well your pipeline resists.

It plants a poisoned passage at the top of the real retrieval results for a sample of your questions (in memory only; your corpus is never changed) and checks whether the answer obeyed it. The poison carries one of five payloads, each with a canary string so success is a simple string check:

| Payload | What it tries |
| --- | --- |
| Instruction override | Make the model follow instructions found in a passage |
| Link exfiltration | Make the model output an attacker's link |
| Contact swap | Replace a real contact detail with another |
| Planted false fact | Make the model state something the documents do not say |
| System-prompt leak | Make the model reveal its instructions |

Each variant is scored with a 95% interval: **as configured**, **no defences**, **each defence alone** and **all defences**, so you can see which defences actually move the number.

### The defences

| Option | What it does |
| --- | --- |
| `prompt.injection_guard = data_rule` | The default: the prompt tells the model that sources are data, not instructions |
| `prompt.injection_guard = delimited` | Sources are wrapped in tags marked untrusted, and a smuggled closing tag is escaped |
| `prompt.injection_guard = none` | No defence, for comparison |
| `verify.validate_output` | Removes URLs, emails and phone numbers that appear in no source from the answer (the answer is then sent whole, not streamed) |

A pipeline with no defence shows a warning in Configure. The recipe **Hardened for production** enables defences and the grounding check together.

## Grounding check and code check

The Verify stage adds checks after generation. They are configured in [Configure](/docs/configure) and measured here:

- **Grounding check** grades every claim and citation against the sources, and either flags the answer or retries with more context. Answer-graded runs report its pass rate and how often it retried. `verify.type` is a sweep axis, so you can measure the trade-off between faithfulness and latency.
- **Code check** runs a code answer's Python in a throwaway Docker container (no network, 256 MB, one CPU, read-only, unprivileged, time-limited) against tests: the eval question's own tests, `>>>` examples from the retrieved documentation, or model-written asserts (labelled as weaker evidence). A failure goes back to the model to fix, up to `max_steps`. Without Docker running, the check is skipped, never run locally.

Eval questions can carry optional `tests` (editable in the question editor and as a CSV column). Answer-graded runs then report **execution-verified correctness**: the share of tested questions whose code passed, with a 95% interval.
