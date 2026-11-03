import os
import sys
import requests
from bcs_client import BcsClient


def main():
    c = BcsClient(os.environ.get("BCS_API_KEY_READ", ""))
    try:
        c._auth()
        print("OK: access-токен получен")
    except requests.HTTPError as e:
        print(f"FAIL: авторизация, HTTP {e.response.status_code}. "
              "Проверьте токен, client_id и срок действия (90 дней).")
        sys.exit(1)

    try:
        p = c.portfolio()
        # Печатаем только названия полей, без значений и номеров счёта
        if isinstance(p, dict):
            print("OK: /api/v1/portfolio, поля верхнего уровня:", sorted(p.keys()))
        else:
            print("OK: /api/v1/portfolio, тип ответа:", type(p).__name__)
    except requests.HTTPError as e:
        print(f"FAIL: портфель, HTTP {e.response.status_code}")
        sys.exit(1)


if __name__ == "__main__":
    main()
