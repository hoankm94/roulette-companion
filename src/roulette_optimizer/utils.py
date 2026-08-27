class ConfigError(ValueError):
    """Invalid session or game configuration."""


class SolverError(RuntimeError):
    """Solver failed to converge or produce a valid policy."""


class VerificationError(RuntimeError):
    """Policy failed independent verification."""


class SimulationError(RuntimeError):
    """Simulation violated hard floor or policy contract."""


class PolicyError(ValueError):
    """Policy file could not be loaded or recommendation is invalid."""
