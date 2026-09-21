# Acceptance criteria — V1

## P0 safety

- Original freeze hashes match before work.
- Original freeze remains byte-for-byte unchanged after work.
- Work occurs in a new clone folder.
- `core.py`, `parser.py`, `replay.py`, `test_suite.py` in the clone remain byte-for-byte equal to baseline.
- Existing extraction, copy and export work if Context Engine folder is deleted.
- Context Engine crash/timeout never crashes or blocks the extractor.

## P0 functional

- One button appears only when a complete packet is present.
- Button passes the already generated packet; it does not rescan Betclic.
- Identical input produces byte-identical JSON except explicitly allowed timestamp fields (V1 should contain none).
- JSON validates against schema.
- TXT is UTF-8 and copyable.
- Unsupported/ambiguous input produces `BLOCKED` plus an auditable reason; no guessed probabilities.

## P1 analytical

- Shin 1X2 sums to 1 within 1e-9.
- Power markets sum to 1 within 1e-9.
- Best-price alerts never merge different settlement/period/line/owner semantics.
- Market lambdas are derived only from valid fair probabilities.
- Total-vs-team-total disagreement is surfaced as a warning, not silently hidden.
- The module labels outputs as market-implied context, never own sports TP or PLAY.

## Corpus gate

Build a corpus of at least 50 saved real packets covering:

- 5-tab and 7/8-tab offers;
- PASS and usable PARTIAL;
- men, women, youth/reserves;
- full-time, 1H, 2H;
- two-way and three-way handicaps;
- team totals;
- duplicate/equivalence groups;
- semantic quarantine;
- decimal odds with commas and dots;
- long packets over 1,000 raw rows.

Required result: 50/50 deterministic parse + schema PASS, and zero false equivalence merges in manually audited fixtures.
