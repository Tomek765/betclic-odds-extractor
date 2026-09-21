# Evidence and settlement changes

Runtime SHA-256 `2d6b25810a1a8fc7a9954bee08f0314e3b4dbf544d41156d1596d581ef7bef42`
matches the installed EXE. RELEASE_MANIFEST.json names this source directory.
Git metadata is absent: branch and HEAD cannot be reported.

Regulatory evidence: https://www.betclic.pl/termsandconditions retrieved directly
on 2026-09-05; complete HTML and SHA-verifiable copy in
`D:/APEX_CONTEXT_ENGINE_V1_WORK/repair_audit_20260905/betclic_terms_20260905.html`.
The page links version 8.0. Search-indexed version 1.105 is older and differs on
corners: use the current page, not that older default.

The named team/player shots contracts include eventual extra time and exclude
shootouts. `MATCH_INCLUDING_EXTRA_TIME` models this settlement window, including
stoppage time. It is neither extra-time-only nor a literal wall-clock interval.
The captured `1x2 Strzały (120 min)` matches that explicit statistical contract.
Assists and SuperSub goal/assist contracts use regulation time. Current corner
rules exclude extra time. Match/team cards use regulation time; player statistics
include extra time. Explicit half and 90-minute evidence takes precedence.
Unknown titles and new 120-minute contracts remain fail closed. Xtra payout rules
are not established by this page and must not inherit ordinary payout semantics.

Boolean proof: for nonnegative integer goals H,A and T=H+A,
`not(BTTS or T>2.5)` equals `not BTTS and T<2.5`, by De Morgan and absence of
integer T equal to 2.5. At line 2, T=2, BTTS=false is a counterexample. Only the
two parsed predicates, half line 2.5 and binary settlement share the rule.

Audit root cause: `(market, category, odds)` collided for 1H HOME and 2H DRAW.
Copies already carry source IDs. Resolve these IDs before testing settlement;
ambiguous legacy lookups remain rejected. Period remains in every equivalence key.

Accounting: 1236 identity representatives = 856 core accepted + 380 quarantined.
1018 canonical export representatives = 698 accepted + 320 quarantined.
Core quarantine is 351 player + 29 statistics; export is 291 + 29.
The old PERIOD_UNKNOWN_COUNT counted only accepted core rows. Worse, Context's
block regex omitted SEMANTIC_QUARANTINE entirely. Preserve and count these blocks.
