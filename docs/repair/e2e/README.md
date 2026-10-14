# End-to-end no-order run (2026-10-14T18:46Z)

Read-only. NO order was placed, cancelled or replaced. Data: live Robinhood read-only tools (portfolio, positions, open
orders, quotes, tax lots, 8 saved scans, earnings calendar, SEC filing index, fundamentals), web search/fetch.
Executed inside an isolated sandbox clone laid out like the canonical branch (a local bare repo as `origin`), because
`startup_check.py` correctly refuses to pass on the repair branch. Its state.json was a copy of production @052ab41; the
sandbox push went to the sandbox remote, never to production.

Honest limits: raw scan/earnings/news/filing files are COMPACT TRANSCRIPTIONS the agent wrote from tool output
(no platform hook saves verbatim output); the earnings file holds 21 of 40 returned rows; filing text was unavailable
(404) for the LQDA/VSTM/MXCT 8-Ks; Liquidia's own site returned 403 (company release read via a GlobeNewswire copy);
the 3-review budget is a DEMONSTRATION cap (production config: 8), so 5 holdings and 27 scanner names were deferred.
Result: RESEARCH_DEFERRED_BUDGET — the old workflow would have journaled this run as NO_ACTION.
