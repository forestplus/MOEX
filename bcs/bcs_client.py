import time
import requests

BASE = "https://trade-api.bcs.ru"
TOKEN_URL = f"{BASE}/trade-api-keycloak/realms/tradeapi/protocol/openid-connect/token"
CLIENT_ID = "trade-api-read-only"  # ПРОВЕРИТЬ: client_id для токенов «только для чтения»


class BcsClient:
    def __init__(self, refresh_token: str, timeout: int = 15):
        if not refresh_token:
            raise ValueError("refresh-токен пустой: проверьте секрет BCS_API_KEY_READ")
        self._refresh = refresh_token
        self._access = None
        self._expires_at = 0.0
        self._timeout = timeout
        self._s = requests.Session()

    def _auth(self):
        if self._access and time.time() < self._expires_at - 60:
            return
        r = self._s.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": self._refresh,
        }, timeout=self._timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Авторизация BCS: HTTP {r.status_code}, ответ: {r.text[:300]}")
        j = r.json()
        self._access = j["access_token"]
        self._expires_at = time.time() + int(j.get("expires_in", 86400))
        if j.get("refresh_token"):  # на случай ротации refresh-токена
            self._refresh = j["refresh_token"]

    def _request(self, method, path, **kw):
        self._auth()
        headers = {"Authorization": f"Bearer {self._access}"}
        r = self._s.request(method, BASE + path, headers=headers,
                            timeout=self._timeout, **kw)
        if r.status_code == 429:  # лимит запросов: пауза и повтор
            time.sleep(2)
            r = self._s.request(method, BASE + path, headers=headers,
                                timeout=self._timeout, **kw)
        r.raise_for_status()
        return r.json()

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def post(self, path, json=None):
        return self._request("POST", path, json=json)

    def portfolio(self):
        return self.get("/api/v1/portfolio")

    def candles(self, params: dict):
        # ПРОВЕРИТЬ имена параметров по /http/market-data/get-candles-chart
        return self.get("/api/v1/candles-chart", params=params)

    def quotes(self, payload: dict):
        # ПРОВЕРИТЬ структуру тела по /http/market-data/get-quotes
        return self.post("/api/v1/quotes", json=payload)
