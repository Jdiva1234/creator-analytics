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

---

## Two deliberate layers

This project intentionally uses both serverless and server-based patterns:

**Serverless (Creator Analytics) —** Lambda fires on a schedule, no servers to manage. The pipeline only costs money when it runs. Ideal for the data collection layer where work is bursty and event-driven.

**Server-based (Sentinel) —** Long-running Python service on EC2, managed by systemd, provisioned by Ansible. Continuously watching the API every 5 minutes. Better fit for monitoring than Lambda because the work is uniform and persistent — a 5-minute cron Lambda would still cost more and lose the benefits of having an actual host to inspect.

Building both side-by-side made the trade-offs concrete rather than theoretical.

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
| **EC2** | Sentinel monitoring host (t3.micro, Amazon Linux 2023) |
| **IAM** | Role-based access with least-privilege inline policies |
| **CloudWatch Logs** | Lambda execution logs and Sentinel health-check logs |

---

## Sentinel — Ansible-provisioned health checker

Sentinel is a separate EC2 instance that monitors Creator Analytics. It's deliberately built using traditional ops patterns to complement the serverless pipeline.

**Stack on the EC2:**
- Amazon Linux 2023, t3.micro
- Python 3 health check script (`health_check.py`)
- Managed by systemd (`sentinel.service`)
- Runs forever, restarts automatically on failure (`Restart=always`)
- Logs to both systemd journal AND CloudWatch Logs

**Provisioning is fully automated:**
- Single Ansible playbook (`sentinel/playbooks/sentinel.yml`)
- Idempotent — running it multiple times produces the same result
- Installs Python dependencies, drops the script, configures systemd, enables and starts the service
- IAM role attached to the EC2 via instance profile — no hardcoded credentials anywhere on the box

The Python script makes an HTTPS GET to the API Gateway endpoint every 5 minutes. It logs a JSON object containing status (UP/DOWN/DEGRADED), HTTP code, latency in milliseconds, and the number of rows returned. This data is queryable in CloudWatch Logs.

---

## Design decisions

**Date as partition key for idempotency.** The DynamoDB schema uses the date string (e.g. `2026-05-12`) as the partition key. If the Collector fires twice on the same day for any reason, the second write overwrites the first instead of creating a duplicate row. Idempotency is enforced by the schema, not by application logic.

**Least-privilege IAM throughout.** Every Lambda role has inline policies scoped to specific resource ARNs and specific actions. The Collector can `GetSecretValue` on exactly one secret and `PutItem` on exactly one table. The Reader can `Scan` on exactly one table. The Sentinel EC2 has CloudWatch Logs write permissions only.

**Two Lambdas, single responsibility.** The Collector writes; the Reader reads. Splitting them isolates failure domains — if the YouTube API breaks tomorrow, the dashboard keeps serving yesterday's data because the Reader has no dependency on YouTube.

**Public API by design.** The `/stats` endpoint has no authentication because the data is public anyway. For an app with user data I'd add Cognito or API key auth.

**External monitor, not self-monitor.** Sentinel is deliberately separate from Creator Analytics. If the API fell over, having the API monitor itself would be useless. Sentinel watches it from outside — the same principle used by Pingdom, Datadog, and CloudWatch Synthetics in production systems.

**Ansible over manual setup.** Sentinel is small enough that I could have provisioned it manually with SSH commands. I deliberately wrote an Ansible playbook instead. The playbook is version-controlled, idempotent, and reproducible. If I lose the EC2 tomorrow, I can re-create it from a fresh image in under five minutes.

---

## Gotchas debugged along the way

**Lambda timeout on third-party API calls.** The Collector hit AWS's default 3-second timeout when DynamoDB IAM permissions were missing — boto3 retried silently until the clock ran out, surfacing as `Sandbox.Timedout` instead of `AccessDeniedException`. Increasing the timeout to 30 seconds during development surfaced the real error.

**DynamoDB Decimal serialisation.** DynamoDB returns numbers as Python `Decimal` objects, which `json.dumps` can't serialise. The Reader includes a recursive `decimal_to_native` helper that converts them to int or float before returning JSON.

**CloudFront origin: website endpoint vs bucket endpoint.** AWS offers both as origin options for S3 buckets. The plain bucket endpoint breaks index document logic; the website endpoint is the right choice for static sites. AWS now warns about this during setup, which suggests how many people get it wrong.

**Timezone mismatch between EventBridge and Lambda.** EventBridge is scheduled in Europe/London time, the Lambda writes dates in UTC. At 9am UK time the dates align, but if the schedule ever moved near midnight UTC the "day" each system thinks it is could diverge. Production version would standardise on UTC end-to-end.

**EC2 instance profile credential propagation.** Attaching an IAM role to a running EC2 doesn't propagate credentials instantly — the AWS CLI reported "Unable to locate credentials" for 10-30 seconds before picking up the role from the Instance Metadata Service. Worth knowing for future production troubleshooting.

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
├── sentinel/
│   ├── playbooks/
│   │   └── sentinel.yml          # Ansible playbook (provisions everything)
│   ├── files/
│   │   ├── health_check.py       # Python health check script
│   │   └── sentinel.service      # systemd unit file
│   └── inventory/
│       └── hosts.ini             # Ansible inventory
├── docs/                         # Architecture notes
└── README.md
---

## Status

✅ Collector Lambda — fetches YouTube stats, writes to DynamoDB
✅ EventBridge schedule — daily at 9am UK time
✅ Reader Lambda — scans DynamoDB, returns JSON
✅ API Gateway — public `GET /stats` endpoint
✅ Dashboard — live on CloudFront with HTTPS
✅ Sentinel — EC2 + systemd + Ansible monitoring health-check companion
![alt text](image.png)