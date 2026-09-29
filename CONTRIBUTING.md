# Contributing

Thank you for looking at this project. It is a small, deterministic simulator, and the
rules below keep it that way.

## Ground rules

1. **No real data, ever.** Only authored synthetic fixtures under `examples/fixtures/`.
   Organisation names must be obviously fictional. Identifiers use the `SYN-` prefix.
2. **Money is integer cents.** Never introduce a float for an amount.
3. **Determinism is a feature.** The engine draws no random numbers; all randomness is
   in `workload.generate_workload` and is seeded. A change that makes the same seed
   produce a different event log must be deliberate and must update the fixture via
   `python tools/make_fixture.py` and the numbers in `docs/evaluation.md`.
4. **Every number in the docs is computed.** If you change behaviour, rerun
   `python -m business_flow_simulator demo` and `python -m pytest -q` and paste the real
   output into `docs/evaluation.md`. Do not edit a number by hand.
5. **No ROI or causal business claims.** The comparison describes what the simulation
   did under each policy on synthetic input; that is all it can say.

## Workflow

```
pip install -e . && pip install pytest
python -m business_flow_simulator smoke
python -m pytest -q
```

Add a focused test for every behaviour change, including the failure case. Keep modules
under 300 lines. Type hints everywhere, frozen dataclasses where natural, no `print` in
library code (the CLI module is the only place that writes to stdout).

## Reporting problems

Open an issue with the scenario file (or the exported scenario string from
`export-scenario`), the seed, the policy and the command you ran. Because runs are
deterministic, that is enough to reproduce any result exactly.
