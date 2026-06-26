# TESTING.md — API Schema & Test Cases

One file covering every route's contract and every case worth exercising
(manually or with curl) before / during the review session.

---

## 1. API Schema

### Internal — Builder (`/campaigns`)

| Method | Path | Body params (form-encoded) | Success | Failure modes |
|---|---|---|---|---|
| GET | `/campaigns` | — | 200, list page (empty state if none) | — |
| GET | `/campaigns/new` | — | 200, create form | — |
| POST | `/campaigns/new` | `name`, `description`, `starts_at`, `ends_at` | 303 → `/campaigns/{id}` (new draft) | 422, form re-rendered with error if `name` blank or dates invalid/missing |
| GET | `/campaigns/{id}` | — | 200, detail page | 404 if id doesn't exist |
| POST | `/campaigns/{id}/edit` | `name`, `description`, `starts_at`, `ends_at`, `version` | 303 → detail (version +1) | 409 if `version` mismatch or status ≠ draft; 422 on bad input |
| POST | `/campaigns/{id}/offers/add` | `offer_type` + that type's fields (see §2) | 303 → detail | 422 if status ≠ draft or params invalid |
| POST | `/campaigns/{id}/offers/{offer_id}/delete` | — | 303 → detail | 409 if status ≠ draft |
| POST | `/campaigns/{id}/schedule` | — | 303 → detail, status → `scheduled` | 409 if not draft, or window/offers invalid |
| POST | `/campaigns/{id}/launch` | — | 303 → detail, status → `live` | 409 if not draft/scheduled, or window/offers invalid |
| POST | `/campaigns/{id}/end` | — | 303 → detail, status → `ended` | 409 if not live |
| GET | `/campaigns/{id}/qr.png` | — | 200, `image/png` | 409 if not live |

### Public — Shopper (`/s`)

| Method | Path | Body params | Success | Failure modes |
|---|---|---|---|---|
| GET | `/s/{token}` | — | 200 enroll form (live) / non-live message (draft, scheduled, ended) | 404 invalid-link page if token unknown |
| POST | `/s/{token}/enroll` | `identity` (free text — phone or email) | 200 success page, offers shown, `already_enrolled` flag set if repeat | 422 if identity invalid; non-live/404 page if campaign isn't live anymore |

---

## 2. Data reference (enums + offer params)

**`CampaignStatus`**: `draft` → `scheduled` → `live` → `ended` (forward-only; see TECH_NOTES "Status flow")

**`OfferType`** and required `params` fields (all numbers must be ≥ 0):

| Type | Fields |
|---|---|
| `PRODUCT_PERCENT_DISCOUNT` | `percent` (number), `applies_to` (text) |
| `CART_FIXED_DISCOUNT` | `amount_off` (number), `min_basket` (number) |
| `STICKER_EARN` | `stickers` (number), `per_amount` (number) |

**`IdentityType`**: inferred, not chosen — `email` if input contains `@` and matches `^[^@\s]+@[^@\s]+\.[^@\s]+$`; otherwise `phone` if it has ≥7 digits after stripping non-digits.

---

## 3. Test cases

### A. Campaign creation & basic validation

| # | Case | Steps | Expected |
|---|---|---|---|
| A1 | List is empty initially | `GET /campaigns` with no data | Empty-state message, "+ New campaign" CTA |
| A2 | Create with valid data | `POST /campaigns/new` with name + valid window | 303 → new draft, status `draft` |
| A3 | Create with blank name | omit `name` | 422, "Campaign name is required" |
| A4 | Create with missing dates | omit `starts_at`/`ends_at` | 422, "Start/End date is required" |
| A5 | Create with malformed date string | `starts_at=not-a-date` | 422, "...is not a valid date/time" |
| A6 | List shows created campaigns with correct status badge | `GET /campaigns` after A2 | Badge shows `draft` |

### B. Offer management (draft only)

| # | Case | Steps | Expected |
|---|---|---|---|
| B1 | Add a valid `PRODUCT_PERCENT_DISCOUNT` | `offer_type=PRODUCT_PERCENT_DISCOUNT, percent=10, applies_to=Shoes` | 303, offer appears on detail page |
| B2 | Add offer missing a required field | omit `applies_to` | 422, "'applies_to' is required for PRODUCT_PERCENT_DISCOUNT" |
| B3 | Add offer with non-numeric value | `percent=abc` | 422, "'percent' must be a number" |
| B4 | Add offer with negative value | `amount_off=-5` | 422, "'amount_off' must not be negative" |
| B5 | Add two offers of the same type | add `STICKER_EARN` twice with different values | Both appear as separate rows, list not keyed by type |
| B6 | Remove an offer | `POST /offers/{id}/delete` while draft | 303, offer gone from list |
| B7 | Add/remove offer on a non-draft campaign | schedule or launch first, then try add/delete | 409/blocked — server rejects regardless of UI |

### C. Lifecycle transitions

| # | Case | Steps | Expected |
|---|---|---|---|
| C1 | Launch with zero offers | draft, no offers, `POST /launch` | 409, "Cannot launch: needs draft or scheduled status, a valid window, and at least one offer." |
| C2 | Launch with invalid window (ends before starts) | `ends_at` < `starts_at`, then launch | 409, blocked |
| C3 | Launch with window already in the past | both dates before "now" | 409, blocked |
| C4 | Schedule with valid window + ≥1 offer | draft, 1 offer, valid window | 303, status → `scheduled` |
| C5 | Launch directly from draft (skip schedule) | draft, 1 offer, valid window, `POST /launch` | 303, status → `live` |
| C6 | Launch from scheduled | C4 then `POST /launch` | 303, status → `live` |
| C7 | End a live campaign | live, `POST /end` | 303, status → `ended` |
| C8 | End a non-live campaign | draft/scheduled, `POST /end` | 409, "Cannot end: campaign is not live." |
| C9 | End an already-ended campaign | ended, `POST /end` again | 409, blocked (terminal) |
| C10 | Edit a scheduled/live/ended campaign | any non-draft, `POST /edit` | 409, "This campaign changed..." (caught by `can_edit()` check, not just version) |
| C11 | No "un-schedule" path exists | inspect routes | Confirm there's no route that moves scheduled → draft |
| C12 | Live campaign past its `ends_at` stays live | launch, let `ends_at` pass, don't call `/end` | Still `live` and enrollable — window never auto-transitions status |
| C13 | Scheduled campaign whose window has since passed can't launch | schedule with near-future window, wait past `ends_at`, then `POST /launch` | 409 — `is_launchable()` re-checks window at launch time |

### D. Stale-edit (optimistic concurrency)

| # | Case | Steps | Expected |
|---|---|---|---|
| D1 | Normal edit | load edit form (`version=0`), submit with `version=0` matching current | 303, saved, `version` → 1 |
| D2 | Edit after someone else edited first | two "sessions" load `version=0`; session A saves (version→1); session B submits with stale `version=0` | 409, "This campaign changed since you opened it..." |
| D3 | Edit after a lifecycle transition moved it out of draft | load edit form, separately `launch` the campaign, then submit the edit | 409, same conflict message (caught by `can_edit()` even if version technically matched) |
| D4 | Edit with correct, current version | reload after a 409, resubmit with the new `version` | 303, succeeds |

### E. Distribution link / QR

| # | Case | Steps | Expected |
|---|---|---|---|
| E1 | QR available only when live | `GET /campaigns/{id}/qr.png` while draft/scheduled/ended | 409 |
| E2 | QR available when live | same, while live | 200, `image/png` |
| E3 | Link token is independent of internal id | inspect `public_token` vs `id` | No relationship/derivability between them |
| E4 | Link reveals nothing before resolving | inspect the link/QR payload itself | Just `/s/{token}` — no status, no offers encoded |

### F. Public page — link resolution states

| # | Case | Steps | Expected |
|---|---|---|---|
| F1 | Unknown/malformed token | `GET /s/does-not-exist` | 404, "This link doesn't work" |
| F2 | Token resolves, campaign is draft | `GET /s/{token}` for a draft campaign | "Not open yet" message, no offers shown |
| F3 | Token resolves, campaign is scheduled | same for scheduled | "Not open yet" message |
| F4 | Token resolves, campaign is ended | same for ended | "This campaign has ended" message |
| F5 | Token resolves, campaign is live | same for live | Enroll form shown |
| F6 | Campaign ends between page load and submit | load live enroll page, end the campaign, then submit `/enroll` | Non-live message returned instead of enrolling |

### G. Enrollment & identity

| # | Case | Steps | Expected |
|---|---|---|---|
| G1 | Enroll with valid email | `identity=jane@example.com` | 200 success page, "You're in!", offers listed |
| G2 | Enroll with valid phone | `identity=555-123-4567` | 200 success, classified as `phone` |
| G3 | Re-enroll same identity, exact match | submit G1's identity again | 200, "You're already enrolled" — no duplicate row |
| G4 | Re-enroll with different case/spacing | `identity= Jane@Example.com ` | Recognized as the same person (normalized match) |
| G5 | Invalid email shape | `identity=foo@bar` (no TLD) or `identity=not-an-email-but-has-@` | 422, "That doesn't look like a valid email" |
| G6 | Too-short digit string | `identity=12345` | 422, "That doesn't look like a valid phone number" |
| G7 | Blank identity | `identity=` | 422, "Please enter a phone number or email" |
| G8 | Two requests race on the same new identity | concurrent POSTs with identical identity to a fresh campaign | Exactly one `Enrollment` row; both responses show success (one via insert, one via the `IntegrityError` → recognized path) |
| G9 | Enrollment ties to one campaign only | enroll the same identity on two different live campaigns | Two separate `Enrollment` rows (constraint is per-`campaign_id`, not global) |

### H. One-model-two-audiences boundary

| # | Case | Steps | Expected |
|---|---|---|---|
| H1 | Public page never exposes internal id | inspect HTML/response of `/s/{token}` and `/enroll` | No `id`, no `version`, no raw enum value beyond the status-derived message |
| H2 | Public offer view matches internal params exactly | compare an offer's `params` on the detail page vs. the success page | Same key/values, just no extra internal metadata alongside them |

### I. Known, named limitations (confirm behavior, not bugs)

| # | Case | Steps | Expected / why |
|---|---|---|---|
| I1 | Two concurrent `launch` calls on the same draft | fire two `POST /launch` near-simultaneously | Both may succeed (idempotent end state: `live`, version bumped twice) — no version guard on transitions, unlike edit; documented trade-off in TECH_NOTES |
| I2 | `percent` accepts values > 100 | add `PRODUCT_PERCENT_DISCOUNT` with `percent=500` | Currently allowed (no upper-bound check) — only negativity is rejected |
| I3 | Phone normalization is pragmatic, not E.164 | enter numbers with extensions, country codes, formatting quirks | May normalize inconsistently for edge-case formats — accepted per spec ("you do not need full E.164") |

---

## 4. Quick curl reference

```bash
# Create
curl -X POST localhost:8000/campaigns/new -d "name=Test" -d "description=" \
  -d "starts_at=2026-08-01T10:00" -d "ends_at=2026-08-10T10:00"

# Add offer
curl -X POST localhost:8000/campaigns/1/offers/add \
  -d "offer_type=PRODUCT_PERCENT_DISCOUNT" -d "percent=10" -d "applies_to=Shoes"

# Illegal launch (no offers) -> 409
curl -i -X POST localhost:8000/campaigns/2/launch

# Legal launch -> 303
curl -i -X POST localhost:8000/campaigns/1/launch

# Enroll
curl -X POST localhost:8000/s/<token>/enroll -d "identity=jane@example.com"

# Non-live scan
curl localhost:8000/s/<token-of-ended-campaign>
```
