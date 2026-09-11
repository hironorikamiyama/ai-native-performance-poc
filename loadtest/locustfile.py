import os

from locust import HttpUser, between, task


class ApiUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(9)
    def list_items(self) -> None:
        delay_ms = int(os.getenv("POC_DELAY_MS", "20"))
        fail_rate = float(os.getenv("POC_FAIL_RATE", "0"))
        self.client.get(
            "/items",
            params={"delay_ms": delay_ms, "fail_rate": fail_rate, "limit": 20},
            name="/items",
        )

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="/health")
