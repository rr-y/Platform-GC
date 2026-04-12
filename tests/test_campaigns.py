from datetime import datetime, timedelta, timezone

import pytest

from app.models import Campaign, Coupon, User, utcnow
from app.services.auth import OTP_KEY


# ── Helpers ───────────────────────────────────────────────────────────────────

def future(days=30) -> str:
    return (utcnow() + timedelta(days=days)).isoformat()

def past(days=1) -> str:
    return (utcnow() - timedelta(days=days)).isoformat()


async def make_admin(db, mobile="+919600000001") -> User:
    user = User(mobile_number=mobile, role="admin")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login(client, redis, mobile, role="user"):
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def admin_headers(client, redis, db, mobile="+919600000001"):
    await make_admin(db, mobile)
    return await login(client, redis, mobile)


async def make_campaign(db, **kwargs) -> Campaign:
    defaults = dict(
        title="Test Sale",
        type="flat",
        discount_value=50.0,
        min_order_value=200.0,
        max_discount_cap=None,
        valid_from=utcnow() - timedelta(days=1),
        valid_to=utcnow() + timedelta(days=30),
        is_active=True,
        audience_type="all",
    )
    defaults.update(kwargs)
    c = Campaign(**defaults)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def make_coupon(db, campaign: Campaign, code="SAVE50", **kwargs) -> Coupon:
    defaults = dict(
        campaign_id=campaign.id,
        code=code,
        is_auto_apply=False,
        max_uses=None,
        uses_count=0,
        per_user_limit=1,
        valid_from=campaign.valid_from,
        valid_to=campaign.valid_to,
    )
    defaults.update(kwargs)
    c = Coupon(**defaults)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


# ── Admin — Campaign CRUD ─────────────────────────────────────────────────────

async def test_create_campaign(client, db, redis):
    headers = await admin_headers(client, redis, db, "+919600000001")
    resp = await client.post(
        "/api/v1/admin/campaigns",
        json={
            "title": "Summer Sale",
            "type": "percentage",
            "discount_value": 15.0,
            "min_order_value": 300.0,
            "max_discount_cap": 200.0,
            "valid_from": past(1),
            "valid_to": future(30),
        },
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Summer Sale"
    assert data["type"] == "percentage"
    assert data["is_active"] is True


async def test_list_campaigns(client, db, redis):
    headers = await admin_headers(client, redis, db, "+919600000002")
    await make_campaign(db, title="Camp A")
    await make_campaign(db, title="Camp B")

    resp = await client.get("/api/v1/admin/campaigns", headers=headers)
    assert resp.status_code == 200
    titles = [c["title"] for c in resp.json()]
    assert "Camp A" in titles
    assert "Camp B" in titles


async def test_update_campaign(client, db, redis):
    headers = await admin_headers(client, redis, db, "+919600000003")
    campaign = await make_campaign(db, title="Old Title")

    resp = await client.patch(
        f"/api/v1/admin/campaigns/{campaign.id}",
        json={"title": "New Title", "is_active": False},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "New Title"
    assert resp.json()["is_active"] is False


async def test_deactivate_campaign(client, db, redis):
    headers = await admin_headers(client, redis, db, "+919600000004")
    campaign = await make_campaign(db)

    resp = await client.delete(f"/api/v1/admin/campaigns/{campaign.id}", headers=headers)
    assert resp.status_code == 204

    await db.refresh(campaign)
    assert campaign.is_active is False


async def test_add_coupons_to_campaign(client, db, redis):
    headers = await admin_headers(client, redis, db, "+919600000005")
    campaign = await make_campaign(db)

    resp = await client.post(
        f"/api/v1/admin/campaigns/{campaign.id}/coupons",
        json={"codes": ["FLAT50", "FLAT100"], "per_user_limit": 1},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["count"] == 2
    assert "FLAT50" in resp.json()["created"]


async def test_admin_required_for_campaigns(client, db, redis):
    # Regular user cannot access admin endpoints
    mobile = "+919600000099"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = await client.get("/api/v1/admin/campaigns", headers=headers)
    assert resp.status_code == 403


# ── Coupon Validation ─────────────────────────────────────────────────────────

async def test_valid_flat_coupon(client, db, redis):
    campaign = await make_campaign(db, type="flat", discount_value=100.0, min_order_value=200.0)
    await make_coupon(db, campaign, code="FLATVALID")

    mobile = "+919600000010"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    login_resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"mobile_number": mobile, "otp": "123456"},
    )
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/coupons/validate",
        json={"code": "FLATVALID", "order_amount": 500.0},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["discount_amount"] == 100.0
    assert data["discount_type"] == "flat"


async def test_valid_percentage_coupon(client, db, redis):
    campaign = await make_campaign(db, type="percentage", discount_value=20.0,
                                    min_order_value=0, max_discount_cap=500.0)
    await make_coupon(db, campaign, code="PCT20")

    mobile = "+919600000011"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post("/api/v1/auth/otp/verify",
                              json={"mobile_number": mobile, "otp": "123456"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    # 20% of ₹1000 = ₹200
    resp = await client.post("/api/v1/coupons/validate",
                              json={"code": "PCT20", "order_amount": 1000.0}, headers=headers)
    assert resp.json()["valid"] is True
    assert resp.json()["discount_amount"] == 200.0


async def test_percentage_coupon_capped(client, db, redis):
    campaign = await make_campaign(db, type="percentage", discount_value=50.0,
                                    min_order_value=0, max_discount_cap=100.0)
    await make_coupon(db, campaign, code="PCT50CAP")

    mobile = "+919600000012"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post("/api/v1/auth/otp/verify",
                              json={"mobile_number": mobile, "otp": "123456"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    # 50% of ₹500 = ₹250, but capped at ₹100
    resp = await client.post("/api/v1/coupons/validate",
                              json={"code": "PCT50CAP", "order_amount": 500.0}, headers=headers)
    assert resp.json()["valid"] is True
    assert resp.json()["discount_amount"] == 100.0


async def test_expired_coupon_rejected(client, db, redis):
    campaign = await make_campaign(
        db,
        valid_from=utcnow() - timedelta(days=10),
        valid_to=utcnow() - timedelta(days=1),   # expired yesterday
    )
    coupon = await make_coupon(
        db, campaign, code="EXPIRED",
        valid_from=campaign.valid_from, valid_to=campaign.valid_to,
    )
    mobile = "+919600000013"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post("/api/v1/auth/otp/verify",
                              json={"mobile_number": mobile, "otp": "123456"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.post("/api/v1/coupons/validate",
                              json={"code": "EXPIRED", "order_amount": 500.0}, headers=headers)
    assert resp.json()["valid"] is False


async def test_coupon_usage_limit_reached(client, db, redis):
    campaign = await make_campaign(db)
    coupon = await make_coupon(db, campaign, code="MAXED", max_uses=2)
    # Manually set uses_count to limit
    coupon.uses_count = 2
    await db.commit()

    mobile = "+919600000014"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post("/api/v1/auth/otp/verify",
                              json={"mobile_number": mobile, "otp": "123456"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.post("/api/v1/coupons/validate",
                              json={"code": "MAXED", "order_amount": 500.0}, headers=headers)
    assert resp.json()["valid"] is False


async def test_min_order_value_not_met(client, db, redis):
    campaign = await make_campaign(db, min_order_value=1000.0)
    await make_coupon(db, campaign, code="MINORDER")

    mobile = "+919600000015"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post("/api/v1/auth/otp/verify",
                              json={"mobile_number": mobile, "otp": "123456"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.post("/api/v1/coupons/validate",
                              json={"code": "MINORDER", "order_amount": 300.0}, headers=headers)
    assert resp.json()["valid"] is False


async def test_per_user_limit_enforced(client, db, redis):
    """User cannot use same coupon twice when per_user_limit=1."""
    campaign = await make_campaign(db, discount_value=50.0, min_order_value=0)
    await make_coupon(db, campaign, code="ONCE", per_user_limit=1)

    mobile = "+919600000016"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post("/api/v1/auth/otp/verify",
                              json={"mobile_number": mobile, "otp": "123456"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    # First use via transaction
    await client.post("/api/v1/transactions",
                       json={"amount": 500.0, "coupon_code": "ONCE", "order_ref": "ONCE-1"},
                       headers=headers)

    # Second validation should fail
    resp = await client.post("/api/v1/coupons/validate",
                              json={"code": "ONCE", "order_amount": 500.0}, headers=headers)
    assert resp.json()["valid"] is False


# ── Available Coupons ─────────────────────────────────────────────────────────

async def test_available_auto_apply_coupons(client, db, redis):
    campaign = await make_campaign(db, title="Auto Deal", discount_value=30.0, min_order_value=200.0)
    await make_coupon(db, campaign, code="AUTO30", is_auto_apply=True)

    mobile = "+919600000020"
    await redis.set(OTP_KEY.format(mobile), "123456", ex=300)
    resp = await client.post("/api/v1/auth/otp/verify",
                              json={"mobile_number": mobile, "otp": "123456"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.get("/api/v1/coupons/available?order_amount=500.0", headers=headers)
    assert resp.status_code == 200
    codes = [o["code"] for o in resp.json()]
    assert "AUTO30" in codes


# ── Admin — Users ─────────────────────────────────────────────────────────────

async def test_admin_list_users(client, db, redis):
    headers = await admin_headers(client, redis, db, "+919600000030")
    resp = await client.get("/api/v1/admin/users", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_admin_coin_adjustment(client, db, redis):
    headers = await admin_headers(client, redis, db, "+919600000031")

    # Create a regular user
    user = User(mobile_number="+919600000032")
    db.add(user)
    await db.commit()
    await db.refresh(user)

    resp = await client.post(
        f"/api/v1/admin/users/{user.id}/coins/adjust",
        json={"coins": 500, "notes": "Welcome bonus"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["balance_after"] == 500


async def test_admin_coin_adjustment_zero_rejected(client, db, redis):
    headers = await admin_headers(client, redis, db, "+919600000033")
    user = User(mobile_number="+919600000034")
    db.add(user)
    await db.commit()

    resp = await client.post(
        f"/api/v1/admin/users/{user.id}/coins/adjust",
        json={"coins": 0},
        headers=headers,
    )
    assert resp.status_code == 400
