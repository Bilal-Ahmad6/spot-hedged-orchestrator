"""Spot-hedged elastic orchestrator.

The package is split so that the *policy* is independent of where it runs:

    model      pure data contracts (no I/O, no Kubernetes)
    forecast   demand forecasting
    policy     allocation (MILP) and the infeasibility ladder
    simulate   discrete-event testbed
    actuator   adapters that reconcile a Plan against a cluster
    controller Kubernetes operator wiring
"""

__version__ = "0.1.0"
