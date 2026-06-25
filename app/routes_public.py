"""
Public shopper routes.

No auth, no session. Every request resolves the link token fresh against
the database, so the page always reflects the campaign's *current*
status — there's no caching of "is this live" anywhere on this surface.

Boundary note (see TECH_NOTES.md "one model, two audiences"): these
handlers only ever pass a hand-picked dict into the templates — name,
description, offers' params, status-derived message — never the ORM
`Campaign`/`Offer` objects themselves. That's the one place in the code
that decides what a shopper is allowed to see.
"""
from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Campaign, Enrollment, CampaignStatus
from app.validators import normalize_identity
from app.web import templates

router = APIRouter(prefix="/s", tags=["public"])


def _public_offer_view(offer):
    return {"type": offer.type.value, "params": offer.params}


@router.get("/{token}")
def shopper_landing(token: str, request: Request, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.public_token == token).first()

    if not campaign:
        return templates.TemplateResponse(
            request, "public/invalid.html", {}, status_code=404
        )

    if campaign.status != CampaignStatus.LIVE:
        return templates.TemplateResponse(
            request,
            "public/not_live.html",
            {"name": campaign.name, "status": campaign.status.value},
        )

    return templates.TemplateResponse(
        request,
        "public/enroll.html",
        {
            "token": token,
            "name": campaign.name,
            "description": campaign.description,
            "errors": [],
        },
    )


@router.post("/{token}/enroll")
def enroll(token: str, request: Request, identity: str = Form(""), db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.public_token == token).first()

    if not campaign:
        return templates.TemplateResponse(request, "public/invalid.html", {}, status_code=404)

    if campaign.status != CampaignStatus.LIVE:
        # Covers the case where the campaign was ended between the shopper
        # loading the page and submitting the form.
        return templates.TemplateResponse(
            request,
            "public/not_live.html",
            {"name": campaign.name, "status": campaign.status.value},
        )

    try:
        identity_type, normalized = normalize_identity(identity)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "public/enroll.html",
            {
                "token": token, "name": campaign.name,
                "description": campaign.description, "errors": [str(e)],
            },
            status_code=422,
        )

    existing = (
        db.query(Enrollment)
        .filter(Enrollment.campaign_id == campaign.id, Enrollment.identity_normalized == normalized)
        .first()
    )
    already_enrolled = existing is not None

    if not existing:
        enrollment = Enrollment(
            campaign_id=campaign.id,
            identity_type=identity_type,
            identity_raw=identity.strip(),
            identity_normalized=normalized,
        )
        db.add(enrollment)
        try:
            db.commit()
        except IntegrityError:
            # Two requests for the same identity racing each other — the
            # unique constraint is the real guard, this just turns the
            # resulting DB error into the same "recognized" outcome.
            db.rollback()
            already_enrolled = True

    return templates.TemplateResponse(
        request,
        "public/success.html",
        {
            "name": campaign.name,
            "offers": [_public_offer_view(o) for o in campaign.offers],
            "already_enrolled": already_enrolled,
        },
    )
