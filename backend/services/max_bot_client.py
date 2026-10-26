import os
import json
import logging
from typing import List, Dict, Any, Optional
import httpx

logger = logging.getLogger("max_bot_client")

def _ensure_env_loaded():
    if not os.environ.get("MAX_BOT_TOKEN"):
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v

_ensure_env_loaded()

MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN", "")
MAX_API_URL = os.environ.get("MAX_API_URL", "https://platform-api2.max.ru")


class MaxBotClient:
    """
    Client for MAX Messenger Bot REST API (platform-api2.max.ru).
    Sends replies, contact verification requests, and interactive buttons to employees in MAX.
    """

    def __init__(self, token: Optional[str] = None, base_url: Optional[str] = None):
        _ensure_env_loaded()
        self._token = token
        self.base_url = (base_url or os.environ.get("MAX_API_URL", "https://platform-api2.max.ru")).rstrip("/")
        self._bot_user_id: Optional[str] = None
        self._client = httpx.Client(
            timeout=8.0,
            verify=True,
            limits=httpx.Limits(max_keepalive_connections=3, max_connections=8),
        )

    @property
    def token(self) -> str:
        return self._token or os.environ.get("MAX_BOT_TOKEN", "")

    def is_configured(self) -> bool:
        return bool(self.token and self.token.strip())

    def get_bot_user_id(self) -> Optional[str]:
        """Returns and caches the bot's own user_id from /me to avoid self-messaging loops."""
        if self._bot_user_id:
            return self._bot_user_id
        if not self.is_configured():
            return None
        try:
            headers = {"Authorization": self.token}
            resp = self._client.get(f"{self.base_url}/me", headers=headers)
            if resp.status_code == 200:
                self._bot_user_id = str(resp.json().get("user_id") or "")
                return self._bot_user_id
        except Exception as e:
            logger.debug(f"Could not fetch bot self-info: {e}")
        return self._bot_user_id

    def send_message(
        self,
        recipient_user_id: str,
        text: str,
        inline_keyboard: Optional[List[Dict[str, Any]]] = None,
        chat_id: Optional[str] = None,
    ) -> bool:
        """Sends a text message with optional interactive buttons to a user in MAX."""
        if not self.is_configured():
            logger.info(f"[MAX SIMULATOR] To user {recipient_user_id} (chat {chat_id}): {text}")
            return True

        bot_id = self.get_bot_user_id()
        safe_user_id = str(recipient_user_id).strip() if (recipient_user_id and str(recipient_user_id).strip() != bot_id) else None
        clean_chat_id = str(chat_id).strip() if (chat_id and str(chat_id).strip() not in ("0", "")) else None

        target_param = f"chat_id={clean_chat_id}" if clean_chat_id else (f"user_id={safe_user_id}" if safe_user_id else None)
        if not target_param:
            logger.warning(f"MAX send_message skipped: no valid chat_id or safe user_id (recipient={recipient_user_id}, bot_id={bot_id})")
            return False

        url = f"{self.base_url}/messages?{target_param}"
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json; charset=utf-8",
        }
        payload: Dict[str, Any] = {
            "text": text,
            "format": "markdown",
        }
        if inline_keyboard:
            buttons_rows = []
            for item in inline_keyboard:
                if isinstance(item, list):
                    row = []
                    for btn in item:
                        b_type = btn.get("type", "callback")
                        b_dict = {
                            "text": btn.get("text", ""),
                            "type": b_type,
                        }
                        if b_type == "link":
                            b_dict["url"] = btn.get("url", "")
                        else:
                            b_dict["payload"] = btn.get("callback_data", btn.get("payload", ""))
                        row.append(b_dict)
                    buttons_rows.append(row)
                else:
                    b_type = item.get("type", "callback")
                    b_dict = {
                        "text": item.get("text", ""),
                        "type": b_type,
                    }
                    if b_type == "link":
                        b_dict["url"] = item.get("url", "")
                    else:
                        b_dict["payload"] = item.get("callback_data", item.get("payload", ""))
                    buttons_rows.append([b_dict])
            payload["attachments"] = [
                {
                    "type": "inline_keyboard",
                    "payload": {
                        "buttons": buttons_rows
                    }
                }
            ]

        try:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            resp = self._client.post(url, headers=headers, content=content)
            if resp.status_code in [200, 201]:
                return True
            alt_param = None
            if target_param.startswith("chat_id") and safe_user_id:
                alt_param = f"user_id={safe_user_id}"
            elif target_param.startswith("user_id") and clean_chat_id:
                alt_param = f"chat_id={clean_chat_id}"

            if alt_param:
                url_alt = f"{self.base_url}/messages?{alt_param}"
                resp_alt = self._client.post(url_alt, headers=headers, content=content)
                if resp_alt.status_code in [200, 201]:
                    return True
            logger.warning(f"MAX Bot API error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Failed to send MAX message to user={recipient_user_id}/chat={chat_id}: {e}")
        return False

    def send_contact_request(self, recipient_user_id: str, text: str, chat_id: Optional[str] = None) -> bool:
        """Sends a message requesting the user to share their verified phone contact in MAX."""
        if not self.is_configured():
            logger.info(f"[MAX SIMULATOR] Contact request to {recipient_user_id} (chat {chat_id}): {text}")
            return True

        bot_id = self.get_bot_user_id()
        safe_user_id = str(recipient_user_id).strip() if (recipient_user_id and str(recipient_user_id).strip() != bot_id) else None
        clean_chat_id = str(chat_id).strip() if (chat_id and str(chat_id).strip() not in ("0", "")) else None

        target_param = f"chat_id={clean_chat_id}" if clean_chat_id else (f"user_id={safe_user_id}" if safe_user_id else None)
        if not target_param:
            logger.warning(f"MAX send_contact_request skipped: no valid chat_id or safe user_id (recipient={recipient_user_id}, bot_id={bot_id})")
            return False

        url = f"{self.base_url}/messages?{target_param}"
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "text": text,
            "format": "markdown",
            "attachments": [
                {
                    "type": "inline_keyboard",
                    "payload": {
                        "buttons": [
                            [
                                {
                                    "text": "📱 Подтвердить номер телефона",
                                    "type": "request_contact",
                                }
                            ]
                        ]
                    }
                }
            ]
        }
        try:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            resp = self._client.post(url, headers=headers, content=content)
            if resp.status_code in [200, 201]:
                return True
            alt_param = None
            if target_param.startswith("chat_id") and safe_user_id:
                alt_param = f"user_id={safe_user_id}"
            elif target_param.startswith("user_id") and clean_chat_id:
                alt_param = f"chat_id={clean_chat_id}"

            if alt_param:
                url_alt = f"{self.base_url}/messages?{alt_param}"
                resp_alt = self._client.post(url_alt, headers=headers, content=content)
                if resp_alt.status_code in [200, 201]:
                    return True
            logger.warning(f"MAX Bot API error {resp.status_code}: {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to send contact request to user={recipient_user_id}/chat={chat_id}: {e}")
        return False

    def register_webhook(self, webhook_url: str) -> bool:
        """Registers or updates webhook subscription on platform-api2.max.ru, cleaning up obsolete URLs."""
        if not self.is_configured():
            return False
        url = f"{self.base_url}/subscriptions"
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }
        try:
            try:
                get_resp = self._client.get(url, headers=headers)
                if get_resp.status_code == 200:
                    subs = get_resp.json().get("subscriptions", [])
                    for s in subs:
                        sub_url = s.get("url")
                        if sub_url and sub_url != webhook_url:
                            self._client.delete(f"{url}?url={sub_url}", headers=headers)
            except Exception as clean_err:
                logger.warning(f"Could not clean old subscriptions: {clean_err}")

            resp = self._client.post(url, headers=headers, json={"url": webhook_url})
            return resp.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Failed to register webhook: {e}")
            return False

    def answer_callback(self, callback_id: str, text: Optional[str] = None, notification: Optional[str] = None) -> bool:
        """Answers a callback query in MAX to dismiss button loading state."""
        if not self.is_configured() or not callback_id:
            return True
        url = f"{self.base_url}/answers?callback_id={callback_id}"
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json; charset=utf-8",
        }
        payload: Dict[str, Any] = {}
        if notification:
            payload["notification"] = notification
        if text:
            payload["message"] = {"text": text, "format": "markdown"}
        try:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            resp = self._client.post(url, headers=headers, content=content)
            return resp.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Failed to answer callback {callback_id}: {e}")
            return False


max_bot_client = MaxBotClient()


