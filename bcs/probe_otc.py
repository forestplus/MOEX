"""
Диагностика внебиржевых инструментов БКС (запускается только вручную —
шаг в bcs.yml помечен if: github.event_name == 'workflow_dispatch').

Ничего не пишет в data/, только печатает в лог workflow:
- сколько инструментов отдаёт /instruments/by-type по каждому типу (с пагинацией)
  и сколько среди них внебиржевых (тикер "O.*" или борд с OTC/QMEBLCK/MTQR);
- какие board у позиций портфеля (БЕЗ тикеров — это приватные данные);
- сырой ответ /quotes для одного публично известного OTC-тикера (схема полей).
"""

import json

from bcs_client import BASE_INFO
from check_token import make_client

TYPES = ["STOCK", "FOREIGN", "BONDS", "DEPOSITARY", "EURO", "ETF", "MUTUAL", "NOTES"]
OTC_MARKERS = ("OTC", "QMEBLCK", "MTQR")
PROBE_TICKER = "O.30303M1027"  # Meta Platforms, публичный код инструмента


def is_otc(inst: dict) -> bool:
    t = str(inst.get("ticker") or "")
    if t.startswith("O."):
        return True
    boards = inst.get("boards") or []
    if any(any(m in str((b or {}).get(k) or "").upper() for m in OTC_MARKERS)
           for b in boards for k in ("classCode", "exchange")):
        return True
    return any(m in str(inst.get("primaryBoard") or "").upper() for m in OTC_MARKERS)


def paged_by_type(c, itype: str) -> list:
    out = []
    page = 0
    while page < 40:
        resp = c.get("/instruments/by-type", base=BASE_INFO,
                     params={"type": itype, "page": page, "size": 500})
        rows = resp.get("instruments") if isinstance(resp, dict) else resp
        rows = rows or []
        out.extend(rows)
        if len(rows) < 500:
            break
        page += 1
    return out


def main():
    c = make_client()

    # 1) board'ы позиций портфеля — только пары (type, board), без тикеров
    try:
        pf = c.portfolio()
        rows = pf.get("positions") if isinstance(pf, dict) else pf
        pairs = sorted({(str(p.get("type")), str(p.get("board")))
                        for p in rows or [] if isinstance(p, dict)})
        print("PORTFOLIO boards (type, board):", pairs)
    except Exception as e:
        print("PORTFOLIO fail:", e)

    # 2) типы инструментов с пагинацией
    sample_keys_printed = False
    for t in TYPES:
        try:
            rows = paged_by_type(c, t)
        except Exception as e:
            print(f"TYPE {t}: FAIL {e}")
            continue
        otc = [x for x in rows if isinstance(x, dict) and is_otc(x)]
        print(f"TYPE {t}: всего {len(rows)}, внебиржевых {len(otc)}")
        if rows and not sample_keys_printed and isinstance(rows[0], dict):
            print("  поля инструмента:", sorted(rows[0].keys()))
            sample_keys_printed = True
        for x in otc[:3]:
            print("  OTC-пример:", json.dumps({k: x.get(k) for k in (
                "ticker", "displayName", "shortName", "tradingCurrency", "instrumentType",
                "primaryBoard", "boards", "isin")}, ensure_ascii=False, default=str)[:500])

    # 3) котировка известного OTC-тикера — схема полей
    for cc in ("OTC", "QMEBLCK", "MTQR"):
        try:
            q = c.quotes([{"ticker": PROBE_TICKER, "classCode": cc}])
            print(f"QUOTES {cc}:", json.dumps(q, ensure_ascii=False, default=str)[:600])
        except Exception as e:
            print(f"QUOTES {cc}: FAIL {e}")

    # 4) мета инструмента по тикеру
    try:
        info = c.post("/instruments/by-tickers", base=BASE_INFO, json={"tickers": [PROBE_TICKER]})
        print("BY-TICKERS:", json.dumps(info, ensure_ascii=False, default=str)[:800])
    except Exception as e:
        print("BY-TICKERS fail:", e)


if __name__ == "__main__":
    main()
