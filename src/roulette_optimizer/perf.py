from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field


@dataclass
class PerformanceTimings:
    config_validation_ms: float = 0.0
    state_space_ms: float = 0.0
    solver_total_ms: float = 0.0
    bellman_iterations_ms: float = 0.0
    policy_extraction_ms: float = 0.0
    policy_evaluation_ms: float = 0.0
    bellman_verification_ms: float = 0.0
    legality_verification_ms: float = 0.0
    verification_total_ms: float = 0.0
    cache_lookup_ms: float = 0.0
    cache_write_ms: float = 0.0
    api_overhead_ms: float = 0.0
    total_ms: float = 0.0
    solver_name: str = ""
    iterations: int = 0
    non_terminal_states: int = 0
    candidate_color_evaluations: int = 0
    candidate_dice_evaluations: int = 0
    convergence_reason: str = ""
    cache_status: str = "DISABLED"
    extras: dict[str, float | int | str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        extras = d.pop("extras", {})
        d.update(extras)
        return d


class PerfClock:
    """Lightweight scoped timer accumulating into PerformanceTimings fields."""

    __slots__ = ("_t0",)

    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    def ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0

    def restart(self) -> float:
        elapsed = self.ms()
        self._t0 = time.perf_counter()
        return elapsed
