# TECH_NOTES.md

## 1. Validation — client, server, or both?

Server-only for anything that decides correctness; client-side is limited to
convenience (e.g. `builder.js` just shows/hides the relevant offer-param
fields for the selected type — it doesn't validate them).

All real validation lives in `app/validators.py`
(`validate_campaign_basics`, `validate_offer_params`, `normalize_identity`)
and in `Campaign.can_schedule()/can_launch()/can_end()/window_is_valid()`
on the model itself. Routes call these functions and turn a `ValueError`
into a 422/409 with the message re-rendered in the same template. Because
there is exactly one implementation of each rule, there's no second copy in
JS that could drift out of sync — the worst a stale or hand-edited client
can do is *show* a button that the server will then correctly reject.

## 2. Lifecycle in code

`CampaignStatus` is a plain enum column on `Campaign`. The legal-transition
rules are methods on the model (`can_edit`, `can_schedule`, `can_launch`,
`can_end`, `is_launchable`, `window_is_valid`) rather than a separate
state-machine library — for four states and three transitions, a tiny
library would add a layer of indirection without buying much.

Client and server agree on "what's legal right now" by construction: every
template that shows a lifecycle button calls the *exact same* `can_*()`
method that the corresponding route checks before acting. There's one
source of truth, read twice (once to render, once to enforce) — never
duplicated as a parallel set of conditions in the template or in JS.

## 3. Stale state

`Campaign.version` is a plain integer, bumped on every edit and every
lifecycle transition. The edit form carries the version that was current
when the form was loaded (a hidden input). On submit, the server compares
it against the row's current version: if they don't match — or the status
isn't `draft` anymore, which covers "someone launched/ended it while you
were editing" even if no edit happened — the save is rejected with a
conflict (409) and the page re-renders with a "this changed, reload" message
and the *current* state, rather than silently overwriting it.

This is the optimistic-lock approach the brief explicitly allows
("a unique constraint plus a version/updated_at check is enough"); it's
checked in `edit_campaign()` in `routes_internal.py`.

## 4. The distribution link / QR

The link encodes a single opaque token: `Campaign.public_token`
(`secrets.token_urlsafe(16)`), generated independently of the internal
integer `id`. `/s/{token}` is the only thing the QR/link carries — no
status, no offer data, no internal id. That's deliberate: the link by
itself reveals nothing about the campaign's existence or state; every
request re-resolves the token against the database and renders whatever is
*currently* true.

The public route (`routes_public.py`) has three outcomes, checked in this
order: token doesn't resolve → "invalid link" (404); resolves but
`status != live` → the matching non-live message (draft/scheduled vs.
ended get slightly different copy); resolves and is live → the enroll
form. The same three-way check runs again on the enroll POST, so a
campaign ended between page-load and submit is caught too.

## 5. Identity without auth

`normalize_identity()` accepts a single free-text field and classifies it:
contains `@` → must match a basic email pattern, normalized as
trim + lowercase; otherwise → must contain at least 7 digits once
non-digits are stripped, normalized by removing everything but digits and
a leading `+`. This is intentionally the pragmatic version the brief asks
for, not E.164/libphonenumber-grade validation.

Dedup is enforced two ways: a DB-level `UniqueConstraint("campaign_id",
"identity_normalized")` (the real guard, holds even under concurrent
requests) and an explicit "does this already exist" lookup before insert
(so the common case returns a clean "you're already enrolled" page instead
of an error). If two requests race past the lookup, the `IntegrityError`
from the constraint is caught and treated as the same "recognized"
outcome — there's no path that produces a duplicate row.

## 6. One model, two audiences

The internal builder's templates render the full ORM objects directly
(`Campaign`, its `offers`, `version`, `status`, etc.) — that surface is
trusted and needs all of it.

The public surface never does this. `routes_public.py` builds a small,
explicit dict per response (`name`, `description`, a list of
`{type, params}` for offers) and that's all the template receives —
no internal id, no `version`, no raw `status` enum (it's translated into
"live" vs. a specific non-live message before reaching the template). The
boundary is the route handler: it's the one and only place that decides
what a shopper is allowed to see, rather than that decision being made
ad-hoc inside a shared template.

## What was cut, and why

- **No automated tests.** Given the time box, I prioritized getting the
  full stack working end-to-end and verified the required flows manually
  (see below) rather than writing pytest coverage. If I were to add tests
  next, lifecycle transitions and duplicate enrollment are exactly where
  I'd start.
- **No re-validation of `window_is_valid()` against "is still launchable"
  at the `scheduled` stage beyond what `can_launch()` already checks** —
  i.e., a campaign scheduled with a valid window that later becomes
  invalid only because real time has moved past `ends_at` will fail the
  launch check then, not earlier. This matches the spec ("window is
  validated at launch") but it's worth naming as a corner the design
  leaves to the launch-time check rather than catching proactively.
- **No client-side JS validation/feedback beyond field show/hide.** All
  error messaging is a full page round-trip. Fine for this scope; a real
  product would want inline JS validation for the offer-parameter fields
  and the enroll form.
- **No enrollment count or live activity view** (both explicit stretch
  goals) — skipped to keep the MVP itself solid rather than partially
  covering extra surface area.
- **No migrations framework.** `Base.metadata.create_all()` on startup is
  enough for a single SQLite file in a sandbox exercise; a real system
  would use Alembic.

## How to exercise the flows

See the "Exercising the two flows" section in `README.md` for exact
commands. Summary of what was manually verified end-to-end during
development:

- Empty campaign list → create draft → **illegal launch with zero offers
  is blocked** (409, clear message) → add an offer → launch succeeds →
  status badge flips to `live` → QR/link appear.
- Public page on the live link → enroll → offers shown → enroll again with
  the same identity in different case/spacing → recognized, not duplicated
  → invalid identity → validation error, not crash.
- End the campaign → **public link now shows the "ended" state, not the
  offer** (the non-live scan case) → attempting to end it again is
  rejected (409, terminal state).
- Stale edit: open a second draft, load its edit form (captures
  `version=0`), separately launch that same campaign (version bumps,
  status leaves draft), then submit the original edit form — rejected
  with a conflict message rather than silently applied.

## AI tool usage

Built with AI pair-programming (Claude) for scaffolding the FastAPI
routes/templates and iterating on the validation/lifecycle logic; I
reviewed and adjusted the design decisions above myself, and ran the
flows manually against a live server to confirm each one behaves as
described before treating it as done.

## Docker

Added after the initial build, for an easier "just run it" path:
`Dockerfile` + `docker-compose.yml`. The only code change this required
was making the SQLite path configurable via `LOOPLINK_DATA_DIR`
(`app/database.py`), defaulting to the project root so local/non-Docker
behavior is unchanged. In the container it's set to `/app/data`, which
`docker-compose.yml` mounts as a named volume so the data outlives
`docker compose down`.

## What I'd do next with more time

- Add pytest coverage for the lifecycle transitions (legal + illegal),
  duplicate enrollment under simulated concurrency, and the stale-edit
  conflict path — these are the cases most worth locking down with tests.
- Inline client-side validation feedback (still server-enforced
  underneath) for a snappier builder experience.
- An enrollment count on the campaign list/detail (the stretch goal),
  since it's a small addition once the data's already there.
- Swap `create_all()` for Alembic migrations if this were headed toward
  real schema evolution.
