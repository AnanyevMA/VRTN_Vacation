import os
import logging
from typing import List, Dict, Any, Optional
import httpx

logger = logging.getLogger("max_bot_client")

MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN", "")
MAX_API_URL = os.environ.get("MAX_API_URL", "https://api.max.ru/bot/v1")


class MaxBotClient:
    """
    Client for MAX Messenger Bot REST API.
    Sends replies, contact verification requests, and interactive buttons to employees in MAX.
    """

    def __init__(self, token: Optional[str] = None, base_url: Optional[str] = None):
        self.token = token or MAX_BOT_TOKEN
        self.base_url = (base_url or MAX_API_URL).rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.token and self.token.strip())

    def send_message(
        self,
        recipient_user_id: str,
        text: str,
        inline_keyboard: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Sends a text message with optional interactive buttons to a user in MAX."""
        if not self.is_configured():
            logger.info(f"[MAX SIMULATOR] To user {recipient_user_id}: {text}")
            return True

        url = f"{self.base_url}/messages/send"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "recipient_id": recipient_user_id,
            "text": text,
        }
        if inline_keyboard:
            payload["keyboard"] = {
                "type": "inline",
                "buttons": inline_keyboard,
            }

        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return True
                logger.warning(f"MAX Bot API error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Failed to send MAX message to {recipient_user_id}: {e}")
        return False

    def send_contact_request(self, recipient_user_id: str, text: str) -> bool:
        """Sends a message requesting the user to share their verified phone contact in MAX."""
        if not self.is_configured():
            logger.info(f"[MAX SIMULATOR] Contact request to {recipient_user_id}: {text}")
            return True

        url = f"{self.base_url}/messages/send"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "recipient_id": recipient_user_id,
            "text": text,
            "keyboard": {
                "type": "reply",
                "buttons": [[{"text": "📱 Подтвердить номер телефона", "request_contact": True}]],
            }
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send contact request to {recipient_user_id}: {e}")
        return False


max_bot_client = MaxBotClient()
