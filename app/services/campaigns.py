import asyncpg

from app.models import utcnow


async def validate_coupon(
    code: str,
    user_id: str,
    order_amount: float,
    conn: asyncpg.Connection,
) -> tuple[dict, float]:
    """
    Validate a coupon for a user and order amount.
    Returns (coupon_row, discount_amount) or raises ValueError with reason.
    """
    now = utcnow()

    coupon = await conn.fetchrow(
        "SELECT * FROM coupons WHERE code = $1", code.upper()
    )
    if not coupon:
        raise ValueError("Coupon not found")

    if now < coupon["valid_from"] or now > coupon["valid_to"]:
        raise ValueError("Coupon has expired or is not yet active")

    if coupon["max_uses"] is not None and coupon["uses_count"] >= coupon["max_uses"]:
        raise ValueError("Coupon usage limit reached")

    user_uses = await conn.fetchval(
        """SELECT COUNT(*) FROM coupon_redemptions
           WHERE coupon_id = $1 AND user_id = $2""",
        coupon["id"], user_id,
    )
    if int(user_uses or 0) >= coupon["per_user_limit"]:
        raise ValueError("You have already used this coupon")

    campaign = await conn.fetchrow(
        "SELECT * FROM campaigns WHERE id = $1", coupon["campaign_id"]
    )
    if not campaign or not campaign["is_active"]:
        raise ValueError("Campaign is inactive")

    if order_amount < float(campaign["min_order_value"] or 0):
        raise ValueError(f"Minimum order value ₹{campaign['min_order_value']} required")

    # Cohort check for specific_users campaigns
    if campaign["audience_type"] == "specific_users":
        eligible = await conn.fetchval(
            """SELECT 1 FROM campaign_user_eligibility
               WHERE campaign_id = $1 AND user_id = $2""",
            campaign["id"], user_id,
        )
        if not eligible:
            raise ValueError("This offer is not available for your account")

    discount = _compute_discount(campaign, order_amount)
    return dict(coupon), discount


def _compute_discount(campaign: dict, order_amount: float) -> float:
    if campaign["type"] == "flat":
        return min(float(campaign["discount_value"] or 0), order_amount)

    if campaign["type"] == "percentage":
        discount = order_amount * float(campaign["discount_value"] or 0) / 100
        if campaign["max_discount_cap"]:
            discount = min(discount, float(campaign["max_discount_cap"]))
        return round(discount, 2)

    return 0.0  # coins_bonus — no direct monetary discount


async def get_available_coupons(
    user_id: str,
    order_amount: float,
    conn: asyncpg.Connection,
) -> list[dict]:
    """Return auto-applicable coupons valid for this user and order amount."""
    now = utcnow()

    rows = await conn.fetch(
        """SELECT c.*, ca.title AS campaign_title, ca.type AS campaign_type,
                  ca.discount_value, ca.min_order_value, ca.max_discount_cap,
                  ca.is_active, ca.audience_type, ca.image_url, ca.description
           FROM coupons c
           JOIN campaigns ca ON ca.id = c.campaign_id
           WHERE c.is_auto_apply = true
             AND c.valid_from <= $1
             AND c.valid_to >= $1
             AND ca.is_active = true""",
        now,
    )

    available = []
    for row in rows:
        if row["min_order_value"] and order_amount < float(row["min_order_value"]):
            continue
        if row["max_uses"] is not None and row["uses_count"] >= row["max_uses"]:
            continue

        # Cohort enforcement
        audience = row["audience_type"]
        if audience == "specific_users":
            eligible = await conn.fetchval(
                """SELECT 1 FROM campaign_user_eligibility
                   WHERE campaign_id = $1 AND user_id = $2""",
                row["campaign_id"], user_id,
            )
            if not eligible:
                continue
        elif audience == "has_coins":
            balance = await conn.fetchval(
                """SELECT COALESCE(SUM(coins), 0) FROM coins_ledger
                   WHERE user_id = $1 AND status = 'active' AND expiry_at > $2""",
                user_id, now,
            )
            if int(balance or 0) <= 0:
                continue
        elif audience == "new_users":
            txn_count = await conn.fetchval(
                "SELECT COUNT(*) FROM transactions WHERE user_id = $1", user_id
            )
            if int(txn_count or 0) > 0:
                continue

        available.append({
            "coupon_id": row["id"],
            "code": row["code"],
            "campaign_title": row["campaign_title"],
            "discount_type": row["campaign_type"],
            "discount_value": float(row["discount_value"] or 0),
            "is_auto_apply": True,
            "image_url": row["image_url"],
            "description": row["description"],
            "valid_to": row["valid_to"].isoformat() if row["valid_to"] else None,
        })

    return available


async def get_offer_banners(
    user_id: str,
    conn: asyncpg.Connection,
    limit: int = 10,
) -> list[dict]:
    """Return all active campaigns visible to this user for banner display."""
    now = utcnow()

    rows = await conn.fetch(
        """SELECT ca.id AS campaign_id, ca.title, ca.description, ca.image_url,
                  ca.type, ca.discount_value, ca.min_order_value, ca.valid_to,
                  ca.audience_type,
                  (SELECT c.code FROM coupons c
                   WHERE c.campaign_id = ca.id
                   ORDER BY c.id ASC LIMIT 1) AS coupon_code,
                  (SELECT c.is_auto_apply FROM coupons c
                   WHERE c.campaign_id = ca.id
                   ORDER BY c.id ASC LIMIT 1) AS is_auto_apply
           FROM campaigns ca
           WHERE ca.is_active = true
             AND ca.valid_from <= $1
             AND ca.valid_to >= $1
           ORDER BY ca.valid_to ASC
           LIMIT $2""",
        now, limit,
    )

    banners = []
    for row in rows:
        audience = row["audience_type"]

        # Cohort enforcement
        if audience == "specific_users":
            eligible = await conn.fetchval(
                """SELECT 1 FROM campaign_user_eligibility
                   WHERE campaign_id = $1 AND user_id = $2""",
                row["campaign_id"], user_id,
            )
            if not eligible:
                continue
        elif audience == "has_coins":
            balance = await conn.fetchval(
                """SELECT COALESCE(SUM(coins), 0) FROM coins_ledger
                   WHERE user_id = $1 AND status = 'active' AND expiry_at > $2""",
                user_id, now,
            )
            if int(balance or 0) <= 0:
                continue
        elif audience == "new_users":
            txn_count = await conn.fetchval(
                "SELECT COUNT(*) FROM transactions WHERE user_id = $1", user_id
            )
            if int(txn_count or 0) > 0:
                continue

        banners.append({
            "campaign_id": row["campaign_id"],
            "title": row["title"],
            "description": row["description"],
            "image_url": row["image_url"],
            "discount_type": row["type"],
            "discount_value": float(row["discount_value"] or 0),
            "min_order_value": float(row["min_order_value"] or 0),
            "valid_to": row["valid_to"].isoformat(),
            "coupon_code": row["coupon_code"],
            "is_auto_apply": row["is_auto_apply"] or False,
        })

    return banners
