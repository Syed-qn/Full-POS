"""Branch-scoped staff identity.

`StaffMember.id` is a platform-wide surrogate key. Before this module existed the
terminal asked for that id and looked it up globally, so a manager at restaurant C
who assumed they were "manager 1" with the near-universal PIN 1234 would
authenticate into restaurant A instead — a cross-tenant login, not a collision.

The fix mirrors how POS integrations scope everything (account + location, e.g.
the Cratis order payload): a login is only ever resolved *inside* one branch.

- ``staff_code`` — the number staff type; restarts at 1 per restaurant.
- ``Restaurant.store_code`` / ``location_uuid`` — the branch key the terminal
  supplies, non-guessable so it cannot be swapped for someone else's branch.

With the branch fixed, identical PINs across restaurants are harmless.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.auth import verify_password
from app.identity.models import Restaurant
from app.organizations.models import Organization
from app.staff.models import StaffMember


class WeakPinError(ValueError):
    """PIN is guessable enough that a wrong-store login would likely succeed."""


class DuplicatePinError(ValueError):
    """Another active staff member in the same restaurant already uses this PIN."""


#: Rejected outright. These are the PINs people actually pick, and a shared PIN
#: inside one restaurant also makes manager-approval attribution ambiguous
#: (approvals match a manager by PIN alone).
WEAK_PINS = frozenset(
    {
        "0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999",
        "1234", "12345", "123456", "4321", "54321", "654321", "1212", "2121",
        "1004", "2000", "2020", "2580", "0852", "1313", "6969", "1122", "1010",
    }
)


def validate_pin_strength(pin: str) -> str:
    """Return the PIN, or raise WeakPinError. Digit-only PINs are still allowed —
    this rejects the guessable ones, it does not force alphanumerics on a keypad."""
    p = (pin or "").strip()
    if len(p) < 4:
        raise WeakPinError("PIN must be at least 4 digits")
    if p in WEAK_PINS:
        raise WeakPinError("that PIN is too common — choose a different one")
    if len(set(p)) == 1:
        raise WeakPinError("PIN cannot be the same digit repeated")
    if p.isdigit() and _is_sequential(p):
        raise WeakPinError("PIN cannot be a run of consecutive digits")
    return p


def _is_sequential(p: str) -> bool:
    steps = {ord(b) - ord(a) for a, b in zip(p, p[1:])}
    return steps in ({1}, {-1})


async def next_staff_code(session: AsyncSession, *, restaurant_id: int) -> int:
    """Next free staff number for this restaurant (1-based, never reused-down).

    Uses max+1 rather than count+1 so deactivating staff cannot hand a retired
    number to a new hire — a recycled number would silently re-point clock-ins,
    approvals and tip attribution in the audit trail.
    """
    highest = await session.scalar(
        select(func.max(StaffMember.staff_code)).where(
            StaffMember.restaurant_id == restaurant_id
        )
    )
    return int(highest or 0) + 1


async def assert_pin_unique_in_restaurant(
    session: AsyncSession,
    *,
    restaurant_id: int,
    pin: str,
    exclude_staff_id: int | None = None,
) -> None:
    """Reject a PIN already held by another active member of the same restaurant.

    Manager approvals resolve the approver by PIN alone (see approvals.py), so two
    managers sharing 1234 would attribute every void/discount to whichever row the
    query returned first. Cross-restaurant duplicates are fine and stay allowed.
    """
    rows = (
        await session.scalars(
            select(StaffMember).where(
                StaffMember.restaurant_id == restaurant_id,
                StaffMember.is_active.is_(True),
            )
        )
    ).all()
    for row in rows:
        if exclude_staff_id is not None and row.id == exclude_staff_id:
            continue
        if verify_password(pin, row.pin_hash):
            raise DuplicatePinError(
                "another active staff member here already uses this PIN"
            )


async def resolve_store(session: AsyncSession, store: str) -> Restaurant | None:
    """Resolve the terminal's branch key to a Restaurant.

    Accepts the human-typed ``store_code`` (case-insensitive) or the machine
    ``location_uuid`` a provisioned terminal stores. ``public_slug`` is NOT
    accepted: it is published on ordering links, so honouring it here would put
    a guessable value back on the authentication path.
    """
    key = (store or "").strip()
    if not key:
        return None
    return await session.scalar(
        select(Restaurant).where(
            (Restaurant.store_code == key.upper())
            | (Restaurant.location_uuid == key.lower())
        )
    )


async def resolve_location(
    session: AsyncSession, *, account: str | None, location: str
) -> Restaurant | None:
    """Resolve an account + location pair to one branch.

    ``location`` alone already identifies the branch — it is a uuid, unique
    platform-wide. ``account`` is checked as a second factor: a link whose
    account does not own that location is rejected rather than followed, which
    is what turns a mistyped or stale pairing link into a refusal instead of a
    sign-in somewhere unintended.
    """
    restaurant = await resolve_store(session, location)
    if restaurant is None:
        return None
    if account:
        org = (
            await session.scalar(
                select(Organization).where(
                    Organization.account_uuid == account.strip().lower()
                )
            )
            if account.strip()
            else None
        )
        if org is None or restaurant.organization_id != org.id:
            return None
    return restaurant


async def find_staff_for_login(
    session: AsyncSession,
    *,
    restaurant_id: int,
    staff_code: int | None,
    staff_id: int | None,
) -> StaffMember | None:
    """Locate a login candidate WITHIN one restaurant.

    Both lookups are restaurant-scoped; `staff_id` is retained for terminals and
    fixtures that still hold a surrogate id, and is no longer a global lookup.
    """
    if staff_code is not None:
        return await session.scalar(
            select(StaffMember).where(
                StaffMember.restaurant_id == restaurant_id,
                StaffMember.staff_code == staff_code,
            )
        )
    if staff_id is not None:
        return await session.scalar(
            select(StaffMember).where(
                StaffMember.restaurant_id == restaurant_id,
                StaffMember.id == staff_id,
            )
        )
    return None
