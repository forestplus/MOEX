"""
Выгрузка портфеля БКС в data/bcs_portfolio.json для страницы portfolio.html.

Собирает:
- /portfolio          — позиции (количество, цены, P/L, доля в портфеле);
- /limits             — свободные деньги (moneyLimit);
- /marginal-indicators — оценка портфеля, изменение за день/за всё время, устойчивость.

Часть эндпоинтов может быть недоступна для отдельных счетов — тогда соответствующий
блок просто пропускается (best effort), главное — позиции.
"""

import json
import os
import pathlib
from datetime import datetime, timezone

from check_token import make_client

OUT = pathlib.Path(__file__).parent.parent / "data" / "bcs_portfolio.json"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def norm_position(p: dict) -> dict:
    return {
        "ticker": p.get("ticker"),
        "displayName": p.get("displayName"),
        "board": p.get("board"),
        "currency": p.get("currency"),
        "instrumentType": p.get("instrumentType"),
        "quantity": _f(p.get("quantity")),
        "balancePrice": _f(p.get("balancePrice")),
        "currentPrice": _f(p.get("currentPrice")),
        "currentValueRub": _f(p.get("currentValueRub") or p.get("currentValueR")),
        "unrealizedPL": _f(p.get("unrealizedPL")),
        "unrealizedPercentPL": _f(p.get("unrealizedPercentPL")),
        "dailyPL": _f(p.get("dailyPL")),
        "dailyPercentPL": _f(p.get("dailyPercentPL")),
        "portfolioShare": _f(p.get("portfolioShare")),
    }


def norm_cash(limits: dict) -> list:
    out = []
    for m in limits.get("moneyLimit") or []:
        q = m.get("quantity") or {}
        out.append({"currency": m.get("currencyCode"), "sum": _f(q.get("value"))})
    return [c for c in out if c["sum"] is not None]


def norm_summary(marginal: dict) -> dict:
    v = (marginal or {}).get("portfolioCurrentValue") or {}
    st = (marginal or {}).get("portfolioStability") or {}
    ag = (marginal or {}).get("agreementData") or {}
    return {
        "currentValueRub": _f(v.get("currentValueRub")),
        "dailyChangeRub": _f(v.get("dailyPortfolioChangeRub")),
        "dailyChangePct": _f(v.get("dailyPortfolioChangePerc")),
        "totalChangeRub": _f(v.get("totalPortfolioChangeRub")),
        "totalChangePct": _f(v.get("totalPortfolioChangePerc")),
        "stabilityStatus": st.get("stabilityStatusName"),
        "marginOn": st.get("isMarginOn"),
        "accountName": ag.get("displayName") or ag.get("number"),
        "isIis": ag.get("isIis"),
    }


def main():
    c = make_client()

    portfolio = c.portfolio()  # обязательный кусок — если упал, падаем
    positions = [norm_position(p) for p in portfolio.get("positions") or []]

    cash, summary = [], {}
    try:
        cash = norm_cash(c.limits())
    except Exception as e:
        print("ПРЕДУПРЕЖДЕНИЕ: /limits недоступен:", e)
    try:
        summary = norm_summary(c.marginal_indicators())
    except Exception as e:
        print("ПРЕДУПРЕЖДЕНИЕ: /marginal-indicators недоступен:", e)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "BCS trade-api",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tokenExpiresInDays": (c.refresh_expires_in // 86400) if c.refresh_expires_in else None,
        "summary": summary,
        "cash": cash,
        "positions": positions,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: позиций {len(positions)}, денежных лимитов {len(cash)} -> {OUT}")


if __name__ == "__main__":
    main()
