"""
Выгрузка внебиржевого (OTC) рынка БКС в data/bcs_otc.json для страницы otc.html.

MOEX закрыла свои внебиржевые доски (MTQR/MPTR), поэтому источник — Trade API БКС:
  1. GET /instruments/by-type?type=FOREIGN и =STOCK — справочник инструментов;
  2. фильтр внебиржевых: тикер вида "O.<isin без кода страны>" или борд с "OTC" в classCode;
  3. POST /quotes (батчами) — текущие котировки;
  4. GET /portfolio — чтобы пометить бумаги, которые уже есть у пользователя.

Верхние MAX_* ограничивают размер файла: берём самые крупные по капитализации.
Ошибка здесь не должна валить весь workflow (в bcs.yml шаг помечен continue-on-error).
"""

import json
import os
import pathlib
from datetime import datetime, timezone

from bcs_client import BASE_INFO
from check_token import make_client
from crypto_box import write_json_or_encrypted

OUT = pathlib.Path(__file__).parent.parent / "data" / "bcs_otc.json"

MAX_FOREIGN = 300   # иностранных бумаг максимум
MAX_RU = 200        # российских бумаг максимум
QUOTE_BATCH = 100   # инструментов в одном POST /quotes


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # NaN -> None


def _boards(inst: dict) -> list:
    b = inst.get("boards")
    return b if isinstance(b, list) else []


def otc_class_code(inst: dict) -> str | None:
    """classCode внебиржевого борда инструмента (для запроса котировок)."""
    for b in _boards(inst):
        cc = str((b or {}).get("classCode") or "")
        if "OTC" in cc.upper():
            return cc
    pb = str(inst.get("primaryBoard") or "")
    if "OTC" in pb.upper():
        return pb
    t = str(inst.get("ticker") or "")
    return "OTC" if t.startswith("O.") else None


def is_otc(inst: dict) -> bool:
    t = str(inst.get("ticker") or "")
    if t.startswith("O."):
        return True
    return otc_class_code(inst) is not None


def norm_instrument(inst: dict, kind: str) -> dict | None:
    ticker = inst.get("ticker")
    if not ticker:
        return None
    return {
        "ticker": ticker,
        "name": inst.get("displayName") or inst.get("shortName") or inst.get("name") or ticker,
        "isin": inst.get("isin"),
        "type": kind,                      # FOREIGN / STOCK
        "instrumentType": inst.get("instrumentType"),
        "currency": inst.get("tradingCurrency") or inst.get("currency"),
        "board": otc_class_code(inst),
        "lot": _f(inst.get("lotSize")),
        "mktcap": _f(inst.get("mktcap")),
        "qualifiedOnly": bool(inst.get("isQualifiedOnly")),
        "faceValue": _f(inst.get("faceValue")),
    }


_QUOTE_KEYS = {
    "last": ("last", "lastPrice", "price"),
    "bid": ("bid", "bidPrice"),
    "ask": ("offer", "ask", "askPrice"),
    "open": ("open", "openPrice"),
    "high": ("high", "highPrice"),
    "low": ("low", "lowPrice"),
    "close": ("close", "prevClose", "closePrice", "previousClose"),
    "volume": ("volume", "vol", "volToday"),
    "turnover": ("turnover", "value", "valToday"),
    "time": ("dateTime", "time", "updated", "timestamp"),
    "currency": ("currency", "currencyId"),
}


def norm_quote(q: dict) -> dict:
    """Терпимая нормализация: точную схему /quotes БКС не документирует стабильно,
    поэтому поля вытаскиваем по списку возможных имён."""
    out = {}
    for dst, keys in _QUOTE_KEYS.items():
        v = None
        for k in keys:
            if k in q and q[k] is not None:
                v = q[k]
                break
        out[dst] = v if dst in ("time", "currency") else _f(v)
    return out


def fetch_quotes(c, instruments: list[dict]) -> dict:
    """Котировки батчами. Возвращает {ticker: norm_quote}."""
    quotes = {}
    for i in range(0, len(instruments), QUOTE_BATCH):
        chunk = instruments[i:i + QUOTE_BATCH]
        payload = [{"ticker": it["ticker"], "classCode": it["board"] or "OTC"} for it in chunk]
        try:
            resp = c.quotes(payload)
        except Exception as e:
            print(f"ПРЕДУПРЕЖДЕНИЕ: /quotes батч {i // QUOTE_BATCH + 1} упал: {e}")
            continue
        rows = resp if isinstance(resp, list) else (resp.get("quotes") or resp.get("data") or [])
        if i == 0 and rows and isinstance(rows[0], dict):
            print("DEBUG: поля котировки:", sorted(rows[0].keys()))
            print("DEBUG: пример:", json.dumps(rows[0], ensure_ascii=False, default=str)[:400])
        for q in rows:
            if isinstance(q, dict) and q.get("ticker"):
                quotes[q["ticker"]] = norm_quote(q)
    return quotes


def portfolio_tickers(c) -> set:
    try:
        pf = c.portfolio()
        rows = pf.get("positions") if isinstance(pf, dict) else pf
        return {p.get("ticker") for p in rows or []
                if isinstance(p, dict) and p.get("ticker") and p.get("type") != "moneyLimit"}
    except Exception as e:
        print("ПРЕДУПРЕЖДЕНИЕ: /portfolio недоступен, меток «в портфеле» не будет:", e)
        return set()


def main():
    c = make_client()
    mine = portfolio_tickers(c)

    items = []
    for kind, cap in (("FOREIGN", MAX_FOREIGN), ("STOCK", MAX_RU)):
        try:
            resp = c.get("/instruments/by-type", base=BASE_INFO, params={"type": kind})
        except Exception as e:
            print(f"ПРЕДУПРЕЖДЕНИЕ: /instruments/by-type?type={kind} упал: {e}")
            continue
        rows = resp.get("instruments") if isinstance(resp, dict) else resp
        otc = [norm_instrument(x, kind) for x in rows or [] if isinstance(x, dict) and is_otc(x)]
        otc = [x for x in otc if x]
        otc.sort(key=lambda x: (x["mktcap"] is None, -(x["mktcap"] or 0)))
        cut = otc[:cap]
        print(f"{kind}: всего {len(rows or [])}, внебиржевых {len(otc)}, берём {len(cut)}")
        items.extend(cut)

    quotes = fetch_quotes(c, items)
    print(f"Котировки получены по {len(quotes)} из {len(items)} инструментов")

    out = []
    for it in items:
        q = quotes.get(it["ticker"]) or {}
        last, close, open_ = q.get("last"), q.get("close"), q.get("open")
        price = last if last is not None else close
        change_pct = None
        ref = close if close else open_
        if last is not None and ref:
            change_pct = round((last - ref) / ref * 100, 2)
        bid, ask = q.get("bid"), q.get("ask")
        spread = round((ask - bid) / ask * 100, 2) if bid and ask and ask > 0 else None
        out.append({
            **it,
            "price": price,
            "last": last,
            "prevClose": close,
            "open": open_,
            "high": q.get("high"),
            "low": q.get("low"),
            "bid": bid,
            "ask": ask,
            "spreadPct": spread,
            "volume": q.get("volume"),
            "turnover": q.get("turnover"),
            "changePct": change_pct,
            "quoteTime": q.get("time"),
            "quoteCurrency": q.get("currency"),
            "inPortfolio": it["ticker"] in mine,
        })

    mode = write_json_or_encrypted({
        "source": "BCS trade-api (внебиржевой рынок)",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": out,
    }, OUT)
    print(f"OK: {len(out)} бумаг -> {OUT} [{mode}]")


if __name__ == "__main__":
    main()
