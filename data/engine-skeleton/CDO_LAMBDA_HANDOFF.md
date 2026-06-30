# CDO Handoff — FinOps AI Engine as a Lambda (ingest + detect + LLM RCA)

This image lets the CDO `tf2-finops-*-ai-request` Lambda **ingest saved telemetry,
run anomaly detection, and produce Bedrock-Nova LLM RCA + actions** — packaged for
direct `lambda:CreateFunction --package-type Image`.

| | |
|---|---|
| **Image** | `197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:lambda` |
| **Handler** | `app.lambda_handler.handler` (built into the image CMD) |
| **Base** | `public.ecr.aws/lambda/python:3.12` (Lambda Runtime Interface included) |
| **ECR cross-account** | already allowed for acct `093490087544` + `tf2-finops-*-ai-request` |
| **Status** | ✅ **Verified live** (function created + invoked in 197826770971, all 3 tests pass) |

## ✅ Verified end-to-end (live Lambda invoke)

Deployed `tf2-finops-ai-test` (mem 1024, timeout 300, `RCA_MODE=offline`) and invoked:

| Test | Result |
|---|---|
| S3 ingest (`{"s3_pointer":"s3://…/cur/….json.gz"}`) | `200` → `ingested_from` set, `anomalies_detected=true`, runbook returned |
| Inline (`{"aws_cur_line_items":[…]}`) | `200` → anomaly + `rca[].root_cause_analysis` + `action_plan` |
| HTTP `GET /health` (Mangum) | `200` → `{"status":"healthy"}` |

## ⚠️ CRITICAL build note (or CreateFunction fails)

Lambda rejects images that carry Buildx **provenance/SBOM attestation manifests**
(error: *"image manifest … media type … is not supported"*). **Always build the
Lambda image with attestations off:**

```bash
docker build --platform linux/amd64 --provenance=false --sbom=false \
  -f Dockerfile.lambda -t <repo>:lambda .
```

(The `:lambda` and `:lambda-lwa` tags now in ECR are already built this way.)

## Variants in ECR

| Tag | Approach | Use when |
|---|---|---|
| **`:lambda`** | Native handler + **Mangum** (no Lambda Web Adapter) | Lambda — supports S3-event / direct-invoke ingest **and** HTTP. Recommended. |
| **`:lambda-lwa`** | **Lambda Web Adapter** (uvicorn unmodified) | Lambda via Function URL/API GW only (HTTP). Same image also runs on ECS/App Runner. |
| `:v1.1.0` / `:latest` | uvicorn HTTP server | ECS / Fargate / App Runner (NOT Lambda) |

## Three ways the CDO can call it

**1. Direct invoke — ingest from the save location (S3 pointer)**
```json
{ "s3_pointer": "s3://company-cdo-093490087544-telemetry/cur/2026-06-30.json.gz",
  "business_context": { "linked_account_id": "093490087544", "traffic_volume": 0,
    "traffic_source": "Mixed", "campaign_flag": false, "load_test_flag": false,
    "migration_flag": false, "scheduled_backup_flag": false } }
```

**2. S3 trigger** — point an S3 `ObjectCreated` event at the function; it ingests the
new object automatically. (`s3:ObjectCreated:*` notification on the telemetry bucket.)

**3. Inline detect body** — `{ "aws_cur_line_items": [...], "resource_utilization_metrics": [...] }`

**4. HTTP** (API Gateway / Function URL) — the full FastAPI app is served via Mangum,
so `/v1/detect`, `/v1/decide`, `/v1/verify`, `/v1/status`, `/health` all work unchanged.

### Response (modes 1–3)
```json
{ "correlation_id": "…", "anomalies_detected": true,
  "anomalies": [ … ],
  "rca": [ { "anomaly_id": "ANM-…", "matched_runbook": "…",
             "root_cause_analysis": { "primary_driver_feature": "…",
               "technical_reason": "…", "missing_mandatory_tags": [ … ] },
             "executive_summary": "…", "action_plan": [ … ], "applied_payload": { … } } ],
  "ingested_from": "s3://…", "saved_to": "s3://…|null" }
```

## Create the function (CDO)
```bash
aws lambda create-function \
  --function-name tf2-finops-prod-ai-request \
  --package-type Image \
  --code ImageUri=197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:lambda \
  --role arn:aws:iam::093490087544:role/<lambda-exec-role> \
  --timeout 300 --memory-size 1024 \
  --environment "Variables={RCA_MODE=bedrock,BEDROCK_REGION=us-east-1,OUTPUT_S3_BUCKET=company-cdo-093490087544-telemetry}" \
  --region ap-southeast-1
```

## Env vars
| Var | Purpose |
|---|---|
| `RCA_MODE` | `bedrock` (live Nova RCA) \| `offline` (deterministic, no network — image default) |
| `BEDROCK_REGION` | Nova region, e.g. `us-east-1` |
| `OUTPUT_S3_BUCKET` | optional — write results JSON here (`finops-results/{correlation_id}.json`) |
| `DYNAMODB_FEATURE_STORE_TABLE` | `finops-feature-store-{env}` (optional hot-path features) |
| `DETECT_*` | optional threshold overrides (not hard-coded) — see deployment-contract |

## Execution-role IAM (CDO side)
```json
{ "Effect": "Allow", "Action": ["bedrock:InvokeModel"],
  "Resource": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-*" },
{ "Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::company-cdo-*-telemetry/*" },
{ "Effect": "Allow", "Action": ["s3:PutObject"], "Resource": "arn:aws:s3:::company-cdo-*-telemetry/finops-results/*" },
{ "Effect": "Allow", "Action": ["ecr:BatchGetImage","ecr:GetDownloadUrlForLayer","ecr:BatchCheckLayerAvailability"],
  "Resource": "arn:aws:ecr:ap-southeast-1:197826770971:repository/tf-2-ai-engine" }
```

## The LLM system prompt
RCA uses Bedrock **Nova Pro** (root cause) + **Nova Lite** (action), with the FinOps
system prompt in `app/services/ml/llm_rca.py` (`_build_rca_system_prompt`). It enforces
plain financial language for the CFO, the tag-policy floor, and the prod safety clamp
(prod never auto-shutdown). Set `RCA_MODE=bedrock` + Bedrock IAM to enable it; otherwise
the deterministic offline RCA returns the same JSON shape with no network call.
