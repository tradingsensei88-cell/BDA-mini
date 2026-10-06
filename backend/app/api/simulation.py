"""Simulation control routes.

Drive the traffic source feeding the platform: the built-in demo generator
(default) or an attached external producer (Kafka). All actions return the
post-action status so the UI can update in one round trip.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SimulationDep
from app.schemas.simulation import (
    SimulationControl,
    SimulationControlResponse,
    SimulationStatus,
)

router = APIRouter(tags=["simulation"])


def _wrap(message: str, status: dict) -> SimulationControlResponse:
    return SimulationControlResponse(
        ok=True,
        message=message,
        status=SimulationStatus.model_validate(status),
    )


@router.get(
    "/status",
    response_model=SimulationStatus,
    summary="Simulation status",
    description=(
        "Current state (running / paused / stopped), configured vs measured "
        "event rate, totals, alert/anomaly counters and category breakdown."
    ),
)
async def simulation_status(simulation: SimulationDep) -> SimulationStatus:
    return SimulationStatus.model_validate(simulation.get_status())


@router.post(
    "/start",
    response_model=SimulationControlResponse,
    summary="Start the simulation",
    description="Starts the demo generator (or the attached producer). Idempotent - resumes when paused.",
)
async def start_simulation(simulation: SimulationDep) -> SimulationControlResponse:
    status = await simulation.start()
    return _wrap("Simulation started.", status)


@router.post(
    "/pause",
    response_model=SimulationControlResponse,
    summary="Pause the simulation",
    description="Suspends event emission while keeping the generator task alive.",
)
async def pause_simulation(simulation: SimulationDep) -> SimulationControlResponse:
    status = await simulation.pause()
    return _wrap("Simulation paused.", status)


@router.post(
    "/resume",
    response_model=SimulationControlResponse,
    summary="Resume the simulation",
    description="Resumes emission after a pause (starts the simulation when stopped).",
)
async def resume_simulation(simulation: SimulationDep) -> SimulationControlResponse:
    status = await simulation.resume()
    return _wrap("Simulation resumed.", status)


@router.post(
    "/reset",
    response_model=SimulationControlResponse,
    summary="Reset the simulation",
    description=(
        "Stops the simulation and zeroes its statistics (event counters, "
        "alerts generated, anomalies, category breakdown). Platform state "
        "(event buffer, alerts, investigations) is left intact."
    ),
)
async def reset_simulation(simulation: SimulationDep) -> SimulationControlResponse:
    status = await simulation.reset()
    return _wrap("Simulation reset.", status)


@router.post(
    "/rate",
    response_model=SimulationControlResponse,
    summary="Set the event rate",
    description="Change the emission rate in events/second (1-10000); applied live.",
)
async def set_rate(
    payload: SimulationControl, simulation: SimulationDep
) -> SimulationControlResponse:
    status = await simulation.set_rate(payload.rate)
    return _wrap(f"Event rate set to {payload.rate}/s.", status)
