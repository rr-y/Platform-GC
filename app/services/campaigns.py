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
                  ca.discount_value, ca.min_order_value, ca.max_discount_cap, ca.is_active
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
        row_dict = dict(row)
        row_dict["type"] = row_dict.get("campaign_type", row_dict.get("type"))
        discount = _compute_discount(row_dict, order_amount)
        available.append({
            "coupon_id": row["id"],
            "code": row["code"],
            "campaign_title": row["campaign_title"],
            "discount_type": row["campaign_type"],
            "discount_value": float(row["discount_value"] or 0),
            "is_auto_apply": True,
        })

    return available
