"""
Выгрузка текущих котировок БКС в data/bcs_quotes.json.

NB: котировки БКС дублируют MOEX ISS (который страницы и так читают напрямую и бесплатно),
поэтому этот экспорт — скорее резерв/проверка. Ошибка здесь не должна валить весь workflow
(в bcs.yml шаг помечен continue-on-error).
"""

import json
import os
import pathlib
from datetime import datetime, timezone

from check_token import make_client

TICKERS = pathlib.Path(__file__).parent / "tickers.txt"
OUT = pathlib.Path(__file__).parent.parent / "data" / "bcs_quotes.json"


def main():
    tickers = [t.strip() for t in TICKERS.read_text(encoding="utf-8").splitlines()
               if t.strip() and not t.startswith("#")]
    c = make_client()
    instruments = [{"ticker": t, "classCode": "TQBR"} for t in tickers]
    data = c.quotes(instruments)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "BCS trade-api",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": data,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: {len(tickers)} тикеров -> {OUT}")


if __name__ == "__main__":
    main()
