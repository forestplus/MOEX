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
from crypto_box import write_json_or_encrypted

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


def norm_cash(limits) -> list:
    if isinstance(limits, dict):
        items = limits.get("moneyLimit") or []
    elif isinstance(limits, list):
        items = limits  # вдруг API тоже отдаёт список верхним уровнем
    else:
        return []
    out = []
    for m in items:
        if not isinstance(m, dict):
            continue
        q = m.get("quantity") or {}
        out.append({"currency": m.get("currencyCode"), "sum": _f(q.get("value"))})
    return [c for c in out if c["sum"] is not None]


def norm_summary(marginal) -> dict:
    if not isinstance(marginal, dict):
        return {}
    v = marginal.get("portfolioCurrentValue") or {}
    st = marginal.get("portfolioStability") or {}
    ag = marginal.get("agreementData") or {}
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
    # API возвращает позиции списком верхнего уровня; на всякий случай принимаем и dict
    raw_positions = portfolio.get("positions") if isinstance(portfolio, dict) else portfolio
    positions = [norm_position(p) for p in raw_positions or [] if isinstance(p, dict)]

    cash, summary = [], {}
    try:
        cash = norm_cash(c.limits())
    except Exception as e:
        print("ПРЕДУПРЕЖДЕНИЕ: /limits недоступен:", e)
    try:
        summary = norm_summary(c.marginal_indicators())
    except Exception as e:
        print("ПРЕДУПРЕЖДЕНИЕ: /marginal-indicators недоступен:", e)

    mode = write_json_or_encrypted({
        "source": "BCS trade-api",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tokenExpiresInDays": (c.refresh_expires_in // 86400) if c.refresh_expires_in else None,
        "summary": summary,
        "cash": cash,
        "positions": positions,
    }, OUT, repo_root=OUT.parent.parent)
    print(f"OK: позиций {len(positions)}, денежных лимитов {len(cash)} -> {OUT} [{mode}]")


if __name__ == "__main__":
    main()
