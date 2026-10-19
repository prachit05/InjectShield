"""Put prompts in S3. The SQS message only carries the key."""

from __future__ import annotations

from injectshield_shared.models import StoredPrompt


class PromptStore:
    def __init__(self, s3_client, bucket: str):
        self.s3 = s3_client
        self.bucket = bucket

    def put(self, key: str, stored: StoredPrompt) -> None:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=stored.model_dump_json().encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
