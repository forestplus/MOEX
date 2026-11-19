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
import re
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


_TERM_RE = re.compile(r"T(\d+)", re.I)


def _term_rank(p: dict) -> int:
    """Ранг срока расчётов: T0 -> 0, T1 -> 1, ...; без term считаем T0."""
    m = _TERM_RE.search(str(p.get("term") or ""))
    return int(m.group(1)) if m else 0


def dedupe_by_term(items: list) -> list:
    """
    БКС отдаёт одну позицию несколькими записями — по срокам расчётов (T0, T1, T2...).
    Запись с большим term КУМУЛЯТИВНА (включает сделки, расчёты по которым ещё не прошли),
    поэтому суммировать записи нельзя — берём для каждого инструмента запись
    с максимальным term: это актуальная позиция, как в приложении брокера.
    """
    best, order = {}, []
    for p in items or []:
        if not isinstance(p, dict):
            continue
        key = (p.get("type"), p.get("ticker"), p.get("board"))
        if key not in best:
            best[key] = p
            order.append(key)
        elif _term_rank(p) > _term_rank(best[key]):
            best[key] = p
    return [best[k] for k in order]


def main():
    c = make_client()

    portfolio = c.portfolio()  # обязательный кусок — если упал, падаем
    # API возвращает позиции списком верхнего уровня; на всякий случай принимаем и dict
    raw_positions = portfolio.get("positions") if isinstance(portfolio, dict) else portfolio

    if os.environ.get("BCS_DEBUG"):
        # структурная отладка: только дискриминирующие поля, без сумм
        import re as _re
        print(f"DEBUG: type={type(portfolio).__name__} len={len(raw_positions or [])}")
        if raw_positions and isinstance(raw_positions[0], dict):
            print("DEBUG keys #0:", sorted(raw_positions[0].keys()))
        for i, p in enumerate(raw_positions or []):
            if isinstance(p, dict) and p.get("ticker") in ("MGKL", "RUB", "EUTR"):
                print(f"DEBUG FULL #{i}: {json.dumps(p, ensure_ascii=False, default=str)[:1200]}")

    deduped = dedupe_by_term(raw_positions)
    if raw_positions is not None and len(deduped) != len(raw_positions):
        print(f"Дедупликация по срокам расчётов: {len(raw_positions)} -> {len(deduped)} записей")
    positions = [norm_position(p) for p in deduped]

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
