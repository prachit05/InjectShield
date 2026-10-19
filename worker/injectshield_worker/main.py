"""Scanner worker: long-poll SQS, fetch the prompt from S3, scan, write RDS, delete.

Reliability rules:
- the SQS message is deleted only after the verdict is committed
- a redelivered message for a finished job is just deleted (no duplicate verdict)
- a failing message is left on the queue; after worker_max_receives attempts SQS
  moves it to the dead-letter queue and the job is marked failed
"""

from __future__ import annotations

import json
import logging
import signal
import time
from datetime import UTC, datetime

from pydantic import ValidationError

from injectshield_shared import aws, metrics
from injectshield_shared.config import Settings, get_settings
from injectshield_shared.models import JobMessage, StoredPrompt

from .db import WorkerRepository
from .scanner import Scanner, build_scanner

log = logging.getLogger("injectshield.worker")


class Worker:
    def __init__(self, settings: Settings, sqs, s3, repo: WorkerRepository, scanner: Scanner):
        self.settings = settings
        self.sqs = sqs
        self.s3 = s3
        self.repo = repo
        self.scanner = scanner
        self._stopping = False

    def stop(self, *_args) -> None:
        log.info("shutdown requested, finishing current message")
        self._stopping = True

    def run_forever(self) -> None:
        log.info("worker started model_version=%s", self.scanner.model_version)
        while not self._stopping:
            try:
                self.poll_once()
            except Exception:
                log.exception("poll failed, backing off")
                time.sleep(5)
        log.info("worker stopped")

    def poll_once(self) -> int:
        response = self.sqs.receive_message(
            QueueUrl=self.settings.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=self.settings.worker_wait_seconds,
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        for message in messages:
            self.handle(message)
        return len(messages)

    def handle(self, message: dict) -> None:
        receive_count = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
        final_attempt = receive_count >= self.settings.worker_max_receives

        try:
            job = JobMessage.model_validate_json(message["Body"])
        except ValidationError:
            # Poison message: leave it, SQS sends it to the DLQ after max receives.
            log.error("malformed message id=%s receive_count=%d", message.get("MessageId"), receive_count)
            return

        started = time.perf_counter()
        try:
            if self.repo.start(job.job_id):
                stored = self._fetch(job.s3_key)
                verdict = self.scanner.scan(stored.prompt, stored.context)
                self.repo.finish(job.job_id, verdict)
                self._report(job, verdict.label, verdict.latency_ms or 0, started)
            else:
                log.info("job already done, dropping redelivery job_id=%s", job.job_id)
        except Exception as exc:
            log.exception("scan failed job_id=%s attempt=%d final=%s", job.job_id, receive_count, final_attempt)
            self._record_failure(job, exc, final_attempt)
            self._retry_later(message, receive_count)
            return

        self.sqs.delete_message(QueueUrl=self.settings.queue_url, ReceiptHandle=message["ReceiptHandle"])

    def _fetch(self, key: str) -> StoredPrompt:
        body = self.s3.get_object(Bucket=self.settings.bucket, Key=key)["Body"].read()
        return StoredPrompt.model_validate(json.loads(body))

    def _record_failure(self, job: JobMessage, exc: Exception, final: bool) -> None:
        try:
            self.repo.record_failure(job.job_id, f"{type(exc).__name__}: {exc}"[:500], final)
        except Exception:
            log.exception("could not record failure job_id=%s", job.job_id)
        metrics.emit("worker", {"ScanErrors": (1, "Count")})

    def _retry_later(self, message: dict, receive_count: int) -> None:
        delay = min(self.settings.worker_retry_delay_seconds * receive_count, 300)
        try:
            self.sqs.change_message_visibility(
                QueueUrl=self.settings.queue_url, ReceiptHandle=message["ReceiptHandle"], VisibilityTimeout=delay
            )
        except Exception:
            log.exception("could not set retry delay")

    def _report(self, job: JobMessage, label: str, scan_ms: int, started: float) -> None:
        processing_ms = int((time.perf_counter() - started) * 1000)
        end_to_end_ms = int((datetime.now(UTC) - job.submitted_at).total_seconds() * 1000)
        log.info("done job_id=%s label=%s scan_ms=%d processing_ms=%d", job.job_id, label, scan_ms, processing_ms)
        metrics.emit(
            "worker",
            {
                "ScanLatency": (scan_ms, "Milliseconds"),
                "ProcessingLatency": (processing_ms, "Milliseconds"),
                "EndToEndLatency": (end_to_end_ms, "Milliseconds"),
                "JobsCompleted": (1, "Count"),
            },
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    worker = Worker(
        settings,
        sqs=aws.client("sqs", settings),
        s3=aws.client("s3", settings),
        repo=WorkerRepository(settings.dsn),
        scanner=build_scanner(settings),
    )
    signal.signal(signal.SIGTERM, worker.stop)  # ECS sends SIGTERM on scale-in
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
