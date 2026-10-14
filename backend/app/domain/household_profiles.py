"""Domain::HouseholdProfiles — Shopper, Household, HouseholdMember, DietaryProfile.

Also holds the Dietitian/Founder accounts (one `users` table with a role) and
taste/preference memory (requirement 1.2.12).
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.domain.enums import RestrictionKind, Severity, UserRole


class User(Base):
    """An account. `role` decides whether it acts as Shopper, Dietitian or Founder."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.shopper)
    password_hash: Mapped[str] = mapped_column(String(300))
    locale: Mapped[str] = mapped_column(String(20), default="en-AU")
    # Dietitian-only fields (class diagram: Dietitian.registrationNo / specialisation)
    registration_no: Mapped[str | None] = mapped_column(String(50), default=None)
    specialisation: Mapped[str | None] = mapped_column(String(120), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    households: Mapped[list["Household"]] = relationship(
        back_populates="shopper", cascade="all, delete-orphan"
    )

    @property
    def is_authorised_reviewer(self) -> bool:
        return self.role in (UserRole.dietitian, UserRole.founder)


class Household(Base):
    __tablename__ = "households"

    id: Mapped[int] = mapped_column(primary_key=True)
    shopper_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str] = mapped_column(String(80), default="Sydney Metro")

    shopper: Mapped[User] = relationship(back_populates="households")
    members: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="household", cascade="all, delete-orphan", order_by="HouseholdMember.id"
    )
    preferences: Mapped[list["Preference"]] = relationship(
        back_populates="household", cascade="all, delete-orphan", order_by="Preference.id"
    )

    @property
    def size(self) -> int:
        return max(1, len(self.members))

    def mandatory_restrictions(self) -> list[dict]:
        """Union of every member's non-preference restrictions (UC-10 ext 3a: strictest safe set)."""
        merged: dict[str, dict] = {}
        rank = {Severity.severe: 3, Severity.moderate: 2, Severity.mild: 1, Severity.preference: 0}
        for member in self.members:
            for profile in member.dietary_profiles:
                if profile.severity == Severity.preference:
                    continue
                current = merged.get(profile.restriction)
                if current is None or rank[profile.severity] > rank[current["severity"]]:
                    merged[profile.restriction] = {
                        "restriction": profile.restriction,
                        "severity": profile.severity,
                        "kind": profile.kind,
                        "source": "household",
                        "members": [member.name],
                    }
                else:
                    current["members"].append(member.name)
        return list(merged.values())

    def add_member(self, member: "HouseholdMember") -> None:
        self.members.append(member)


class HouseholdMember(Base):
    __tablename__ = "household_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"))
    name: Mapped[str] = mapped_column(String(80))
    age_group: Mapped[str] = mapped_column(String(20), default="adult")

    household: Mapped[Household] = relationship(back_populates="members")
    dietary_profiles: Mapped[list["DietaryProfile"]] = relationship(
        back_populates="member", cascade="all, delete-orphan"
    )

    def strictest_restrictions(self) -> list["DietaryProfile"]:
        return [p for p in self.dietary_profiles if p.severity != Severity.preference]


class DietaryProfile(Base):
    """One restriction held by one member, e.g. ("tree_nuts", allergy, severe)."""

    __tablename__ = "dietary_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("household_members.id"))
    restriction: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20), default=RestrictionKind.allergy)
    severity: Mapped[str] = mapped_column(String(20), default=Severity.severe)

    member: Mapped[HouseholdMember] = relationship(back_populates="dietary_profiles")

    def is_severe(self) -> bool:
        return self.severity == Severity.severe


class Preference(Base):
    """Taste & preference memory (1.2.12). Always secondary to mandatory restrictions."""

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"))
    kind: Mapped[str] = mapped_column(String(20))  # dislike | like | brand | avoid_brand
    value: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20), default="user")  # user | learned
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    household: Mapped[Household] = relationship(back_populates="preferences")
