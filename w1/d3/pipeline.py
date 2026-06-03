from __future__ import annotations

import csv
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from queue import Queue

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent.parent
DEFAULT_INPUT = ROOT_DIR / "data" / "raw" / "machine_temperature_system_failure.csv"
DEFAULT_OUTPUT_PARQUET = BASE_DIR / "features.parquet"
DEFAULT_OUTPUT_JSON = BASE_DIR / "features.json"


@dataclass(frozen=True)
class Event:
    timestamp: str
    value: float


def load_events(csv_path: Path) -> list[Event]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [Event(timestamp=row["timestamp"], value=float(row["value"])) for row in reader]


def producer(events: list[Event], queue: Queue) -> None:
    for event in events:
        queue.put(event)
    queue.put(None)


def consumer(queue: Queue) -> pd.DataFrame:
    history = deque(maxlen=288)
    rows = []
    previous_value = None

    while True:
        event = queue.get()
        if event is None:
            break

        history.append(event.value)
        window = list(history)
        recent_12 = window[-12:]
        rolling_mean_1h = sum(recent_12) / len(recent_12)
        rolling_std_1h = float(pd.Series(recent_12).std(ddof=0)) if len(recent_12) > 1 else 0.0
        rolling_mean_24h = sum(window) / len(window)
        rate_of_change = 0.0 if previous_value is None else event.value - previous_value
        rate_of_change_1h = 0.0 if len(window) < 13 else event.value - window[-13]

        rows.append(
            {
                "timestamp": event.timestamp,
                "value": event.value,
                "rolling_mean_1h": rolling_mean_1h,
                "rolling_std_1h": rolling_std_1h,
                "rolling_mean_24h": rolling_mean_24h,
                "rate_of_change": rate_of_change,
                "rate_of_change_1h": rate_of_change_1h,
            }
        )
        previous_value = event.value

    return pd.DataFrame(rows)


def main() -> None:
    events = load_events(DEFAULT_INPUT)
    queue: Queue = Queue()
    producer(events, queue)
    features = consumer(queue)

    try:
        features.to_parquet(DEFAULT_OUTPUT_PARQUET, index=False)
        output_file = DEFAULT_OUTPUT_PARQUET.name
    except Exception:
        features.to_json(DEFAULT_OUTPUT_JSON, orient="records", lines=True, force_ascii=False)
        output_file = DEFAULT_OUTPUT_JSON.name

    print(
        json.dumps(
            {
                "input_rows": len(events),
                "output_rows": len(features),
                "output_file": output_file,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
