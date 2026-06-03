from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from queue import Queue

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent.parent
DEFAULT_INPUT = ROOT_DIR / "data" / "raw" / "machine_temperature_system_failure.csv"
DEFAULT_OUTPUT = BASE_DIR / "features.parquet"
DEFAULT_OUTPUT_JSON = BASE_DIR / "features.json"


@dataclass
class Event:
    timestamp: str
    value: float


def load_events(csv_path: Path) -> list[Event]:
    df = pd.read_csv(csv_path)
    ts_col = df.columns[0]
    value_col = df.columns[1]
    df[ts_col] = pd.to_datetime(df[ts_col], utc=False)
    df = df.sort_values(ts_col).reset_index(drop=True)
    return [
        Event(timestamp=row[ts_col].isoformat(), value=float(row[value_col]))
        for _, row in df.iterrows()
    ]


def build_features(queue: Queue) -> pd.DataFrame:
    history = deque(maxlen=288)
    rows = []
    previous_value = None

    while not queue.empty():
        event: Event = queue.get()
        history.append(event.value)
        window = list(history)
        rolling_mean_1h = sum(window[-12:]) / min(len(window), 12)
        rolling_std_1h = float(pd.Series(window[-12:]).std(ddof=0)) if len(window) > 1 else 0.0
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
    input_path = DEFAULT_INPUT
    output_parquet = DEFAULT_OUTPUT
    output_json = DEFAULT_OUTPUT_JSON

    events = load_events(input_path)
    queue: Queue = Queue()
    for event in events:
        queue.put(event)

    features = build_features(queue)

    try:
        features.to_parquet(output_parquet, index=False)
        output_message = f"wrote {output_parquet.name}"
    except Exception:
        features.to_json(output_json, orient="records", lines=True)
        output_message = f"wrote {output_json.name}"

    summary = {
        "input_rows": len(events),
        "output_rows": len(features),
        "output": output_message,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
