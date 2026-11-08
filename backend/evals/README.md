# evals

Behavioural tests for AI output. **Not training data** — nothing here is learned from; these
are regression fixtures, the same idea as a unit test with a messier input.

```
fixtures/   ~60 real threads, grown from actual misbehaviour rather than labelled upfront
traces/     golden traces: the tool calls and the order a run is expected to make
injection/  the 6-case corpus; a Plane U agent that follows one of these fails the build
run_eval.py the runner
```

Arrives with the first agent, in phase 6 (H3). Empty until then, on purpose: an eval suite
written before the thing it measures is a guess with a pass rate.

See [07-harness.md §7](../../docs/architecture/07-harness.md) and
[03-lld-agent-runtime.md](../../docs/architecture/03-lld-agent-runtime.md) §7.
