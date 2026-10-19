"""boto3 client factory that points at LocalStack when AWS_ENDPOINT_URL is set."""

from __future__ import annotations

import boto3

from .config import Settings


def client(service: str, settings: Settings):
    return boto3.client(
        service,
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )
