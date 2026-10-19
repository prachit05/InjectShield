#!/bin/bash
# Runs inside LocalStack once it is ready: creates what storage.yaml and queue.yaml create on AWS.
set -euo pipefail

awslocal s3 mb s3://injectshield-prompts

DLQ_URL=$(awslocal sqs create-queue --queue-name injectshield-scan-dlq --query QueueUrl --output text)
DLQ_ARN=$(awslocal sqs get-queue-attributes --queue-url "$DLQ_URL" --attribute-names QueueArn \
  --query Attributes.QueueArn --output text)

awslocal sqs create-queue --queue-name injectshield-scan --attributes "{
  \"VisibilityTimeout\": \"60\",
  \"RedrivePolicy\": \"{\\\"deadLetterTargetArn\\\":\\\"$DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"
}"

echo "injectshield: bucket and queues ready"
