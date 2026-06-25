# LoopLink — Campaign Builder & Distribution

A small slice of LoopLink: an internal campaign builder and a public,
mobile-first shopper enrollment page.

## Stack

- **FastAPI** (routes/validation) + **SQLAlchemy** (ORM) + **SQLite** (single file DB)
- **Jinja2** server-rendered templates, plain HTML forms, a few lines of vanilla JS
  (no React/SPA, no build step)
- **qrcode** + **Pillow** to render the distribution QR code

## Setup & run

```bash
cd looplink
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

Open:
- Internal builder: http://127.0.0.1:8000/campaigns
- Public shopper page: you reach this via the link/QR a live campaign produces
  (`http://127.0.0.1:8000/s/<token>`), not directly.

The SQLite file `looplink.db` is created automatically on first run, in the
project root. Delete it to reset all data.

## Using the builder (internal)

1. **Campaigns list** (`/campaigns`) — shows every campaign and its status.
   Empty state when there are none yet.
2. **New campaign** (`/campaigns/new`) — set name, description, and the
   start/end window (UTC). This creates a **draft**.
3. **Campaign detail** (`/campaigns/<id>`) — once created, add offers here
   (pick a type from the dropdown, fill in its parameters, e.g. percent +
   applies_to for a percent discount). You can attach more than one offer,
   including repeats of the same type.
4. **Lifecycle buttons** on the detail page only appear when the action is
   currently legal:
   - **Schedule** — draft → scheduled (needs a valid window + ≥1 offer)
   - **Launch** — draft or scheduled → live (same requirements; opens
     enrollment immediately regardless of `starts_at`)
   - **End** — live → ended (closes enrollment)
   Editing name/description/window and adding/removing offers is only
   possible while the campaign is a draft.
5. **Distribute** — once live, the detail page shows the shareable link and
   a QR code pointing at it.

## Using the shopper page (public)

Open the link/QR from a live campaign's detail page:

- If the campaign is **live**, you'll see its name/description and a form
  asking for a phone number or email. Submitting enrolls you and shows the
  attached offers with their actual values.
- If the campaign is **not live** (draft, scheduled, or ended), the page
  shows that state instead of any offer.
- If the link doesn't resolve to any campaign at all, the page shows an
  "invalid link" state.
- Submitting the same identity again (even with different
  capitalization/spacing) is recognized rather than creating a duplicate
  enrollment.

## Exercising the two flows the brief calls out

**An illegal action (blocked):**
```bash
# create a draft, then try to launch it with zero offers
curl -X POST http://127.0.0.1:8000/campaigns/new -d "name=Test" -d "description=" \
  -d "starts_at=2026-08-01T10:00" -d "ends_at=2026-08-10T10:00"
curl -i -X POST http://127.0.0.1:8000/campaigns/1/launch   # -> 409, error message
```

**A non-live scan:** open `/campaigns/<id>` for any draft/ended campaign,
copy its public link pattern (`/s/<token>`, visible in code/db before it's
live) — or just open the link for a campaign you've since ended. The page
renders the appropriate non-live state, not the offer.

See `TECH_NOTES.md` for the design decisions, what was cut, and how the
stale-edit / duplicate-enrollment cases specifically work.

## Project layout

```
app/
  main.py              FastAPI app, mounts routers + static files
  database.py           SQLAlchemy engine/session
  models.py              Campaign, Offer, Enrollment, enums, lifecycle rules
  validators.py          offer-param + identity validation/normalization
  routes_internal.py     builder: list/create/edit/offers/lifecycle/QR
  routes_public.py        shopper: resolve token -> live/non-live/invalid, enroll
  web.py                  shared Jinja2Templates instance
  templates/internal/...  builder pages
  templates/public/...    shopper pages
  static/css, static/js
```
