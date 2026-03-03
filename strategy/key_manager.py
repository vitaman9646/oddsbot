import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from config import CFG

logger = logging.getLogger("odds_bot.key_manager")


@dataclass
class KeyState:
    key: str
    remaining: int
    used: int
    exhausted_at: Optional[float]  # timestamp когда кончились

    @property
    def is_alive(self) -> bool:
        """Ключ ещё не исчерпан."""
        return self.remaining > 0

    @property
    def is_reset(self) -> bool:
        """
        Odds API сбрасывает лимит 1-го числа каждого месяца.
        Если ключ исчерпан в прошлом месяце — он снова живой.
        """
        if self.exhausted_at is None:
            return False
        from datetime import datetime
        exhausted = datetime.fromtimestamp(self.exhausted_at)
        now = datetime.now()
        return (now.year, now.month) != (exhausted.year, exhausted.month)


class KeyManager:
    """
    Управляет пулом API ключей The Odds API.
    - Ротация при исчерпании
    - Сохранение состояния между перезапусками
    - Учёт x-requests-remaining из заголовков ответа
    """

    def __init__(self):
        self.keys: list[KeyState] = []
        self._current_idx: int = 0
        self._load_state()

    def _load_state(self):
        """Загружаем сохранённое состояние или инициализируем."""
        state_file = CFG.KEYS_STATE_FILE

        if os.path.exists(state_file):
            try:
                with open(state_file, "r") as f:
                    saved = json.load(f)

                saved_map = {s["key"]: s for s in saved.get("keys", [])}

                for key in CFG.ODDS_API_KEYS:
                    if key in saved_map:
                        s = saved_map[key]
                        ks = KeyState(
                            key=key,
                            remaining=s["remaining"],
                            used=s["used"],
                            exhausted_at=s.get("exhausted_at"),
                        )
                        # Проверяем сброс месяца
                        if ks.is_reset:
                            logger.info(f"Key ...{key[-6:]}: monthly reset")
                            ks.remaining = 500
                            ks.used = 0
                            ks.exhausted_at = None
                        self.keys.append(ks)
                    else:
                        self.keys.append(KeyState(
                            key=key, remaining=500, used=0, exhausted_at=None,
                        ))

                self._current_idx = saved.get("current_idx", 0)
                if self._current_idx >= len(self.keys):
                    self._current_idx = 0

                logger.info(f"Loaded {len(self.keys)} API keys from state")
                self._log_status()
                return

            except Exception as e:
                logger.warning(f"Failed to load keys state: {e}")

        # Инициализация с нуля
        for key in CFG.ODDS_API_KEYS:
            self.keys.append(KeyState(
                key=key, remaining=500, used=0, exhausted_at=None,
            ))
        logger.info(f"Initialized {len(self.keys)} API keys")
        self._save_state()

    def _save_state(self):
        """Сохраняем состояние в файл."""
        os.makedirs("data", exist_ok=True)
        state = {
            "current_idx": self._current_idx,
            "keys": [
                {
                    "key": ks.key,
                    "remaining": ks.remaining,
                    "used": ks.used,
                    "exhausted_at": ks.exhausted_at,
                }
                for ks in self.keys
            ],
        }
        try:
            with open(CFG.KEYS_STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save keys state: {e}")

    def _log_status(self):
        """Логируем статус всех ключей."""
        total = sum(k.remaining for k in self.keys)
        for i, ks in enumerate(self.keys):
            marker = " ◄ active" if i == self._current_idx else ""
            status = "alive" if ks.is_alive else "EXHAUSTED"
            logger.info(
                f"  Key #{i+1} ...{ks.key[-6:]}: "
                f"{ks.remaining} remaining, {ks.used} used [{status}]{marker}"
            )
        logger.info(f"  Total remaining: {total}")

    def get_current_key(self) -> Optional[str]:
        """Возвращает текущий активный ключ или None если все исчерпаны."""
        if not self.keys:
            logger.error("No API keys configured!")
            return None

        # Пробуем найти живой ключ начиная с текущего
        for _ in range(len(self.keys)):
            ks = self.keys[self._current_idx]
            if ks.is_alive:
                return ks.key

            # Этот ключ мёртв — пробуем следующий
            logger.warning(
                f"Key ...{ks.key[-6:]} exhausted, switching..."
            )
            self._current_idx = (self._current_idx + 1) % len(self.keys)

        logger.error("ALL API keys exhausted!")
        return None

    def update_from_response(self, key: str, headers: dict):
        """
        Обновляем remaining из заголовков ответа API.
        The Odds API возвращает:
          x-requests-remaining: 487
          x-requests-used: 13
        """
        for ks in self.keys:
            if ks.key != key:
                continue

            remaining_str = headers.get("x-requests-remaining")
            used_str = headers.get("x-requests-used")

            if remaining_str is not None:
                try:
                    ks.remaining = int(remaining_str)
                except ValueError:
                    pass

            if used_str is not None:
                try:
                    ks.used = int(used_str)
                except ValueError:
                    pass

            if ks.remaining <= 0:
                ks.exhausted_at = time.time()
                logger.warning(
                    f"Key ...{key[-6:]} is now exhausted! "
                    f"Used: {ks.used}"
                )

            self._save_state()
            break

    def report_error(self, key: str, status_code: int):
        """Обрабатываем ошибку API (401 = bad key, 429 = rate limited)."""
        for ks in self.keys:
            if ks.key != key:
                continue

            if status_code == 401:
                logger.error(f"Key ...{key[-6:]}: INVALID (401)")
                ks.remaining = 0
                ks.exhausted_at = time.time()

            elif status_code == 429:
                logger.warning(f"Key ...{key[-6:]}: rate limited (429)")
                ks.remaining = 0
                ks.exhausted_at = time.time()

            self._save_state()
            break

    def get_total_remaining(self) -> int:
        return sum(k.remaining for k in self.keys)

    def get_status_text(self) -> str:
        """Для Telegram уведомлений."""
        lines = []
        for i, ks in enumerate(self.keys):
            marker = "→" if i == self._current_idx else " "
            status = "✅" if ks.is_alive else "❌"
            lines.append(
                f"{marker} Key #{i+1}: {ks.remaining} left {status}"
            )
        total = self.get_total_remaining()
        lines.append(f"\nTotal: {total} requests")
        return "\n".join(lines)
