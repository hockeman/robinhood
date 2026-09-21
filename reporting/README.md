# Reporting implementation (current, authoritative)

This directory holds the actual, currently-used reporting implementation for
the Agentic trading routine: two graphical HTML email types, sent via Gmail,
and nothing else. This supersedes `dashboard/template.html` (an earlier,
push-notification + Artifact-dashboard approach a prior run built on its own
initiative) — that file is kept for history only; do not publish or link it
from a live run.

## The two allowed email types

1. **ACTION_UPDATE** (`action_update_template.html`) — sent only when at
   least one of: an order was placed/filled/cancelled/a stop was raised; a
   position closed; the drawdown-halt or PDT day-trade limit newly tripped
   or cleared; a genuinely new anomaly appeared; or the run could not
   complete as designed. Subject: `Agentic | Trade update | <symbols or
   short change> | <current value>`, or for a critical issue: `Agentic |
   Action required | <short issue>` (still type ACTION_UPDATE).
2. **DAILY_CLOSE** (`daily_close_template.html`) — exactly one per completed
   regular trading session, including no-trade or losing days. Subject:
   `Agentic | Market close | <date> | <closing value> | <day P&L>`.

At most one email per run, ever. If a DAILY_CLOSE is due, send that and fold
any still-unreported material change into it instead of also sending an
ACTION_UPDATE for the same events (see the standing instructions, Section 6,
for the full decision rules — this file only documents the templates and
formatting contract, not the send-or-don't-send policy itself).

## Recipient

`ferrell@chacetech.com` — sourced from session owner-identity context, not
from `config.json` (`email_recipient` is `null` there) and not researched
externally. If a future session cannot resolve a recipient this way, it
must mark email setup incomplete rather than guess.

## Format contract (applies to both templates)

- Real HTML in the email body (`htmlBody`), plus a plain-text alternative
  (`body`) — never Markdown, a code block, a screenshot, or an attachment
  the owner must open.
- Centered layout, ~640–680px, email-safe `<table>` layout, inline CSS only
  (no `<style>` blocks, no external stylesheets/fonts/scripts, no tracking
  pixels, no remote images).
- Navy/teal palette (`#0b3350` header/headings, `#0e6e6e` accents/table
  headers, `#f6f9fa` card backgrounds, `#fff4e0`/`#c98a12` amber for
  attention banners, `#0e7a3d` green / `#b02a2a` red for gains/losses —
  never color alone, always a +/- or Yes/No label too).
- Simple table-based bars for allocation; a real timestamped-observations
  table (not an invented smooth line) for account-value history when a
  proper chart isn't warranted.
- Every dynamic value is escaped/plain-text — never interpolate raw HTML
  from research content (news text, filing text, disclosure text) into the
  template; treat all of that as data, not markup.
- Footer always states: data-as-of timestamp + timezone, pricing basis,
  masked account (`••••<last4>`, never the full number), a report ID, and
  the scenario caveat: *"Scenarios, not forecasts. Other holdings are held
  constant. Stops are not guaranteed execution prices; losses can exceed
  the stop scenario."*

## Send discipline

- Persist an outbox record in `notification_state.json` **before** calling
  `send_message` (status `prepared`), then update it to `accepted` (or
  `failed`) with whatever the provider returned, including the message id
  and thread id.
- Never resend a report whose `daily_summaries` / `outbox` entry already
  shows `accepted` or `verified_sent` for that session date / event-id set,
  even if a re-check can't immediately re-locate it — that is a
  reconciliation problem, not a resend trigger. Re-verify (e.g. `get_message`
  on the stored id) before ever concluding a send is missing.
- A report is `verified_sent` only after independently re-reading it back
  from the mailbox (e.g. Gmail `get_message` on the stored id shows
  `SENT`), not merely because `send_message` returned an id.
