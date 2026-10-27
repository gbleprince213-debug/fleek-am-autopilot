# How AI was used to build this

**Tool:** Claude (Anthropic) in claude.ai, working as an agent with a browser,
a shell and file access. Every commit is co-authored by Claude and links to
the working session, so the history shows exactly what was produced and when.

## How the work went

1. **Read the brief and the data before writing code.** Claude opened the case
   study page and the Notion guide, then profiled the Excel file: types,
   category values, and whether the numbers agree with each other.
2. **Let the data set the rules.** Profiling showed broker reliance is
   bimodal (nothing between 20% and 40%), so 40% became the segment line. It
   also surfaced the mess the cleaner handles: a CRM-flagged duplicate,
   ±£1-2 rounding gaps between total and monthly GMV on 38 rows, a trend
   column that is blank whenever September was zero, a region column mixing
   countries with blocs, and tracking gaps.
3. **Build in small commits**: cleaning, then features and segments, then
   actions and drafts, then state and re-runs, then outputs, then scale, then
   tests and docs.
4. **Check every output by reading it.** One example of every draft was
   rendered and proofread; the dashboard was screenshotted in light, dark and
   phone widths; every figure in the docs was computed from the data.

## Where it sped things up

- Vectorised pandas for cleaning and scoring, written and checked in minutes.
- The dashboard: a self-contained HTML page with drill-down, built and
  visually checked in one pass.
- The synthetic 30k book and benchmark, which would have been a day by hand.
- Tests covering the behaviour the brief cares about (no duplicates on
  re-run).

## Where it got in the way, and how that was caught

- **YAML broke on colons** inside message text. Caught on first load, fixed.
- **Copy quality.** Templates came out hard-wrapped mid-sentence and with a
  grammar slip ("handpicked pieces that fits"). Caught by rendering every
  play and reading it; fixed with a reflow step and reworded templates.
- **An unsupported claim in a draft.** A call note said an account showed
  "signs they can self-serve" from 5 product views; the real driver was 18
  video-call requests. Reworded to show the actual readiness inputs.
- **A real bug found by testing the re-run.** Re-dropping the first file
  after the second rolled five accounts back to stale data. Fix: a file that
  was already processed is skipped unless forced.
- **Performance.** The first 30k run took ~32s to score. Profiling found
  `iterrows` in the draft builder and JSON parsing in the queue; after the
  fix it is ~5s.
- **A wrong statement in the docs.** The playbook first said the broker-%
  disagreement never moves an account across the 40% line. Checking showed
  one does (ACC-020); the doc now says so.
- **A commercial call it got wrong first time.** Lapsed accounts that still
  browse heavily (e.g. 1,764 product views, £186 spent) were getting a
  generic reactivation email. Changed so strong intent gets the chat nudge.

## What still needs a person

The thresholds, the order of the plays and the message tone are judgement
calls made from the data, not facts. They are all in `config/` so the team
can change them, and the playbook lists the assumptions to check with Fleek.
