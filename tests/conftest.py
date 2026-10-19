import os

import boto3
import pytest
from moto import mock_aws

# Never let a test reach real AWS, even if the developer has credentials configured.
os.environ.update(
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    AWS_SESSION_TOKEN="testing",
    AWS_DEFAULT_REGION="ap-south-1",
    AWS_REGION="ap-south-1",
)
os.environ.pop("AWS_PROFILE", None)
os.environ.pop("AWS_ENDPOINT_URL", None)

REGION = "ap-south-1"
BUCKET = "test-prompts"


@pytest.fixture
def aws_resources():
    """Moto S3 bucket plus a scan queue with a DLQ after 3 receives, like queue.yaml."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        sqs = boto3.client("sqs", region_name=REGION)
        dlq_url = sqs.create_queue(QueueName="scan-dlq")["QueueUrl"]
        dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        queue_url = sqs.create_queue(
            QueueName="scan",
            Attributes={
                "VisibilityTimeout": "60",
                "RedrivePolicy": f'{{"deadLetterTargetArn":"{dlq_arn}","maxReceiveCount":"3"}}',
            },
        )["QueueUrl"]
        yield {"s3": s3, "sqs": sqs, "queue_url": queue_url, "dlq_url": dlq_url, "bucket": BUCKET}
