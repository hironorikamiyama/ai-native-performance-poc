from locust import HttpUser, between, events, task
from locust.runners import LocalRunner

import gevent
import logging
import os


logger = logging.getLogger(__name__)


def reset_stats(environment) -> None:
    """Reset Locust statistics after the warm-up period."""
    runner = environment.runner
    if runner is None:
        logger.warning("Stats reset skipped: runner is not available")
        return

    runner.stats.reset_all()
    logger.info("Locust statistics reset after warm-up")


@events.test_start.add_listener
def schedule_stats_reset(environment, **kwargs) -> None:
    """Schedule one statistics reset when a local test starts."""
    warmup_seconds = float(
        os.getenv("POC_WARMUP_SECONDS", "0")
    )

    if warmup_seconds <= 0:
        logger.info("Stats reset disabled: warm-up is 0 seconds")
        return

    if not isinstance(environment.runner, LocalRunner):
        logger.warning(
            "Stats reset skipped: only LocalRunner is supported"
        )
        return

    logger.info(
        "Locust statistics will reset after %.1f seconds",
        warmup_seconds,
    )
    gevent.spawn_later(
        warmup_seconds,
        reset_stats,
        environment,
    )


class ApiUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(9)
    def list_items(self) -> None:
        delay_ms = int(os.getenv("POC_DELAY_MS", "20"))
        fail_rate = float(os.getenv("POC_FAIL_RATE", "0"))
        self.client.get(
            "/items",
            params={
                "delay_ms": delay_ms,
                "fail_rate": fail_rate,
                "limit": 20,
            },
            name="/items",
        )

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="/health")