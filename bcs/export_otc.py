"""
Выгрузка внебиржевого (OTC) рынка БКС в data/bcs_otc.json для страницы otc.html.

MOEX закрыла публичный ISS для внебиржевых досок, поэтому источник — Trade API БКС:
  1. GET /instruments/by-type (пагинация size=100) для типов STOCK, FOREIGN_STOCK, ETF;
  2. фильтр внебиржевых бордов: MTQR (Мосбиржа, НРД), QMEBLCK (вне биржи в БКС),
     SPBOTC (СПБ), BQMEA (котировальный двигатель БКС, тикеры "O.*");
  3. дедупликация по ISIN (у одной компании бывает несколько внебиржевых бордов:
     AA@QMEBLCK и AA-RM@MTQR — оставляем один);
  4. POST /quotes батчами — текущие котировки (ответ: {"records": [...]});
  5. позиции портфеля с внебиржевых бордов добавляем в список принудительно,
     чтобы свои бумаги были на карте всегда.

Объёма/оборота в /quotes нет — поэтому сортировка по обороту на странице
заменена капитализацией (mktcap из справочника). Нули в котировках (0.0)
означают отсутствие значения — нормализуем в None.
"""

import json
import pathlib
from datetime import datetime, timezone

from bcs_client import BASE_INFO
from check_token import make_client
from crypto_box import write_json_or_encrypted

OUT = pathlib.Path(__file__).parent.parent / "data" / "bcs_otc.json"

TYPES = [  # (тип by-type, сколько максимум берём)
    ("STOCK", 200),          # российские акции (MTQR)
    ("FOREIGN_STOCK", 300),  # иностранные акции (MTQR / QMEBLCK / BQMEA)
    ("ETF", 100),            # иностранные ETF (SPBOTC)
]
OTC_BOARDS = {"MTQR", "QMEBLCK", "SPBOTC", "BQMEA", "BQNOTE"}
# приоритет борда при дедупликации по ISIN (меньше — лучше)
BOARD_RANK = {"MTQR": 0, "BQMEA": 1, "QMEBLCK": 2, "SPBOTC": 3, "BQNOTE": 4}
EXCHANGE_BOARDS = {"TQBR", "TQRD", "TQPI", "TQIR", "TQOB"}  # биржевые — не OTC
QUOTE_BATCH = 100
PAGE_SIZE = 100
MAX_PAGES = 60


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # NaN -> None


def _nz(x):
    """0.0 у БКС означает «нет значения»."""
    v = _f(x)
    return v if v else None


def _boards(inst: dict) -> list:
    b = inst.get("boards")
    return b if isinstance(b, list) else []


def otc_class_code(inst: dict) -> str | None:
    """classCode внебиржевого борда инструмента (для запроса котировок)."""
    for b in _boards(inst):
        cc = str((b or {}).get("classCode") or "").upper()
        if cc in OTC_BOARDS or "OTC" in cc:
            return cc
    pb = str(inst.get("primaryBoard") or "").upper()
    if pb in OTC_BOARDS or "OTC" in pb:
        return pb
    t = str(inst.get("ticker") or "")
    return "BQMEA" if t.startswith("O.") else None


def is_otc(inst: dict) -> bool:
    return otc_class_code(inst) is not None


def norm_instrument(inst: dict) -> dict | None:
    ticker = inst.get("ticker")
    board = otc_class_code(inst)
    if not ticker or not board:
        return None
    return {
        "ticker": ticker,
        "name": inst.get("displayName") or inst.get("shortName") or inst.get("name") or ticker,
        "isin": inst.get("isin"),
        "type": inst.get("instrumentType"),     # STOCK / FOREIGN_STOCK / ETF / ...
        "currency": inst.get("tradingCurrency") or inst.get("currency"),
        "board": board,
        "lot": _f(inst.get("lotSize")),
        "mktcap": _f(inst.get("mktcap")),
        "qualifiedOnly": bool(inst.get("isQualifiedOnly")),
    }


def paged_by_type(c, itype: str) -> list:
    out = []
    for page in range(MAX_PAGES):
        resp = c.get("/instruments/by-type", base=BASE_INFO,
                     params={"type": itype, "page": page, "size": PAGE_SIZE})
        rows = resp.get("instruments") if isinstance(resp, dict) else resp
        rows = rows or []
        out.extend(rows)
        if len(rows) < PAGE_SIZE:
            break
    return out


def dedupe_by_isin(items: list) -> list:
    """Одна компания — одна карточка: выбираем борд по BOARD_RANK, без ISIN — по тикеру."""
    best = {}
    for it in items:
        key = it["isin"] or it["ticker"]
        cur = best.get(key)
        if cur is None or BOARD_RANK.get(it["board"], 9) < BOARD_RANK.get(cur["board"], 9):
            best[key] = it
    return list(best.values())


def fetch_quotes(c, instruments: list) -> dict:
    """Котировки батчами. Ответ /quotes: {"records": [...]}. Нули -> None."""
    quotes = {}
    for i in range(0, len(instruments), QUOTE_BATCH):
        chunk = instruments[i:i + QUOTE_BATCH]
        payload = [{"ticker": it["ticker"], "classCode": it["board"]} for it in chunk]
        try:
            resp = c.quotes(payload)
        except Exception as e:
            print(f"ПРЕДУПРЕЖДЕНИЕ: /quotes батч {i // QUOTE_BATCH + 1} упал: {e}")
            continue
        rows = resp.get("records") if isinstance(resp, dict) else resp
        rows = rows or []
        if i == 0 and rows:
            print("DEBUG: поля котировки:", sorted(rows[0].keys()))
        for q in rows:
            if isinstance(q, dict) and q.get("ticker"):
                quotes[q["ticker"]] = q
    return quotes


def portfolio_otc(c) -> list:
    """Позиции портфеля с внебиржевых бордов — принудительно добавляем в выгрузку."""
    out = []
    try:
        pf = c.portfolio()
        rows = pf.get("positions") if isinstance(pf, dict) else pf
        seen = set()
        for p in rows or []:
            if not isinstance(p, dict) or p.get("type") != "depoLimit":
                continue
            board = str(p.get("board") or "").upper()
            ticker = p.get("ticker")
            if not ticker or board in EXCHANGE_BOARDS or ticker in seen:
                continue
            seen.add(ticker)
            out.append({"ticker": ticker, "board": board or "BQMEA",
                        "displayName": p.get("displayName")})
    except Exception as e:
        print("ПРЕДУПРЕЖДЕНИЕ: /portfolio недоступен:", e)
    return out


def norm_quote(q: dict) -> dict:
    last, close = _nz(q.get("last")), _nz(q.get("close"))
    open_ = _nz(q.get("open"))
    price = last if last is not None else close
    change_pct = _nz(q.get("changeRate"))
    if change_pct is None and last is not None and close:
        change_pct = round((last - close) / close * 100, 2)
    bid, ask = _nz(q.get("bid")), _nz(q.get("offer"))
    return {
        "price": price,
        "last": last,
        "prevClose": close,
        "open": open_,
        "high": _nz(q.get("high")),
        "low": _nz(q.get("low")),
        "bid": bid,
        "ask": ask,
        "spreadPct": round((ask - bid) / ask * 100, 2) if bid and ask and ask > 0 else None,
        "changePct": change_pct,
        "quoteTime": q.get("dateTime"),
        "quoteCurrency": q.get("currency"),
        "tradingStatus": q.get("securityTradingStatus"),  # 17 — торги идут, 18 — закрыты
    }


def main():
    c = make_client()

    mine = portfolio_otc(c)
    mine_tickers = {p["ticker"] for p in mine}

    items = []
    for itype, cap in TYPES:
        try:
            rows = paged_by_type(c, itype)
        except Exception as e:
            print(f"ПРЕДУПРЕЖДЕНИЕ: /instruments/by-type?type={itype} упал: {e}")
            continue
        otc = [x for x in (norm_instrument(x) for x in rows if isinstance(x, dict)) if x]
        otc = dedupe_by_isin(otc)
        otc.sort(key=lambda x: (x["mktcap"] is None, -(x["mktcap"] or 0)))
        cut = otc[:cap]
        print(f"{itype}: всего {len(rows)}, внебиржевых {len(otc)}, берём {len(cut)}")
        items.extend(cut)

    # свои позиции — в список даже если их нет в справочнике by-type
    known = {it["ticker"] for it in items}
    for p in mine:
        if p["ticker"] not in known:
            try:
                meta = c.post("/instruments/by-tickers", base=BASE_INFO, json={"tickers": [p["ticker"]]})
                rec = (meta[0] if isinstance(meta, list) and meta else None) or {}
            except Exception:
                rec = None
            it = norm_instrument(rec) if rec else None
            if not it:
                it = {"ticker": p["ticker"], "name": p.get("displayName") or p["ticker"],
                      "isin": None, "type": None, "currency": None, "board": p["board"],
                      "lot": None, "mktcap": None, "qualifiedOnly": False}
            items.append(it)
            known.add(p["ticker"])

    quotes = fetch_quotes(c, items)
    print(f"Котировки получены по {len(quotes)} из {len(items)} инструментов")

    out = []
    for it in items:
        q = quotes.get(it["ticker"]) or {}
        nq = norm_quote(q) if q else {"price": None, "last": None, "prevClose": None,
                                      "open": None, "high": None, "low": None, "bid": None,
                                      "ask": None, "spreadPct": None, "changePct": None,
                                      "quoteTime": None, "quoteCurrency": None, "tradingStatus": None}
        out.append({**it, **nq, "inPortfolio": it["ticker"] in mine_tickers})

    mode = write_json_or_encrypted({
        "source": "BCS trade-api (внебиржевой рынок)",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": out,
    }, OUT)
    print(f"OK: {len(out)} бумаг -> {OUT} [{mode}]")


if __name__ == "__main__":
    main()
