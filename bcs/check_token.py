"""
Проверка токена БКС: получает access-токен и дёргает /portfolio.
Печатает срок жизни refresh-токена и предупреждает, если осталось меньше WARN_DAYS дней.
Если токен ротирован — кладёт новый в RUNTIME_DIR/new_refresh_token (для workflow).
"""

import os
import pathlib
import sys

from bcs_client import BcsClient

WARN_DAYS = 10
RUNTIME_DIR = pathlib.Path(__file__).parent / ".runtime"


def save_rotated_token(new_token: str, _expires_in):
    RUNTIME_DIR.mkdir(exist_ok=True)
    (RUNTIME_DIR / "new_refresh_token").write_text(new_token, encoding="utf-8")
    print("ВНИМАНИЕ: BCS ротировал refresh-токен, новый сохранён для обновления секрета")


def make_client() -> BcsClient:
    return BcsClient(os.environ.get("BCS_API_KEY_READ", ""), on_refresh=save_rotated_token)


def check_token(c: BcsClient) -> bool:
    try:
        c._auth()  # noqa: SLF001 — сознательно проверяем сам обмен токена
        print("OK: access-токен получен")
    except RuntimeError as e:
        print("FAIL:", e)
        return False

    if c.refresh_expires_in is not None:
        days = c.refresh_expires_in // 86400
        print(f"Refresh-токен живёт ещё ~{days} дн.")
        if days < WARN_DAYS:
            print(f"ВНИМАНИЕ: меньше {WARN_DAYS} дней! Перевыпустите токен в «БКС Мир инвестиций» "
                  "и обновите секрет BCS_API_KEY_READ")

    try:
        p = c.portfolio()
        if isinstance(p, dict):
            print("OK: /portfolio, поля верхнего уровня:", sorted(p.keys()))
        else:
            print("OK: /portfolio, тип ответа:", type(p).__name__)
        return True
    except Exception as e:  # портфель может быть недоступен при валидном токене
        print("FAIL: /portfolio:", e)
        return False


if __name__ == "__main__":
    sys.exit(0 if check_token(make_client()) else 1)
