import requests
import logging
from src.core.config import settings

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self):
        self.token = settings.telegram.token
        self.chat_id = settings.telegram.chat_id
        self.enabled = bool(self.token and self.chat_id)

    def send(self, message: str, status: str = "info"):
        """
        Отправляет сообщение в Telegram.
        status: 'info', 'success', 'error' (влияет на эмодзи)
        """
        if not self.enabled:
            return

        icons = {
            "info": "ℹ️",
            "success": "✅",
            "error": "🚨",
            "warning": "⚠️"
        }
        icon = icons.get(status, "")
        
        # Формируем текст
        full_text = f"{icon} *PIKURR System*\n\n{message}"
        
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = {
            "chat_id": self.chat_id,
            "text": full_text,
            "parse_mode": "Markdown"
        }

        try:
            response = requests.post(url, data=data, timeout=5)
            if response.status_code != 200:
                logger.warning(f"Telegram send failed: {response.text}")
        except Exception as e:
            logger.warning(f"Telegram connection error: {e}")