# The commercial thinking behind the rules

Figures are from the inherited book (Accounts tab, 300 accounts, Sep 2025 to
Feb 2026), unless stated.

## What the book actually looks like

- **It is concentrated.** £845k of 6-month GMV. The top 10 accounts are 51% of
  it; ACC-001 alone is 20%.
- **Brokering is where the money is.** Account-managed customers split cleanly
  in two. Nobody sits between 20% and 40% broker reliance, so 40% is a natural
  line, not an arbitrary one. The 78 accounts above it hold **£702k (83%)**
  and **515 of the 525 orders AMs placed by hand**. Their median is 4 app days
  and 5 product views in six months: the AM is their buying channel, often
  through chat (ACC-001 has 139 chat threads).
- **The label overstates who needs an AM.** 132 of the 210 account-managed
  customers (63%) already place their own orders. They are small (median
  £306, one order) and together are worth £78k. They do not need an AM's time.
- **Spend is lumpy.** Half the book has not bought in the last three months of
  its time on book, and 158 accounts have a single order. That is normal
  wholesale behaviour, so "lapsed" alone is not a reason for a human; value
  decides.

## Problem 1: migrate broker-reliant accounts without losing spend

The risk is asymmetric. Moving a £170k account to self-serve and losing it
costs more than a year of AM time. So the play gets *more* careful the more
an account spends, and retention always comes before migration.

| Wave | Accounts | Play | Who | Why |
|---|---|---|---|---|
| 0. Protect | 14 lapsing key/mid accounts, £133k (ACC-002 alone is £70.6k and silent since October) | Win-back call before anything else | AM (3 key) / AM-approved note (11 mid) | Never pitch self-serve to a customer who has stopped buying. Find out why first. |
| 1. Assisted hand-off | 6 key accounts with migration readiness 40+ (ACC-003, 004, 006, 013, 016, 017), £128k | We build the next order as a shortlist in the app; they check out. Do it on a video call if they use video. | AM | They already show some ability to self-serve (video calls, bundle buying, offers). The AM still chooses, the customer presses buy. |
| 2. Partial migration | 7 key accounts with low readiness (ACC-001, 007, 008, 009, 010, 012, 014), £273k | Migrate the routine, keep the relationship: repeat reorders move to the app with saved searches and drop alerts; the AM keeps specialist and handpick sourcing. | AM | All-or-nothing migration is how you lose a whale. Target 30% of orders self-placed in 60 days, spend flat or up. |
| 3. At scale | 30 mid-value accounts, £123k | Guided email with a shortlist link, a 15-minute walkthrough and a perk for ordering in-app | Agent drafts, AM approves | Big enough for a personal note, too many for calls. |
| 3. At scale | 20 long-tail accounts, £19k | Automated onboarding sequence; brokering for small orders only on request | Agent | AM time on a £500 account costs more than it earns. |

**Readiness** (0-100) is how likely an account is to cope buying alone: some
app days, product views and offers, a high bundle share (standard product is
easier to self-serve than handpicks), reseller persona (online sellers are
digital-native), and video-call use (comfortable buying remotely).

**How we know it is working.** Per account: share of orders self-placed, and
spend versus its run-rate before migration. The tool already logs a fall in
broker reliance of 10+ points between runs as progress (ACC-006 went 84% to
64% and ACC-008 84% to 66% in the second batch, both with spend up).
**Guardrail to add next:** if spend falls more than 20% below run-rate after a
migration step, flag the account straight back to its AM.

## Problem 2: grow self-serve spend, keep it self-serve

Applies to the self-serve accounts and to the 132 account-managed customers who
behave like self-serve. One nudge per account, chosen in this order:

| Signal | Feature nudge | Why | Count |
|---|---|---|---:|
| Spends £400+/month and has never had a video call | **Video call** (live sourcing session) | Bigger baskets come from confidence about large lots | 5 |
| Lots of browsing or offers per order, little chat | **Chat** | High intent, low conversion: something is stopping the purchase, usually a question | 18 |
| Buys handpicks only | **Bundles** | More volume per order at a lower cost per piece | 15 |
| Bundle buyer who browses a lot | **Build-a-bundle** | They want volume and control of the mix | 50 |
| New, one order | **Second-order nudge** | The second order is the one that makes a customer stick | 39 |

Priority within growth uses **headroom**: engagement score minus value score,
i.e. intent running ahead of spend. Lapsed accounts that are still browsing
hard get the chat nudge instead of a generic reactivation email.

Two self-serve accounts are big enough to deserve a growth owner: ACC-211
(£13.4k, 6,665 product views, 71 offers) and ACC-212 (£8.6k). ACC-211 went
quiet in Jan-Feb in the first file (win-back note), then the second batch
showed £3.5k in February, so its action switched to a video-call offer.

## Health: which accounts are healthiest for Fleek

Health score (0-100) = value 35%, self-sufficiency (100 - broker %) 25%,
consistency (months with spend / months on book) 20%, momentum 10%,
engagement 10%, minus a penalty for lapsing or cooling.

The healthiest accounts are valuable, buy for themselves, buy every month and
are growing: **ACC-217, ACC-212, ACC-219, ACC-213, ACC-025**. They are cheap to
serve and sticky. ACC-001 is the most valuable account but not the healthiest:
69% brokered, 139 chat threads, and 20% of the book in one relationship.

## First 30 days

| Week | Do | The tool's part |
|---|---|---|
| 1 | Handover with the outgoing AM to sanity-check segments on the top 20. Win-back calls to ACC-002, ACC-011, ACC-015. Merge the ACC-005 duplicate. Agree the self-checkout perk and what "shortlist link" means in the product. | First run; queue capped at 12 calls a day; drafts for the 11 lapsing mid accounts. |
| 2 | Assisted hand-offs with the 6 ready key accounts. Switch on automated sequences for the long tail and new customers. | Agent sends the outbox daily; review queue takes 10 minutes. |
| 3 | Partial-migration conversations with the 7 big low-readiness accounts. | Call notes, follow-up emails, outcomes logged with `mark`. |
| 4 | Measure: self-placed share and spend vs run-rate on migrated accounts, response rate by play. Tune thresholds in `rules.yaml`. Propose releasing the 125 long-tail AM-labelled self-servers to pooled coverage. | Run history and the "What changed" view. |

A normal day: the job runs before 9am, the AM opens the dashboard, works the
call list, approves drafts, and logs outcomes. Everything else already
happened.

## Assumptions to check with the team

- The data is a six-month snapshot per account, not an event stream, so
  "recency" is measured in months.
- `broker_reliance_pct` disagrees with the order counts on some small
  accounts (e.g. 15% with zero manual orders), probably because the % is
  measured over a longer period. The tool keeps the reported % and flags gaps
  over 25 points. Only one account would change side of the 40% line:
  ACC-020 (48% reported, 1 of 3 orders by count). With three orders either
  reading is thin, and its low app use (7 days, 3 product views) supports
  treating it as broker-reliant.
- Drafts assume we can share a shortlist or saved search link and offer a
  non-monetary perk (first look at new drops). Monetary incentives need
  commercial sign-off.
- There are no contact names in the anonymised data, so drafts open with
  "Hi there".
