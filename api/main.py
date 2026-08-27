"""Roulette Optimizer HTTP API — thin adapter over domain callables."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.errors import register_exception_handlers
from api.routes import router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from roulette_optimizer.policy_cache import init_policy_cache

    init_policy_cache()
    try:
        from roulette_optimizer.numba_solver import warm_up_kernels

        warm_up_kernels()
    except Exception as exc:  # pragma: no cover
        # Fall back: routes still work via numpy if numba warm-up fails.
        import logging

        logging.getLogger("api").error("Numba warm-up failed: %s", exc)
    yield


app = FastAPI(
    title="Roulette Optimizer API",
    version="0.1.0",
    description="Thin web adapter over the Dynamic Goal-Directed optimizer.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(router)
