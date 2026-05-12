# Creator Analytics

A serverless YouTube channel analytics pipeline built on AWS. Automatically collects daily channel stats and serves them via a public dashboard.

**Live demo:** [d3oaw7mpp312ry.cloudfront.net](https://d3oaw7mpp312ry.cloudfront.net)

---

## What it does

Every morning at 9am UK time, a Lambda function pulls YouTube channel statistics (subscribers, views, video count) and writes them to DynamoDB. A public dashboard fetches the latest data via an API Gateway endpoint and renders a stat overview plus a Chart.js subscriber growth chart.

The pipeline runs entirely on serverless infrastructure — no servers to maintain, no instances to patch.

---

## Architecture

                      ┌────────────────────────┐
                      │   YouTube Data API v3  │
                      └────────────┬───────────┘
                                   │
                                   ▼
┌────────────────┐         ┌──────────────────────┐
│  EventBridge   │────────▶│  Collector Lambda    │
│  Scheduler     │  9am    │  (Python 3.13)       │
│  (daily cron)  │  UK     └──────────┬───────────┘
└────────────────┘                    │
▼
┌──────────────────────┐
│   DynamoDB           │
│   (creator-stats)    │◀─── partition key: date
└──────────┬───────────┘
│
▼
┌──────────────────────┐
│   Reader Lambda      │
│   (Python 3.13)      │
└──────────┬───────────┘
│
▼
┌──────────────────────┐
│   API Gateway        │
│   (HTTP API)         │
│   GET /stats         │
└──────────┬───────────┘
│
▼
┌──────────────────────┐
│   CloudFront CDN     │
│   (HTTPS, global)    │
└──────────┬───────────┘
│
▼
┌──────────────────────┐
│   S3 Static Website  │
│   (HTML + Chart.js)  │
└──────────────────────┘

---

## AWS services used

| Service | Purpose |
|---|---|
| **Lambda** | Serverless functions (Collector + Reader, Python 3.13) |
| **DynamoDB** | NoSQL time-series storage with date-based partition key |
| **API Gateway** | Public HTTP API exposing the Reader Lambda |
| **EventBridge Scheduler** | Cron-based trigger for the daily Collector |
| **Secrets Manager** | YouTube API key storage with scoped IAM access |
| **S3** | Static hosting of the HTML dashboard |
| **CloudFront** | Global CDN with HTTPS and edge caching |
| **IAM** | Role-based access with least-privilege inline policies |
| **CloudWatch Logs** | Lambda execution logs and observability |

---

## Design decisions

**Date as partition key for idempotency.** The DynamoDB schema uses the date string (e.g. `2026-05-12`) as the partition key. If the Collector fires twice on the same day for any reason, the second write overwrites the first instead of creating a duplicate row. Idempotency is enforced by the schema, not by application logic.

**Least-privilege IAM throughout.** Every Lambda role has inline policies scoped to specific resource ARNs and specific actions. The Collector can `GetSecretValue` on exactly one secret and `PutItem` on exactly one table. The Reader can `Scan` on exactly one table. Wildcards aren't used.

**Two Lambdas, single responsibility.** The Collector writes; the Reader reads. Splitting them isolates failure domains — if the YouTube API breaks tomorrow, the dashboard keeps serving yesterday's data because the Reader has no dependency on YouTube.

**Public API by design.** The `/stats` endpoint has no authentication because the data is public anyway (it's the same stats anyone can see on YouTube). For an app with user data I'd add Cognito or API key auth.

**CloudFront in front of S3.** Not strictly necessary for a working site, but provides HTTPS (S3 website endpoints are HTTP-only) and avoids mobile carrier caching issues I've previously hit serving HTTP content.

---

## Debugged along the way

**Lambda timeout on third-party API calls.** The Collector hit AWS's default 3-second timeout when DynamoDB IAM permissions were missing — boto3 retried silently until the clock ran out, surfacing as `Sandbox.Timedout` instead of `AccessDeniedException`. Increasing the timeout to 30 seconds during development surfaced the real error.

**DynamoDB Decimal serialisation.** DynamoDB returns numbers as Python `Decimal` objects, which `json.dumps` can't serialise. The Reader includes a recursive `decimal_to_native` helper that converts them to int or float before returning JSON.

**CloudFront origin: website endpoint vs bucket endpoint.** AWS offers both as origin options for S3 buckets. The plain bucket endpoint (`s3.region.amazonaws.com`) breaks index document logic; the website endpoint (`s3-website.region.amazonaws.com`) is the right choice for static sites. AWS now warns about this during setup, which suggests how many people get it wrong.

**Timezone mismatch between EventBridge and Lambda.** EventBridge is scheduled in Europe/London time, the Lambda writes dates in UTC. At 9am UK time the dates align, but if the schedule ever moved near midnight UTC the "day" each system thinks it is could diverge. Production version would standardise on UTC end-to-end.

---

## Repository structure
creator-analytics/
├── lambdas/
│   ├── collector/
│   │   └── lambda_function.py    # Daily YouTube → DynamoDB
│   └── reader/
│       └── lambda_function.py    # DynamoDB → JSON API
├── dashboard/
│   └── index.html                # Static dashboard (HTML/CSS/JS + Chart.js)
├── docs/                         # Architecture notes
├── sentinel/                     # Server-based monitoring (future)
└── README.m

---

## Status

✅ Collector Lambda — fetches YouTube stats, writes to DynamoDB
✅ EventBridge schedule — daily at 9am UK time
✅ Reader Lambda — scans DynamoDB, returns JSON
✅ API Gateway — public `GET /stats` endpoint
✅ Dashboard — live on CloudFront with HTTPS
![alt text](image.png)