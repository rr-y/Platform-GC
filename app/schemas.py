from datetime import datetime

from pydantic import BaseModel, field_validator
import phonenumbers


# ── Auth ──────────────────────────────────────────────────────────────────────

class OtpRequestIn(BaseModel):
    mobile_number: str

    @field_validator("mobile_number")
    @classmethod
    def normalize_mobile(cls, v: str) -> str:
        try:
            parsed = phonenumbers.parse(v, "IN")  # default region India
            if not phonenumbers.is_valid_number(parsed):
                raise ValueError("Invalid mobile number")
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            raise ValueError("Invalid mobile number format")


class OtpRequestOut(BaseModel):
    message: str
    expires_in_seconds: int


class OtpVerifyIn(BaseModel):
    mobile_number: str
    otp: str

    @field_validator("mobile_number")
    @classmethod
    def normalize_mobile(cls, v: str) -> str:
        try:
            parsed = phonenumbers.parse(v, "IN")
            if not phonenumbers.is_valid_number(parsed):
                raise ValueError("Invalid mobile number")
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            raise ValueError("Invalid mobile number format")


class UserOut(BaseModel):
    user_id: str
    mobile_number: str
    name: str | None
    role: str
    coin_balance: int = 0

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class RefreshIn(BaseModel):
    refresh_token: str


class AccessTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Coins ─────────────────────────────────────────────────────────────────────

class ExpiringSoon(BaseModel):
    coins: int
    expiry_at: str


class CoinBalanceOut(BaseModel):
    total_active_coins: int
    expiring_soon: ExpiringSoon | None = None


class CoinHistoryItem(BaseModel):
    id: str
    coins: int
    type: str
    status: str
    issued_at: str
    expiry_at: str
    reference_id: str | None

    model_config = {"from_attributes": True}


class PaginatedCoins(BaseModel):
    items: list[CoinHistoryItem]
    total: int
    page: int
    limit: int


# ── Transactions ──────────────────────────────────────────────────────────────

class TransactionIn(BaseModel):
    order_ref: str | None = None
    amount: float
    coins_to_redeem: int = 0
    coupon_code: str | None = None


class TransactionOut(BaseModel):
    transaction_id: str
    amount: float
    discount_applied: float
    coins_redeemed: int
    coins_redeemed_value: float
    final_amount: float
    coins_earned: int
    coins_balance_after: int


class TransactionItem(BaseModel):
    id: str
    amount: float
    coins_earned: int
    coins_used: int
    discount_amount: float
    status: str
    created_at: str

    model_config = {"from_attributes": True}


class PaginatedTransactions(BaseModel):
    items: list[TransactionItem]
    total: int
    page: int
    limit: int


# ── Coupons ───────────────────────────────────────────────────────────────────

class CouponValidateIn(BaseModel):
    code: str
    order_amount: float


class CouponValidateOut(BaseModel):
    valid: bool
    coupon_id: str | None = None
    discount_type: str | None = None
    discount_value: float | None = None
    discount_amount: float | None = None
    campaign_title: str | None = None


class AvailableOffer(BaseModel):
    coupon_id: str
    code: str
    campaign_title: str
    discount_type: str
    discount_value: float
    is_auto_apply: bool


# ── Admin — Campaigns ─────────────────────────────────────────────────────────

class CampaignIn(BaseModel):
    title: str
    type: str  # 'flat' | 'percentage' | 'coins_bonus'
    discount_value: float | None = None
    min_order_value: float = 0
    max_discount_cap: float | None = None
    valid_from: datetime
    valid_to: datetime
    audience_type: str = "all"
    usage_limit: int | None = None


class CampaignOut(BaseModel):
    id: str
    title: str
    type: str
    discount_value: float | None
    min_order_value: float
    max_discount_cap: float | None
    valid_from: str
    valid_to: str
    is_active: bool
    audience_type: str
    usage_limit: int | None
    usage_count: int

    model_config = {"from_attributes": True}


class CouponAddIn(BaseModel):
    codes: list[str]
    is_auto_apply: bool = False
    max_uses: int | None = None
    per_user_limit: int = 1


# ── Admin — Users ─────────────────────────────────────────────────────────────

class CoinAdjustIn(BaseModel):
    coins: int  # positive = add, negative = deduct
    notes: str | None = None


class UserAdminOut(BaseModel):
    user_id: str
    mobile_number: str
    name: str | None
    role: str
    is_active: bool
    coin_balance: int
    created_at: str

    model_config = {"from_attributes": True}
