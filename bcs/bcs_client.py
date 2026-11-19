"""
Клиент для БКС Trade API (https://trade-api.bcs.ru).

Важно:
- API живёт на be.broker.ru, а trade-api.bcs.ru — это сайт с документацией.
- client_id: "trade-api-read" для токена «только для чтения», "trade-api-write" — для торговли.
- Access-токен живёт 24 часа, refresh-токен — 90 суток и РОТИРУЕТСЯ при каждом обмене:
  в ответе приходит новый refresh_token, его нужно сохранить (см. on_refresh).
"""

import os
import time
import requests

AUTH_URL = "https://be.broker.ru/trade-api-keycloak/realms/tradeapi/protocol/openid-connect/token"

BASE_PORTFOLIO = "https://be.broker.ru/trade-api-bff-portfolio/api/v1"
BASE_LIMITS = "https://be.broker.ru/trade-api-bff-limit/api/v1"
BASE_OPERATIONS = "https://be.broker.ru/trade-api-bff-operations/api/v1"
BASE_INFO = "https://be.broker.ru/trade-api-information-service/api/v1"
BASE_MARKET_DATA = "https://be.broker.ru/trade-api-market-data-connector/api/v1"
BASE_MARGINAL = "https://be.broker.ru/trade-api-bff-marginal-indicators/api/v1"


class BcsClient:
    def __init__(self, refresh_token: str, client_id: str | None = None, timeout: int = 15,
                 on_refresh=None):
        """
        on_refresh: необязательный колбэк fn(new_refresh_token, refresh_expires_in_sec) —
        вызывается, когда API ротирует refresh-токен. Подпишитесь и сохраните токен
        (например, обновите секрет в GitHub), иначе через 90 суток или после ротации
        доступ пропадёт.
        """
        if not refresh_token:
            raise ValueError("refresh-токен пустой: проверьте секрет BCS_API_KEY_READ")
        self._refresh = refresh_token
        self._client_id = client_id or os.environ.get("BCS_CLIENT_ID", "trade-api-read")
        self._access = None
        self._expires_at = 0.0
        self.refresh_expires_in = None  # секунд до конца жизни refresh-токена
        self._timeout = timeout
        self._on_refresh = on_refresh
        self._s = requests.Session()

    def _auth(self):
        if self._access and time.time() < self._expires_at - 60:
            return
        r = self._s.post(AUTH_URL, data={
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "refresh_token": self._refresh,
        }, timeout=self._timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Авторизация BCS: HTTP {r.status_code}, ответ: {r.text[:300]}")
        j = r.json()
        self._access = j["access_token"]
        self._expires_at = time.time() + int(j.get("expires_in", 86400))
        self.refresh_expires_in = int(j.get("refresh_expires_in", 0)) or None
        new_refresh = j.get("refresh_token")
        if new_refresh and new_refresh != self._refresh:
            self._refresh = new_refresh
            if self._on_refresh:
                self._on_refresh(new_refresh, self.refresh_expires_in)

    def _request(self, method, base, path, _retried=False, **kw):
        self._auth()
        headers = {"Authorization": f"Bearer {self._access}"}
        r = self._s.request(method, base + path, headers=headers,
                            timeout=self._timeout, **kw)
        if r.status_code == 401 and not _retried:  # токен протух раньше срока — перевыпускаем
            self._access = None
            self._auth()
            return self._request(method, base, path, _retried=True, **kw)
        if r.status_code == 429:  # лимит запросов: пауза и повтор
            time.sleep(2)
            r = self._s.request(method, base + path, headers=headers,
                                timeout=self._timeout, **kw)
        r.raise_for_status()
        return r.json()

    def get(self, path, base=BASE_PORTFOLIO, params=None):
        return self._request("GET", base, path, params=params)

    def post(self, path, base=BASE_OPERATIONS, json=None):
        return self._request("POST", base, path, json=json)

    # ---------- портфель и счёт ----------

    def portfolio(self):
        """Позиции портфеля: тикер, количество, балансовая/текущая цена, P/L, доля."""
        return self.get("/portfolio", base=BASE_PORTFOLIO)

    def limits(self):
        """Лимиты: бумаги (depoLimit), деньги (moneyLimit), срочный рынок (futuresLimit)."""
        return self.get("/limits", base=BASE_LIMITS)

    def marginal_indicators(self):
        """Оценка портфеля, дневное/полное изменение, устойчивость, свободные деньги."""
        return self.get("/marginal-indicators", base=BASE_MARGINAL)

    # ---------- рыночные данные ----------

    def candles(self, ticker: str, class_code: str, start, end, time_frame: str = "D1"):
        """Исторические свечи. timeFrame: M1/M5/M15/H1/D1/W1/MN1. Максимум ~1000–1440 баров."""
        return self.get("/candles-chart", base=BASE_MARKET_DATA, params={
            "ticker": ticker, "classCode": class_code,
            "startDate": start, "endDate": end, "timeFrame": time_frame,
        })

    def quotes(self, instruments: list[dict]):
        """Текущие котировки. instruments: [{"ticker": "SBER", "classCode": "TQBR"}, ...]."""
        return self.post("/quotes", base=BASE_MARKET_DATA, json={"instruments": instruments})

    # ---------- справочники ----------

    def instrument_by_ticker(self, ticker: str, class_code: str = "TQBR"):
        return self.get("/instruments/by-tickers", base=BASE_INFO,
                        params={"ticker": ticker, "classCode": class_code})

    def trading_status(self, class_code: str = "TQBR"):
        return self.get("/trading-schedule/status", base=BASE_INFO,
                        params={"classCode": class_code})
