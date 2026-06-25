"""
Data model.

Three tables: Campaign, Offer (many-to-one with Campaign, params stored as
JSON since each offer type has different fields), and Enrollment
(many-to-one with Campaign, unique per normalized identity).

Design notes (see TECH_NOTES.md for the full reasoning):
- `status` is the single source of truth for shopper visibility — the
  window (starts_at/ends_at) never drives it automatically.
- `version` is a plain integer bumped on every edit. It's the optimistic
  lock used to detect a stale edit (someone else changed the campaign
  between when you opened the edit form and when you hit save).
- `public_token` is a random opaque string, completely separate from the
  internal integer id. It is what the QR/link encodes. We never expose
  the internal `id` or `version` on the public surface.
"""
import enum
import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, JSON,
    UniqueConstraint, Enum as SAEnum,
)
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    LIVE = "live"
    ENDED = "ended"


class OfferType(str, enum.Enum):
    PRODUCT_PERCENT_DISCOUNT = "PRODUCT_PERCENT_DISCOUNT"
    CART_FIXED_DISCOUNT = "CART_FIXED_DISCOUNT"
    STICKER_EARN = "STICKER_EARN"


class IdentityType(str, enum.Enum):
    EMAIL = "email"
    PHONE = "phone"


def generate_public_token() -> str:
    # 16 bytes of randomness, URL-safe. Opaque on purpose — see TECH_NOTES.
    return secrets.token_urlsafe(16)


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    status = Column(SAEnum(CampaignStatus), nullable=False, default=CampaignStatus.DRAFT)

    # Optimistic-concurrency token. Bumped by every successful edit/transition.
    version = Column(Integer, nullable=False, default=0)

    # Opaque public identifier used in the shareable link / QR code.
    public_token = Column(String(64), unique=True, nullable=False, default=generate_public_token)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    offers = relationship("Offer", back_populates="campaign", cascade="all, delete-orphan")
    enrollments = relationship("Enrollment", back_populates="campaign", cascade="all, delete-orphan")

    # ---- lifecycle helpers -------------------------------------------------
    # Centralizing the rules here means both the internal routes (to decide
    # which buttons to show) and the route handlers (to enforce on submit)
    # call the exact same logic. There is no second copy of these rules in
    # the templates or in JS.

    def window_is_valid(self) -> bool:
        if self.starts_at is None or self.ends_at is None:
            return False
        if self.ends_at <= self.starts_at:
            return False
        if self.ends_at < utcnow().replace(tzinfo=self.ends_at.tzinfo):
            return False
        return True

    def is_launchable(self) -> bool:
        return self.window_is_valid() and len(self.offers) >= 1

    def can_edit(self) -> bool:
        return self.status == CampaignStatus.DRAFT

    def can_schedule(self) -> bool:
        return self.status == CampaignStatus.DRAFT and self.is_launchable()

    def can_launch(self) -> bool:
        return self.status in (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED) and self.is_launchable()

    def can_end(self) -> bool:
        return self.status == CampaignStatus.LIVE

    def is_shopper_visible_live(self) -> bool:
        return self.status == CampaignStatus.LIVE


class Offer(Base):
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    type = Column(SAEnum(OfferType), nullable=False)
    # Type-specific parameters, e.g. {"percent": 10, "applies_to": "Shoes"}.
    # Stored as JSON rather than separate columns per type so a campaign can
    # hold a list of heterogeneous offers (including repeats of one type)
    # without a sparse table full of nullable columns.
    params = Column(JSON, nullable=False, default=dict)

    campaign = relationship("Campaign", back_populates="offers")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        # The dedup rule from the spec, enforced at the database level so it
        # holds even under concurrent requests, not just in application code.
        UniqueConstraint("campaign_id", "identity_normalized", name="uq_campaign_identity"),
    )

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    identity_type = Column(SAEnum(IdentityType), nullable=False)
    identity_raw = Column(String(200), nullable=False)
    identity_normalized = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    campaign = relationship("Campaign", back_populates="enrollments")
