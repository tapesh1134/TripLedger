import json
import logging
import time
import uuid
import pika
from .config import env, service_key
from .database import initialize, connect, query
from .reviewer import review, internal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def process(body):
    event = json.loads(body)
    job_id = str(uuid.UUID(event["jobId"]))
    # Session advisory lock prevents concurrent processing of the same delivery.
    with connect() as c:
        locked = query(
            c, "SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired", (job_id,)
        )[0]["acquired"]
        c.commit()
        if not locked:
            raise RuntimeError("Review already being processed")
        try:
            previous = query(c, "SELECT result FROM reviews WHERE job_id=%s", (job_id,))
            c.commit()
            if previous:
                result = previous[0]["result"]
                if isinstance(result, str):
                    result = json.loads(result)
            else:
                snapshot = internal("GET", f"/internal/jobs/{job_id}")
                internal("POST", f"/internal/jobs/{job_id}/started", body={})
                try:
                    result = review(job_id)
                except Exception as e:
                    logging.warning(
                        "review_failed job=%s type=%s", job_id, type(e).__name__
                    )
                    result = {
                        "status": "FAILED",
                        "summary": "AI review failed. Check provider access, policy index and service logs, then retry or review manually.",
                        "errorType": type(e).__name__,
                    }
                query(
                    c,
                    "INSERT INTO reviews(job_id,report_id,revision,result) VALUES(%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",
                    (
                        job_id,
                        snapshot["report_id"],
                        snapshot["revision"],
                        json.dumps(result),
                    ),
                )
                c.commit()
            # Delivery is acknowledged only after the Expense Service persists the result.
            internal("POST", f"/internal/jobs/{job_id}/result", body=result)
        finally:
            query(c, "SELECT pg_advisory_unlock(hashtext(%s))", (job_id,))


def main():
    service_key()
    initialize()
    while True:
        try:
            credentials = pika.PlainCredentials(
                env("RABBIT_USER", "tripledger"), env("RABBIT_PASSWORD")
            )
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    env("RABBIT_HOST", "127.0.0.1"),
                    int(env("RABBIT_PORT", "5672")),
                    credentials=credentials,
                    heartbeat=0,
                    blocked_connection_timeout=60,
                )
            )
            channel = connection.channel()
            channel.queue_declare(queue="tripledger.review", durable=True)
            channel.basic_qos(prefetch_count=1)
            logging.info("review_worker_ready")
            for method, properties, body in channel.consume(
                "tripledger.review", inactivity_timeout=1
            ):
                if method is None:
                    continue
                try:
                    process(body)
                    channel.basic_ack(method.delivery_tag)
                except (ValueError, KeyError, json.JSONDecodeError):
                    logging.error("invalid_queue_message_rejected")
                    channel.basic_reject(method.delivery_tag, requeue=False)
                except Exception as e:
                    logging.warning("delivery_retry type=%s", type(e).__name__)
                    channel.basic_nack(method.delivery_tag, requeue=True)
                    time.sleep(5)
        except KeyboardInterrupt:
            return
        except Exception as e:
            logging.warning("worker_reconnect type=%s", type(e).__name__)
            time.sleep(5)


if __name__ == "__main__":
    main()
