"""Map domain exceptions to clean JSON errors (never raw tracebacks)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from roulette_optimizer.play import LiveSessionError
from roulette_optimizer.utils import (
    ConfigError,
    PolicyError,
    SimulationError,
    SolverError,
    VerificationError,
)

from api.money import MoneyError


class SessionNotFoundError(Exception):
    """Companion or play session missing from the active store."""

    def __init__(self, message: str = "Companion session not found") -> None:
        self.message = message
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SessionNotFoundError)
    async def session_not_found(
        _request: Request, exc: SessionNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": exc.message},
        )

    @app.exception_handler(LiveSessionError)
    async def live_session_error(
        _request: Request, exc: LiveSessionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": exc.code, "detail": exc.message},
        )

    @app.exception_handler(ConfigError)
    async def config_error(_request: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "config", "detail": str(exc)})

    @app.exception_handler(MoneyError)
    async def money_error(_request: Request, exc: MoneyError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "money", "detail": str(exc)})

    @app.exception_handler(SolverError)
    async def solver_error(_request: Request, exc: SolverError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "solver", "detail": str(exc)})

    @app.exception_handler(VerificationError)
    async def verification_error(_request: Request, exc: VerificationError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"error": "verification", "detail": str(exc)}
        )

    @app.exception_handler(PolicyError)
    async def policy_error(_request: Request, exc: PolicyError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "policy", "detail": str(exc)})

    @app.exception_handler(SimulationError)
    async def simulation_error(_request: Request, exc: SimulationError) -> JSONResponse:
        return JSONResponse(
            status_code=400, content={"error": "simulation", "detail": str(exc)}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "validation", "detail": str(exc.errors())},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "http", "detail": detail},
        )

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, (HTTPException, StarletteHTTPException)):
            raise exc
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal",
                "detail": "An unexpected error occurred. Check server logs.",
            },
        )
