import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import CFG

logger = logging.getLogger("odds_bot.key_manager")

# Cooldown при 429 в секундах
RATE_LIMIT_COOLDOWN = 60


@dataclass
class KeyState:
    key: str
    remaining: int
    used: int
    exhausted_at: Optional[float] = None   # timestamp когда исчерпан
    rate_limited_until: Optional[float] = None  # timestamp до которого ждём

    @property
    def is_alive(self) -> bool:
        """Ключ живой: не исчерпан и не в кулдауне."""
        if self.remaining <= 0:
            return False
        if self.rate_limited_until and time.time() < self.rate_limited_until:
            return False
        return True

    @property
    def is_rate_limited(self) -> bool:
        return (
            self.rate_limited_until is not None
            and time.time() < self.rate_limited_until
        )

    @property
    def cooldown_seconds_left(self) -> float:
        if not self.rate_limited_until:
            return 0
        return max(0.0, self.rate_limited_until - time.time())

    @property
    def is_monthly_reset(self) -> bool:
        """
        Odds API сбрасывает лимит 1-го числа каждого месяца.
        Если ключ исчерпан в прошлом месяце — он снова живой.
        """
        if self.exhausted_at is None:
            return False
        exhausted = datetime.fromtimestamp(self.exhausted_at)
        now = datetime.now()
        return (now.year, now.month) != (exhausted.year, exhausted.month)


class KeyManager:
    """
    Управляет пулом API ключей The Odds API.
    - Ротация при исчерпании
    - Cooldown при 429 (не убиваем ключ, просто ждём)
    - Сохранение состояния между перезапусками
    - Учёт x-requests-remaining из заголовков ответа
    """

    def __init__(self):
        self.keys: list[KeyState] = []
        self._current_idx: int = 0
        self._load_state()

    # -------------------------------------------------------------------------
    # Инициализация и персистентность
    # -------------------------------------------------------------------------

    def _load_state(self):
        """Загружаем сохранённое состояние или инициализируем с нуля."""
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
                            rate_limited_until=s.get("rate_limited_until"),
                        )
                        if ks.is_monthly_reset:
                            logger.info(f"Key ...{key[-6:]}: monthly reset applied")
                            ks.remaining = 500
                            ks.used = 0
                            ks.exhausted_at = None
                            ks.rate_limited_until = None
                    else:
                        ks = KeyState(key=key, remaining=500, used=0)

                    self.keys.append(ks)

                self._current_idx = saved.get("current_idx", 0)
                if self._current_idx >= len(self.keys):
                    self._current_idx = 0

                logger.info(f"Loaded {len(self.keys)} API keys from state")
                self._log_status()
                return

            except Exception as e:
                logger.warning(f"Failed to load keys state: {e}, reinitializing")

        # Инициализация с нуля
        self.keys = [
            KeyState(key=key, remaining=500, used=0)
            for key in CFG.ODDS_API_KEYS
        ]
        logger.info(f"Initialized {len(self.keys)} API keys")
        self._save_state()

    def _save_state(self):
        """Сохраняем состояние в файл."""
        os.makedirs("data", exist_ok=True)
        state = {
            "current_idx": self._current_idx,
            "saved_at": time.time(),
            "keys": [
                {
                    "key": ks.key,
                    "remaining": ks.remaining,
                    "used": ks.used,
                    "exhausted_at": ks.exhausted_at,
                    "rate_limited_until": ks.rate_limited_until,
                }
                for ks in self.keys
            ],
        }
        try:
            with open(CFG.KEYS_STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save keys state: {e}")

    # -------------------------------------------------------------------------
    # Получение ключа
    # -------------------------------------------------------------------------

    def get_current_key(self) -> Optional[str]:
        """
        Возвращает текущий активный ключ.
        Если текущий не годится — ищет следующий живой.
        Возвращает None если все исчерпаны (не в кулдауне).
        """
        if not self.keys:
            logger.error("No API keys configured!")
            return None

        start_idx = self._current_idx

        for i in range(len(self.keys)):
            idx = (start_idx + i) % len(self.keys)
            ks = self.keys[idx]

            if ks.is_rate_limited:
                logger.debug(
                    f"Key ...{ks.key[-6:]}: rate limited, "
                    f"{ks.cooldown_seconds_left:.0f}s left"
                )
                continue

            if ks.is_alive:
                if idx != self._current_idx:
                    logger.info(f"Switched to key ...{ks.key[-6:]}")
                    self._current_idx = idx
                return ks.key

            # Ключ мёртв (remaining=0, не rate_limited)
            logger.debug(f"Key ...{ks.key[-6:]}: exhausted, skipping")

        # Все исчерпаны — может кто-то в кулдауне?
        rate_limited = [k for k in self.keys if k.is_rate_limited]
        if rate_limited:
            # Есть ключи в кулдауне — возвращаем None, вызывающий код подождёт
            min_wait = min(k.cooldown_seconds_left for k in rate_limited)
            logger.warning(
                f"All keys rate-limited. Shortest cooldown: {min_wait:.0f}s"
            )
        else:
            logger.error("ALL API keys exhausted!")

        return None

    async def get_key_with_wait(self) -> Optional[str]:
        """
        Как get_current_key, но если все ключи в кулдауне — ждёт минимальный cooldown.
        Возвращает None только если все реально исчерпаны.
        """
        key = self.get_current_key()
        if key:
            return key

        # Проверяем: есть ли ключи в кулдауне (не exhausted)
        rate_limited = [k for k in self.keys if k.is_rate_limited]
        if not rate_limited:
            return None  # все exhausted, ждать бессмысленно

        min_wait = min(k.cooldown_seconds_left for k in rate_limited)
        logger.info(f"Waiting {min_wait:.0f}s for rate limit cooldown...")
        await asyncio.sleep(min_wait + 1)  # +1 секунда буфер

        return self.get_current_key()

    # -------------------------------------------------------------------------
    # Обновление состояния
    # -------------------------------------------------------------------------

    def update_from_response(self, key: str, headers: dict):
        """
        Обновляем remaining из заголовков ответа API.
        The Odds API: x-requests-remaining, x-requests-used
        """
        ks = self._find_key(key)
        if not ks:
            return

        remaining_str = headers.get("x-requests-remaining")
        used_str = headers.get("x-requests-used")

        if remaining_str is not None:
            try:
                ks.remaining = int(remaining_str)
            except ValueError:
                logger.warning(f"Bad x-requests-remaining value: {remaining_str!r}")

        if used_str is not None:
            try:
                ks.used = int(used_str)
            except ValueError:
                pass

        if ks.remaining <= 0:
            ks.exhausted_at = time.time()
            logger.warning(f"Key ...{key[-6:]} exhausted! Used: {ks.used}")

        self._save_state()

    def report_error(self, key: str, status_code: int):
        """
        Обрабатываем ошибки API:
        - 401: невалидный ключ → помечаем exhausted навсегда
        - 429: rate limit → cooldown, ключ не убиваем
        """
        ks = self._find_key(key)
        if not ks:
            return

        if status_code == 401:
            logger.error(f"Key ...{key[-6:]}: INVALID (401), marking exhausted")
            ks.remaining = 0
            ks.exhausted_at = time.time()

        elif status_code == 429:
            until = time.time() + RATE_LIMIT_COOLDOWN
            ks.rate_limited_until = until
            logger.warning(
                f"Key ...{key[-6:]}: rate limited (429), "
                f"cooldown {RATE_LIMIT_COOLDOWN}s"
            )
            # Переключаемся на следующий ключ сразу
            self._rotate_to_next()

        self._save_state()

    # -------------------------------------------------------------------------
    # Вспомогательные методы
    # -------------------------------------------------------------------------

    def _find_key(self, key: str) -> Optional[KeyState]:
        for ks in self.keys:
            if ks.key == key:
                return ks
        logger.warning(f"Key ...{key[-6:]} not found in pool")
        return None

    def _rotate_to_next(self):
        """Переключаемся на следующий живой ключ."""
        for i in range(1, len(self.keys) + 1):
            idx = (self._current_idx + i) % len(self.keys)
            if self.keys[idx].is_alive:
                self._current_idx = idx
                logger.info(f"Rotated to key ...{self.keys[idx].key[-6:]}")
                return

    def _log_status(self):
        total = self.get_total_remaining()
        for i, ks in enumerate(self.keys):
            marker = " ◄ active" if i == self._current_idx else ""
            if ks.is_rate_limited:
                status = f"COOLDOWN ({ks.cooldown_seconds_left:.0f}s)"
            elif ks.is_alive:
                status = "alive"
            else:
                status = "EXHAUSTED"
            logger.info(
                f"  Key #{i+1} ...{ks.key[-6:]}: "
                f"{ks.remaining} remaining, {ks.used} used [{status}]{marker}"
            )
        logger.info(f"  Total remaining: {total}")

    def get_total_remaining(self) -> int:
        return sum(k.remaining for k in self.keys)

    def get_status_text(self) -> str:
        """Для Telegram уведомлений."""
        lines = []
        for i, ks in enumerate(self.keys):
            marker = "→" if i == self._current_idx else " "
            if ks.is_rate_limited:
                status = f"⏳ {ks.cooldown_seconds_left:.0f}s"
            elif ks.is_alive:
                status = "✅"
            else:
                status = "❌"
            lines.append(f"{marker} Key #{i+1}: {ks.remaining} left {status}")
        lines.append(f"\nTotal: {self.get_total_remaining()} requests")
        return "\n".join(lines)
