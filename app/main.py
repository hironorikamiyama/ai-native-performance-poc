import asyncio
import random
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="Performance AI PoC", version="1.0.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/items")
async def list_items(
    delay_ms: Annotated[int, Query(ge=0, le=5_000)] = 20,
    fail_rate: Annotated[float, Query(ge=0, le=1)] = 0.0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    """A controllable endpoint for demonstrating latency and failures."""
    await asyncio.sleep(delay_ms / 1_000)
    if random.random() < fail_rate:
        raise HTTPException(status_code=503, detail="Simulated overload")
    return {
        "count": limit,
        "items": [{"id": index, "name": f"item-{index}"} for index in range(limit)],
    }
