from unittest.mock import AsyncMock, patch

import pytest

from app.services.notifications import (
    _send_push_or_sms,
    send_transaction_notification,
)


# ── _send_push_or_sms ─────────────────────────────────────────────────────────

async def test_push_succeeds_sms_skipped():
    with (
        patch("app.services.notifications.send_push", new_callable=AsyncMock) as push_mock,
        patch("app.services.notifications._send_sms", new_callable=AsyncMock) as sms_mock,
    ):
        push_mock.return_value = True
        channel = await _send_push_or_sms(
            "ExponentPushToken[abc]", "+919800000040", "title", "body"
        )

    assert channel == "push"
    push_mock.assert_awaited_once()
    sms_mock.assert_not_called()


async def test_push_fails_sms_sent():
    with (
        patch("app.services.notifications.send_push", new_callable=AsyncMock) as push_mock,
        patch("app.services.notifications._send_sms", new_callable=AsyncMock) as sms_mock,
    ):
        push_mock.return_value = False
        channel = await _send_push_or_sms(
            "ExponentPushToken[abc]", "+919800000041", "title", "body"
        )

    assert channel == "sms"
    push_mock.assert_awaited_once()
    sms_mock.assert_awaited_once()


async def test_no_token_sms_sent_directly():
    with (
        patch("app.services.notifications.send_push", new_callable=AsyncMock) as push_mock,
        patch("app.services.notifications._send_sms", new_callable=AsyncMock) as sms_mock,
    ):
        channel = await _send_push_or_sms(None, "+919800000042", "title", "body")

    assert channel == "sms"
    push_mock.assert_not_called()
    sms_mock.assert_awaited_once()


# ── send_transaction_notification threads push_token through ──────────────────

async def test_transaction_notification_uses_push_when_token_present():
    with (
        patch("app.services.notifications.send_push", new_callable=AsyncMock) as push_mock,
        patch("app.services.notifications._send_sms", new_callable=AsyncMock) as sms_mock,
    ):
        push_mock.return_value = True
        channel = await send_transaction_notification(
            mobile="+919800000050",
            name="Ravi",
            final_amount=500,
            coins_earned=25,
            coins_redeemed=0,
            coins_redeemed_value=0,
            balance=100,
            push_token="ExponentPushToken[abc]",
        )

    assert channel == "push"
    sms_mock.assert_not_called()


async def test_transaction_notification_sms_when_no_token():
    with (
        patch("app.services.notifications.send_push", new_callable=AsyncMock) as push_mock,
        patch("app.services.notifications._send_sms", new_callable=AsyncMock) as sms_mock,
    ):
        channel = await send_transaction_notification(
            mobile="+919800000051",
            name="Ravi",
            final_amount=500,
            coins_earned=25,
            coins_redeemed=0,
            coins_redeemed_value=0,
            balance=100,
        )

    assert channel == "sms"
    push_mock.assert_not_called()
    sms_mock.assert_awaited_once()
