import base64
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PINTEREST_API_BASE = "https://api.pinterest.com/v5"


def get_pinterest_token() -> str:
    """Return the configured Pinterest access token."""
    return getattr(settings, "PINTEREST_ACCESS_TOKEN", "").strip()


def get_default_board_id() -> str:
    """Return the configured fallback Pinterest board ID."""
    return getattr(settings, "PINTEREST_BOARD_ID", "").strip()


def get_or_resolve_board_id(board_name: str, access_token: str = None) -> tuple[str | None, str | None]:
    """
    Find an existing board matching board_name, or create it, or fall back to default board.
    Returns (board_id, actual_board_name) or (None, None).
    """
    token = access_token or get_pinterest_token()
    if not token:
        return None, None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 1. Fetch user's existing boards
    try:
        resp = requests.get(
            f"{PINTEREST_API_BASE}/boards?page_size=100",
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            boards = data.get("items", [])
            for b in boards:
                if b.get("name", "").strip().lower() == board_name.strip().lower():
                    return b.get("id"), b.get("name")

            # If default board ID is specified in .env, check if it matches any
            default_id = get_default_board_id()
            if default_id:
                for b in boards:
                    if b.get("id") == default_id:
                        return default_id, b.get("name")
                return default_id, board_name

            # Fall back to first board if available
            if boards:
                return boards[0].get("id"), boards[0].get("name")

    except Exception as exc:
        logger.warning(f"Failed to fetch Pinterest boards: {exc}")

    # 2. Try creating a new board for this niche
    try:
        clean_name = board_name.strip()[:50]
        create_resp = requests.post(
            f"{PINTEREST_API_BASE}/boards",
            headers=headers,
            json={
                "name": clean_name,
                "description": f"Curated collection for {clean_name}",
                "privacy": "PUBLIC",
            },
            timeout=15,
        )
        if create_resp.status_code in (200, 201):
            created = create_resp.json()
            return created.get("id"), created.get("name", clean_name)
    except Exception as exc:
        logger.warning(f"Failed to auto-create Pinterest board: {exc}")

    default_id = get_default_board_id()
    if default_id:
        return default_id, board_name

    return None, None


def publish_pin_to_pinterest(
    title: str,
    description: str,
    link: str,
    image_url: str,
    alt_text: str,
    board_name: str,
    access_token: str = None,
) -> dict:
    """
    Publish a pin to Pinterest using API v5.
    Returns:
    {
        "success": bool,
        "pin_id": str or None,
        "pin_url": str or None,
        "board_name": str or None,
        "error": str or None,
    }
    """
    token = access_token or get_pinterest_token()
    if not token:
        return {
            "success": False,
            "error": "No PINTEREST_ACCESS_TOKEN configured in settings.",
        }

    board_id, actual_board = get_or_resolve_board_id(board_name, token)
    if not board_id:
        return {
            "success": False,
            "error": f"Could not find or create a Pinterest board for '{board_name}'.",
        }

    payload = {
        "title": title[:100],
        "description": description[:800],
        "link": link,
        "alt_text": alt_text[:500],
        "board_id": board_id,
        "media_source": {
            "source_type": "image_url",
            "url": image_url,
        },
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            f"{PINTEREST_API_BASE}/pins",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            pin_id = data.get("id")
            pin_url = f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else None
            return {
                "success": True,
                "pin_id": pin_id,
                "pin_url": pin_url,
                "board_name": actual_board or board_name,
                "error": None,
            }

        # If image_url failed (e.g. Pinterest crawler was blocked), fallback to image_base64
        try:
            img_resp = requests.get(image_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if img_resp.status_code == 200 and img_resp.content:
                b64_data = base64.b64encode(img_resp.content).decode("utf-8")
                content_type = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
                payload["media_source"] = {
                    "source_type": "image_base64",
                    "content_type": content_type,
                    "data": b64_data,
                }
                retry_resp = requests.post(
                    f"{PINTEREST_API_BASE}/pins",
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
                if retry_resp.status_code in (200, 201):
                    data = retry_resp.json()
                    pin_id = data.get("id")
                    pin_url = f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else None
                    return {
                        "success": True,
                        "pin_id": pin_id,
                        "pin_url": pin_url,
                        "board_name": actual_board or board_name,
                        "error": None,
                    }
        except Exception as img_exc:
            logger.warning(f"Base64 image fallback attempt failed: {img_exc}")

        err_data = resp.json() if resp.content else {}
        err_msg = err_data.get("message") or resp.text
        return {
            "success": False,
            "error": f"Pinterest API error ({resp.status_code}): {err_msg}",
        }
    except Exception as exc:
        logger.error(f"Failed to post to Pinterest: {exc}", exc_info=True)
        return {"success": False, "error": f"Connection error: {exc}"}
