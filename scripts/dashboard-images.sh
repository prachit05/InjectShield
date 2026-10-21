#!/usr/bin/env bash
# Save the dashboard's key graphs as PNGs (report evidence without console screenshots).
#
#   scripts/dashboard-images.sh                 # last 60 minutes into docs/screenshots/
#   MINUTES=120 OUT=/tmp/shots scripts/dashboard-images.sh
#
# Uses CloudWatch GetMetricWidgetImage, so it renders the same metrics as the
# injectshield dashboard: queue depth vs running workers, scan latency,
# throughput and errors, and the dead-letter queue against its alarm threshold.
set -euo pipefail
source "$(dirname "$0")/common.sh"

MINUTES="${MINUTES:-60}"
OUT="${OUT:-$ROOT/docs/screenshots}"
mkdir -p "$OUT"

QUEUE=$(stack_output queue ScanQueueName)
DLQ=$(stack_output queue DeadLetterQueueName)
CLUSTER=$(stack_output compute ClusterName)
WORKERS=$(stack_output compute WorkerServiceName)

render() { # render <file> <widget json>
  aws_ cloudwatch get-metric-widget-image --metric-widget "$2" --output-format png \
    --query MetricWidgetImage --output text | base64 --decode >"$OUT/$1"
  echo "saved $OUT/$1"
}

common="\"width\": 1000, \"height\": 400, \"start\": \"-PT${MINUTES}M\", \"region\": \"$REGION\", \"period\": 60"

render autoscaling.png "{ $common,
  \"title\": \"Autoscaling: scan-queue backlog vs running workers\",
  \"metrics\": [
    [\"AWS/SQS\", \"ApproximateNumberOfMessagesVisible\", \"QueueName\", \"$QUEUE\", {\"label\": \"Messages waiting\", \"stat\": \"Maximum\"}],
    [\"ECS/ContainerInsights\", \"RunningTaskCount\", \"ClusterName\", \"$CLUSTER\", \"ServiceName\", \"$WORKERS\", {\"label\": \"Running workers\", \"stat\": \"Maximum\", \"yAxis\": \"right\"}]
  ],
  \"yAxis\": {\"left\": {\"min\": 0, \"label\": \"messages\"}, \"right\": {\"min\": 0, \"max\": 6, \"label\": \"tasks\"}}}"

render throughput.png "{ $common,
  \"title\": \"Jobs completed and scan errors per minute\",
  \"metrics\": [
    [\"InjectShield\", \"JobsCompleted\", \"Service\", \"worker\", {\"label\": \"Jobs completed\", \"stat\": \"Sum\"}],
    [\".\", \"ScanErrors\", \".\", \".\", {\"label\": \"Scan errors\", \"stat\": \"Sum\", \"color\": \"#d62728\"}]
  ],
  \"yAxis\": {\"left\": {\"min\": 0}}}"

render latency.png "{ $common,
  \"title\": \"Latency (ms): scan and submit-to-verdict\",
  \"metrics\": [
    [\"InjectShield\", \"ProcessingLatency\", \"Service\", \"worker\", {\"label\": \"Worker processing p95\", \"stat\": \"p95\"}],
    [\".\", \"EndToEndLatency\", \".\", \".\", {\"label\": \"Submit to verdict p50\", \"stat\": \"p50\"}],
    [\"...\", {\"label\": \"Submit to verdict p95\", \"stat\": \"p95\"}]
  ],
  \"yAxis\": {\"left\": {\"min\": 0}}}"

render dead-letter-queue.png "{ $common,
  \"title\": \"Dead-letter queue (alarm at 1 message)\",
  \"metrics\": [
    [\"AWS/SQS\", \"ApproximateNumberOfMessagesVisible\", \"QueueName\", \"$DLQ\", {\"label\": \"Messages in DLQ\", \"stat\": \"Maximum\", \"color\": \"#d62728\"}]
  ],
  \"annotations\": {\"horizontal\": [{\"label\": \"alarm threshold\", \"value\": 1}]},
  \"yAxis\": {\"left\": {\"min\": 0}}}"
