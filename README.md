# Fleek AM Autopilot

A daily portfolio tool for Fleek's GTM Retention team. Drop in a portfolio
export and it:

1. **Cleans it** and logs every fix (blanks, spellings, `£1,234` strings,
   mismatched totals, a CRM duplicate, a region column that mixes countries
   and blocs).
2. **Segments the book by behaviour, not the ownership label**: broker-reliant,
   broker + browsing, account-managed but self-serving, account-managed but
   light-touch, self-serve.
3. **Picks one next best action per account, says why, and drafts it**: a call
   note for the AM, an email for the AM to approve, or a nudge the agent sends.
4. **Remembers what it has done.** Run it again and it picks up new accounts,
   updates changed ones, skips everything else, and never duplicates an action.

## Run it

Python 3.10+.

```bash
pip install -r requirements.txt
make demo          # or the three commands below
```

```bash
python -m autopilot run --input data/raw/fleek_portfolio.xlsx --sheet Accounts --dispatch
python -m autopilot run --input data/raw/fleek_portfolio.xlsx --sheet new_accounts --dispatch
python -m autopilot run --input data/raw/fleek_portfolio.xlsx --sheet new_accounts --dispatch   # skipped
```

Then open **`out/dashboard.html`**. What the three runs show:

| Run | Result |
|---|---|
| 1. Accounts | 300 new accounts, 335 data fixes logged, 284 actions created |
| 2. new_accounts | 45 new, 5 updated (ACC-006 and ACC-008 flagged as migration progress), the other 295 accounts untouched, 345 in the book, no duplicate actions |
| 3. new_accounts again | "already processed, nothing to do" |
| 3b. same, with `--force` | re-reads the file: all 50 accounts unchanged, so all 50 skipped and 0 actions created |

Other commands:

```bash
python -m autopilot queue --bucket today      # the AM's call list
python -m autopilot show ACC-001              # one account: segment, reason, call note, history
python -m autopilot mark ACC-002 done         # log an outcome; the next run respects it
python -m autopilot status                    # runs, segments, actions by owner
python -m autopilot inbox                     # daily mode: process every new file in data/inbox/
python -m autopilot reset                     # start again
```

## What comes out (`out/`)

| File | For |
|---|---|
| `dashboard.html` | Everything, clickable. Click any account for its numbers, monthly spend, reason, call note, draft and history. |
| `queue_today.csv` | The AM's calls for today, capped at their daily capacity (12 by default) |
| `review_queue.csv` | Drafts waiting for AM approval |
| `outbox.jsonl` | Automated messages for the sending agent / CRM |
| `accounts.csv` | The whole book, cleaned and scored |
| `data_quality.csv` | Every fix made in this run |
| `run_summary.md` | What happened, in plain English |

## What it found in this book

- **83% of GMV (£702k) sits in 78 broker-reliant accounts**, which also hold
  515 of the 525 orders AMs placed by hand. Account-managed customers split
  cleanly: nobody sits between 20% and 40% broker reliance.
- **132 of 210 account-managed customers already buy for themselves.** They
  are small (median £306) and do not need an AM's time.
- **£133k is at risk in 14 broker-reliant accounts that stopped buying.**
  ACC-002 (£70.6k) has been silent since October. These get a win-back call
  before anyone mentions self-serve.
- The top 10 accounts are 51% of GMV; ACC-001 alone is 20%. Migration for the
  biggest accounts is partial: routine reorders move to the app, the AM keeps
  the specialist sourcing.

The reasoning is in [docs/playbook.md](docs/playbook.md).

## How it is built

- [docs/architecture.md](docs/architecture.md): diagram of where data comes
  in, what is automatic, and where the agent and the AM step in; the rules
  that keep re-runs safe; scale numbers.
- [docs/playbook.md](docs/playbook.md): migration waves, feature nudges,
  health, first 30 days, assumptions.
- [docs/ai_usage.md](docs/ai_usage.md): how AI was used, where it helped and
  where it got in the way.
- **Config, not code**: every threshold is in `config/rules.yaml`; every play,
  owner and message template is in `config/plays.yaml`.

## Scale

`make bench` builds a 30,000-account synthetic book (from the real
distributions, with mess injected) and runs the full job: about 5 seconds for
the whole book, under half a second for a 1,000-row daily batch, zero
duplicate actions. Only new and changed accounts are re-scored.

## Online

`.github/workflows/daily.yml` runs the tests and the daily job on every push
and each weekday morning. To also publish the dashboard to GitHub Pages
(public repo, or a paid plan for a private one): set Pages to source "GitHub
Actions" in the repo settings, then add the Actions variable
`PUBLISH_DASHBOARD` = `true`.

## Optional: Claude-polished drafts

```bash
pip install anthropic && export ANTHROPIC_API_KEY=...
python -m autopilot run --input <file> --sheet <tab> --llm 10
```

Rewrites the wording of the top 10 human/review drafts only; facts, numbers
and links are kept, and any failure falls back to the template.

## Tests

```bash
python -m pytest -q
```
