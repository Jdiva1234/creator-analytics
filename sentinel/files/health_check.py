#!/usr/bin/env python3
"""
Sentinel — Creator Analytics health check.
Pings the API every 5 minutes and logs the result to CloudWatch Logs.
"""

import json
import logging
import time
from datetime import datetime, timezone

import boto3
import requests

# Configuration
API_URL = 'https://durxju8sfj.execute-api.eu-west-2.amazonaws.com/stats'
REGION = 'eu-west-2'
LOG_GROUP = '/sentinel/health-check'
LOG_STREAM = 'main'
CHECK_INTERVAL_SECONDS = 300  # 5 minutes

# Set up basic logging to stdout too (visible in systemd journal)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
log = logging.getLogger(__name__)


def ensure_log_group(client):
    """Create the CloudWatch log group if it doesn't exist."""
    try:
        client.create_log_group(logGroupName=LOG_GROUP)
        log.info(f"Created log group: {LOG_GROUP}")
    except client.exceptions.ResourceAlreadyExistsException:
        pass


def ensure_log_stream(client):
    """Create the CloudWatch log stream if it doesn't exist."""
    try:
        client.create_log_stream(logGroupName=LOG_GROUP, logStreamName=LOG_STREAM)
        log.info(f"Created log stream: {LOG_STREAM}")
    except client.exceptions.ResourceAlreadyExistsException:
        pass


def send_to_cloudwatch(client, message):
    """Push a single log line to CloudWatch."""
    timestamp_ms = int(time.time() * 1000)
    client.put_log_events(
        logGroupName=LOG_GROUP,
        logStreamName=LOG_STREAM,
        logEvents=[{'timestamp': timestamp_ms, 'message': message}],
    )


def check_api():
    """Hit the API and return a status dict."""
    started = time.time()
    try:
        response = requests.get(API_URL, timeout=10)
        latency_ms = round((time.time() - started) * 1000)
        return {
            'status': 'UP' if response.status_code == 200 else 'DEGRADED',
            'http_code': response.status_code,
            'latency_ms': latency_ms,
            'rows': len(response.json()) if response.status_code == 200 else 0,
        }
    except requests.exceptions.RequestException as e:
        return {
            'status': 'DOWN',
            'http_code': None,
            'latency_ms': round((time.time() - started) * 1000),
            'error': str(e),
        }


def main():
    log.info("Sentinel health check starting...")
    cw = boto3.client('logs', region_name=REGION)
    ensure_log_group(cw)
    ensure_log_stream(cw)

    while True:
        result = check_api()
        timestamp = datetime.now(timezone.utc).isoformat()
        message = json.dumps({'timestamp': timestamp, **result})
        log.info(message)
        try:
            send_to_cloudwatch(cw, message)
        except Exception as e:
            log.error(f"Failed to push to CloudWatch: {e}")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == '__main__':
    main()
