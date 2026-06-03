# W1-D3 Assignment Submission

## Files

- `pipeline.py`
- `architecture.md`
- `cost_model.py`
- `ADR-001.md`

## Screenshot / Diagram

Architecture diagram is included in [`architecture.md`](./architecture.md).

## Pipeline summary

The mock streaming pipeline reads `data/raw/machine_temperature_system_failure.csv`, simulates a producer by pushing rows into a `queue.Queue`, and computes rolling features on the consumer side.

Expected output:

- `features.parquet` when Parquet support is available
- `features.json` as fallback if Parquet dependencies are missing

## Cost estimate

Run:

```bash
uv run python cost_model.py
```

The script prints a monthly cost breakdown by tier for:

- storage
- compute
- network
- total

It also compares build vs Datadog SaaS.

## ADR summary

Decision: use Kafka for telemetry transport.

Reason:

- decouple producers from storage
- replay after downstream failure
- absorb burst traffic
- support multiple consumers from one stream

Trade-off:

- higher operational complexity
- slightly higher latency than direct push

## Reflection

If I were hired as Platform Engineer for a 50-service startup that just raised Series A, I would recommend a mostly build-first approach with selective buy:

- build the streaming pipeline and internal feature processing
- buy managed storage or managed observability where operating cost is too high

Reason: at 50 services, the team needs flexibility and cost control, but not a fully custom observability platform. A hybrid approach avoids lock-in while keeping the team focused on product work instead of running every subsystem.

## How to run

```bash
uv run python pipeline.py
uv run python cost_model.py
```
