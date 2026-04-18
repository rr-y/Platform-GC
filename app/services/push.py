import logging

import httpx

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


async def send_push(
    token: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> bool:
    """
    Send a single push notification via the Expo Push API.

    Returns True on delivery ticket acceptance, False on any failure (network
    error, Expo rejection, bad token). The caller is responsible for falling
    back to another channel on False.
    """
    payload: dict = {
        "to": token,
        "title": title,
        "body": body,
        "sound": "default",
        "priority": "high",
    }
    if data:
        payload["data"] = data

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(EXPO_PUSH_URL, json=payload)
    except httpx.HTTPError as e:
        logger.warning("Expo push request failed: %s", e)
        return False

    if resp.status_code != 200:
        logger.warning(
            "Expo push returned HTTP %s: %s", resp.status_code, resp.text[:200]
        )
        return False

    body_json = resp.json()
    ticket = body_json.get("data")
    if isinstance(ticket, dict) and ticket.get("status") == "error":
        logger.warning(
            "Expo push ticket error for token %s…: %s",
            token[:20], ticket.get("message"),
        )
        return False

    logger.info("Push sent to token %s…", token[:20])
    return True
