# Multi-Branch & Franchise — Design Specification

Date: 2026-07-07
Status: Approved (Traditional POS §17 Phase J, scoped)

## 1. Scope decision

Full RBAC (Phase G) wasn't built — this platform still has one manager
account per restaurant, no cashier/kitchen role distinction enforced at the
API layer. Building a franchise-level permission model on top of RBAC that
doesn't exist yet would mean inventing both at once. **Deferred**: branch-level
role permissions distinct from an owner login.

What's real and buildable: an `Organization` grouping — one owner login that
owns several `Restaurant` branches, plus a roll-up sales report across them.
This is the actual data-model gap (`Restaurant` currently IS the account,
1:1) and is independently useful before any RBAC work lands.

## 2. Data model

- `organizations` — id, name, owner_email, password_hash (the multi-branch login, separate from any single branch's own login)
- `restaurants` gets `organization_id` (nullable FK) — null for today's single-branch restaurants, set when a branch is added to an organization.

## 3. Flow

1. Owner signs up an organization: `POST /api/v1/organizations/signup` (name, owner_email, password) → JWT (separate token audience `"org"` vs. the existing `"manager"` audience, so an org token can't be used against single-restaurant endpoints and vice versa).
2. Owner adds a branch: `POST /api/v1/organizations/branches` (creates a new `Restaurant` row with `organization_id` set — reuses the existing restaurant-creation shape, doesn't duplicate it).
3. `GET /api/v1/organizations/branches` — list all branches under the authenticated organization.
4. `GET /api/v1/organizations/rollup-sales?target_date=` — sums each branch's Z-report gross sales for the day into one cross-branch total + per-branch breakdown.

## 4. API surface (new `src/app/organizations/` module)

- `POST /api/v1/organizations/signup`
- `POST /api/v1/organizations/login`
- `POST /api/v1/organizations/branches`
- `GET /api/v1/organizations/branches`
- `GET /api/v1/organizations/rollup-sales?target_date=`

## 5. Testing

Unit: rollup math across 2+ branches. Integration: signup → add 2 branches → rollup reflects both.

## Related
- `docs/TRADITIONAL_POS_SYSTEM.md` §17 Phase J
- Branch-level RBAC explicitly deferred until Phase G's full role system exists (see §1)
