"""Send scan jobs to SQS."""

from __future__ import annotations

from injectshield_shared.models import JobMessage


class JobQueue:
    def __init__(self, sqs_client, queue_url: str):
        self.sqs = sqs_client
        self.queue_url = queue_url

    def send(self, message: JobMessage) -> None:
        self.sqs.send_message(QueueUrl=self.queue_url, MessageBody=message.model_dump_json())
