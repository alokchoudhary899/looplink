"""
Internal builder routes.

Every transition and edit is re-validated here on the server — the
templates only *reflect* what `Campaign.can_*()` says is currently
allowed (e.g. hide the Launch button), they never decide on their own.
That's the contract between client and server described in TECH_NOTES.md:
the server is the single source of truth, so even a stale page or a
hand-crafted request can't perform an illegal transition.
"""
import io

import qrcode
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Campaign, Offer, OfferType, CampaignStatus
from app.validators import validate_campaign_basics, validate_offer_params, OFFER_PARAM_SPECS
from app.web import templates

router = APIRouter(prefix="/campaigns", tags=["internal"])


def _get_campaign_or_404(db: Session, campaign_id: int) -> Campaign:
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def _public_url(request: Request, campaign: Campaign) -> str:
    return str(request.base_url).rstrip("/") + f"/s/{campaign.public_token}"


# ---- list -------------------------------------------------------------

@router.get("")
def list_campaigns(request: Request, db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "internal/list.html",
        {"campaigns": campaigns},
    )


# ---- create -------------------------------------------------------------

@router.get("/new")
def new_campaign_form(request: Request):
    return templates.TemplateResponse(
        request,
        "internal/new.html",
        {"errors": [], "form": {}},
    )


@router.post("/new")
def create_campaign(
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    starts_at: str = Form(""),
    ends_at: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        clean_name, clean_desc, starts_dt, ends_dt = validate_campaign_basics(
            name, description, starts_at, ends_at
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "internal/new.html",
            {
                "errors": [str(e)],
                "form": {"name": name, "description": description, "starts_at": starts_at, "ends_at": ends_at},
            },
            status_code=422,
        )

    campaign = Campaign(name=clean_name, description=clean_desc, starts_at=starts_dt, ends_at=ends_dt)
    db.add(campaign)
    db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign.id}", status_code=303)


# ---- detail / edit -------------------------------------------------------

@router.get("/{campaign_id}")
def campaign_detail(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    campaign = _get_campaign_or_404(db, campaign_id)
    return templates.TemplateResponse(
        request,
        "internal/detail.html",
        {
            "campaign": campaign,
            "offer_types": list(OfferType),
            "param_specs": OFFER_PARAM_SPECS,
            "public_url": _public_url(request, campaign) if campaign.status == CampaignStatus.LIVE else None,
            "errors": [],
        },
    )


@router.post("/{campaign_id}/edit")
def edit_campaign(
    campaign_id: int,
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    starts_at: str = Form(""),
    ends_at: str = Form(""),
    version: int = Form(...),
    db: Session = Depends(get_db),
):
    campaign = _get_campaign_or_404(db, campaign_id)

    # Stale-edit guard: the form the user is looking at carried the version
    # that was current when they opened it. If the row has moved on since
    # (someone else edited it, or — more importantly — transitioned its
    # status) we reject the save rather than silently overwrite newer state.
    if campaign.version != version or not campaign.can_edit():
        return templates.TemplateResponse(
            request,
            "internal/detail.html",
            {
                "campaign": campaign,
                "offer_types": list(OfferType),
                "param_specs": OFFER_PARAM_SPECS,
                "public_url": _public_url(request, campaign) if campaign.status == CampaignStatus.LIVE else None,
                "errors": [
                    "This campaign changed since you opened it (status or edits from elsewhere). "
                    "Reload to see the current version before editing again."
                ],
            },
            status_code=409,
        )

    try:
        clean_name, clean_desc, starts_dt, ends_dt = validate_campaign_basics(
            name, description, starts_at, ends_at
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "internal/detail.html",
            {
                "campaign": campaign,
                "offer_types": list(OfferType),
                "param_specs": OFFER_PARAM_SPECS,
                "public_url": None,
                "errors": [str(e)],
            },
            status_code=422,
        )

    campaign.name = clean_name
    campaign.description = clean_desc
    campaign.starts_at = starts_dt
    campaign.ends_at = ends_dt
    campaign.version += 1
    db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


# ---- offers ---------------------------------------------------------------

@router.post("/{campaign_id}/offers/add")
async def add_offer(
    campaign_id: int,
    request: Request,
    offer_type: str = Form(...),
    db: Session = Depends(get_db),
):
    campaign = _get_campaign_or_404(db, campaign_id)
    form = await request.form()

    errors = []
    if not campaign.can_edit():
        errors.append("Offers can only be changed while the campaign is in draft.")
    else:
        try:
            offer_type_enum = OfferType(offer_type)
            raw_params = {k: v for k, v in form.items() if k != "offer_type"}
            cleaned = validate_offer_params(offer_type_enum, raw_params)
            db.add(Offer(campaign_id=campaign.id, type=offer_type_enum, params=cleaned))
            db.commit()
        except (ValueError, KeyError) as e:
            errors.append(str(e))

    if errors:
        return templates.TemplateResponse(
            request,
            "internal/detail.html",
            {
                "campaign": campaign,
                "offer_types": list(OfferType),
                "param_specs": OFFER_PARAM_SPECS,
                "public_url": None,
                "errors": errors,
            },
            status_code=422,
        )
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.post("/{campaign_id}/offers/{offer_id}/delete")
def delete_offer(campaign_id: int, offer_id: int, db: Session = Depends(get_db)):
    campaign = _get_campaign_or_404(db, campaign_id)
    if not campaign.can_edit():
        raise HTTPException(status_code=409, detail="Offers can only be changed while the campaign is in draft.")
    offer = db.query(Offer).filter(Offer.id == offer_id, Offer.campaign_id == campaign_id).first()
    if offer:
        db.delete(offer)
        db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


# ---- lifecycle transitions -------------------------------------------------

def _render_with_error(request, db, campaign, message, status_code=409):
    campaign = _get_campaign_or_404(db, campaign.id)  # re-fetch fresh state
    return templates.TemplateResponse(
        request,
        "internal/detail.html",
        {
            "campaign": campaign,
            "offer_types": list(OfferType),
            "param_specs": OFFER_PARAM_SPECS,
            "public_url": _public_url(request, campaign) if campaign.status == CampaignStatus.LIVE else None,
            "errors": [message],
        },
        status_code=status_code,
    )


@router.post("/{campaign_id}/schedule")
def schedule_campaign(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    campaign = _get_campaign_or_404(db, campaign_id)
    if not campaign.can_schedule():
        return _render_with_error(
            request, db, campaign,
            "Cannot schedule: needs a draft status, a valid window, and at least one offer.",
        )
    campaign.status = CampaignStatus.SCHEDULED
    campaign.version += 1
    db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.post("/{campaign_id}/launch")
def launch_campaign(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    campaign = _get_campaign_or_404(db, campaign_id)
    if not campaign.can_launch():
        return _render_with_error(
            request, db, campaign,
            "Cannot launch: needs draft or scheduled status, a valid window, and at least one offer.",
        )
    campaign.status = CampaignStatus.LIVE
    campaign.version += 1
    db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.post("/{campaign_id}/end")
def end_campaign(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    campaign = _get_campaign_or_404(db, campaign_id)
    if not campaign.can_end():
        return _render_with_error(request, db, campaign, "Cannot end: campaign is not live.")
    campaign.status = CampaignStatus.ENDED
    campaign.version += 1
    db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


# ---- distribution (QR) -----------------------------------------------------

@router.get("/{campaign_id}/qr.png")
def campaign_qr(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    campaign = _get_campaign_or_404(db, campaign_id)
    if campaign.status != CampaignStatus.LIVE:
        raise HTTPException(status_code=409, detail="QR is only available for live campaigns.")
    img = qrcode.make(_public_url(request, campaign))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")
