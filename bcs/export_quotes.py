import json
import os
import pathlib
from datetime import datetime, timezone
from bcs_client import BcsClient

TICKERS = pathlib.Path("bcs/tickers.txt")
OUT = pathlib.Path("data/bcs_quotes.json")


def main():
    tickers = [t.strip() for t in TICKERS.read_text(encoding="utf-8").splitlines()
               if t.strip() and not t.startswith("#")]
    c = BcsClient(os.environ["BCS_API_KEY_READ"])
    # ПРОВЕРИТЬ формат: здесь предполагается список инструментов с тикером и classCode
    payload = {"instruments": [{"ticker": t, "classCode": "TQBR"} for t in tickers]}
    data = c.quotes(payload)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "BCS trade-api",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": data,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: {len(tickers)} тикеров -> {OUT}")


if __name__ == "__main__":
    main()
