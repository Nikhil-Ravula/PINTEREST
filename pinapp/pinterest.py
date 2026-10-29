import base64
import logging
import os
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PINTEREST_API_BASE = "https://api.pinterest.com/v5"


def get_pinterest_token() -> str:
    """Return the configured Pinterest access token."""
    return os.getenv("PINTEREST_ACCESS_TOKEN", "") or getattr(settings, "PINTEREST_ACCESS_TOKEN", "").strip()


def get_default_board_id() -> str:
    """Return the configured fallback Pinterest board ID."""
    return os.getenv("PINTEREST_BOARD_ID", "") or getattr(settings, "PINTEREST_BOARD_ID", "").strip()


def refresh_pinterest_token() -> str | None:
    """Use refresh_token to automatically obtain a fresh access_token from Pinterest."""
    refresh_token = os.getenv("PINTEREST_REFRESH_TOKEN", "") or getattr(settings, "PINTEREST_REFRESH_TOKEN", "").strip()
    client_id = os.getenv("PINTEREST_APP_ID", "") or getattr(settings, "PINTEREST_APP_ID", "1631413").strip()
    client_secret = os.getenv("PINTEREST_APP_SECRET", "") or getattr(settings, "PINTEREST_APP_SECRET", "").strip()
    if not refresh_token or not client_secret:
        return None

    auth_str = f"{client_id}:{client_secret}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    try:
        resp = requests.post("https://api.pinterest.com/v5/oauth/token", headers=headers, data=data, timeout=30)
        if resp.status_code in (200, 201):
            token_data = resp.json()
            new_token = token_data.get("access_token")
            if new_token:
                from pinapp.views import update_env_variable
                update_env_variable("PINTEREST_ACCESS_TOKEN", new_token)
                new_refresh = token_data.get("refresh_token")
                if new_refresh:
                    update_env_variable("PINTEREST_REFRESH_TOKEN", new_refresh)
                return new_token
    except Exception as exc:
        logger.warning(f"Failed to refresh Pinterest token: {exc}")
    return None


def get_configured_boards() -> list[str]:
    """Return the list of user's Pinterest boards from settings or env."""
    custom = os.getenv("PINTEREST_BOARDS", "")
    if custom:
        return [b.strip() for b in custom.split(",") if b.strip()]
    return list(getattr(settings, "PINTEREST_DEFAULT_BOARDS", []))


KNOWN_BOARDS = {
    "mobile accessories & gadgets": "1130192537678736048",
    "modern home decor": "1130192537678745048",
    "laptop accessories & setup": "1130192537678749926",
    "best smartphones & reviews": "1130192537678749931",
    "best laptops & reviews": "1130192537678749916",
    "best watches & smartwatches": "1130192537678753798",
    "summer beauty & fashion": "1130192537678738324",
    "women outfit ideas": "1130192537678736067",
}


def get_or_resolve_board_id(board_name: str, access_token: str = None) -> tuple[str, str]:
    """
    Find an existing board matching board_name, or create it, or fall back to known user boards.
    Guaranteed to return (board_id, actual_board_name).
    """
    clean_key = board_name.strip().lower()

    # 1. Exact match in known boards
    if clean_key in KNOWN_BOARDS:
        return KNOWN_BOARDS[clean_key], board_name

    # 2. Partial match in known boards
    for name, bid in KNOWN_BOARDS.items():
        if name in clean_key or clean_key in name:
            return bid, board_name

    # 3. Smart niche keyword mapping for AI-suggested boards
    if any(k in clean_key for k in ("decor", "home", "living", "boho", "cushion", "furniture", "kitchen", "pillow")):
        return KNOWN_BOARDS["modern home decor"], "Modern Home Decor"
    if any(k in clean_key for k in ("laptop", "computer", "macbook", "pc", "desk")):
        return KNOWN_BOARDS["best laptops & reviews"], "Best Laptops & Reviews"
    if any(k in clean_key for k in ("phone", "mobile", "gadget", "charger", "cable", "case")):
        return KNOWN_BOARDS["mobile accessories & gadgets"], "Mobile Accessories & Gadgets"
    if any(k in clean_key for k in ("watch", "smartwatch", "fitness", "tracker")):
        return KNOWN_BOARDS["best watches & smartwatches"], "Best Watches & Smartwatches"
    if any(k in clean_key for k in ("fashion", "dress", "outfit", "clothing", "wear")):
        return KNOWN_BOARDS["women outfit ideas"], "Women Outfit Ideas"
    if any(k in clean_key for k in ("beauty", "skincare", "makeup", "summer")):
        return KNOWN_BOARDS["summer beauty & fashion"], "Summer Beauty & Fashion"

    # 4. If token available, attempt live board search or creation via Pinterest API
    token = access_token or get_pinterest_token()
    if token:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.get(
                f"{PINTEREST_API_BASE}/boards?page_size=100",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                boards = resp.json().get("items", [])
                for b in boards:
                    if b.get("name", "").strip().lower() == clean_key:
                        return b.get("id"), b.get("name")
        except Exception as exc:
            logger.warning(f"Failed to fetch Pinterest boards: {exc}")

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
                timeout=10,
            )
            if create_resp.status_code in (200, 201):
                created = create_resp.json()
                return created.get("id"), created.get("name", clean_name)
        except Exception as exc:
            logger.warning(f"Failed to auto-create Pinterest board: {exc}")

    # 5. Fallback to configured default board or first known board
    default_id = get_default_board_id()
    if default_id:
        return default_id, board_name

    return KNOWN_BOARDS["mobile accessories & gadgets"], "Mobile Accessories & Gadgets"


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
            "error": "No Pinterest token found. Please visit https://6049.pythonanywhere.com/pinterest/connect/ to link your account.",
        }

    board_id, actual_board = get_or_resolve_board_id(board_name, token)

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

        # If token expired (401), try automatic token refresh and retry
        if resp.status_code == 401:
            logger.info("Pinterest token returned 401, attempting token refresh...")
            new_token = refresh_pinterest_token()
            if new_token:
                token = new_token
                headers["Authorization"] = f"Bearer {token}"
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

        # Format user-friendly guidance for known Pinterest response codes
        if resp.status_code == 401:
            return {
                "success": False,
                "error": "Pinterest token expired or missing write permissions. Please visit https://6049.pythonanywhere.com/pinterest/connect/ to authorize.",
            }
        if "Trial access" in err_msg or (resp.status_code == 403 and "trial" in str(err_msg).lower()):
            return {
                "success": False,
                "error": "Pinterest App has Trial access. In developer.pinterest.com -> Your App, click 'Apply for Standard access' to publish pins live to Pinterest boards.",
            }

        return {
            "success": False,
            "error": f"Pinterest API error ({resp.status_code}): {err_msg}",
        }
    except Exception as exc:
        logger.error(f"Failed to post to Pinterest: {exc}", exc_info=True)
        return {"success": False, "error": f"Connection error: {exc}"}
