"""Single source of truth for the nineclaw container's service layout.

Centralises:
- the list of internal services exposed by a nineclaw container
- their internal container ports
- the Traefik route templates that proxy to them

Every other module (instance_service, docker_service, schemas, etc.) should
import from here instead of redefining service names or ports.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class NineclawService:
    """A single internal service exposed by a nineclaw container."""

    name: str          # logical name, used as port_mappings key (e.g. "gateway")
    internal_port: int  # container-side TCP port (e.g. 8642)
    route_template: str  # Traefik path template containing {instance_id}
    needs_auth: bool   # whether Traefik should inject Authorization for it


def _build_services() -> tuple[NineclawService, ...]:
    """Pair the three configured internal ports with their route templates.

    Order matters and must match nineclaw_internal_ports:
        index 0 → gateway   (OpenAI-compatible API)
        index 1 → webui     (static assets, no auth)
        index 2 → dashboard (REST API)
    """
    ports = settings.nineclaw_internal_ports
    if len(ports) != 3:
        raise ValueError(
            "nineclaw_internal_ports must contain exactly 3 ports "
            "(gateway, webui, dashboard); got %r" % (ports,)
        )

    return (
        NineclawService(
            name="gateway",
            internal_port=ports[0],
            route_template=settings.nineclaw_route_gateway,
            needs_auth=True,
        ),
        NineclawService(
            name="webui",
            internal_port=ports[1],
            route_template=settings.nineclaw_route_webui,
            needs_auth=False,
        ),
        NineclawService(
            name="dashboard",
            internal_port=ports[2],
            route_template=settings.nineclaw_route_dashboard,
            needs_auth=True,
        ),
    )


# Tuple, not list — service layout is immutable for the lifetime of the process.
NINECLAW_SERVICES: tuple[NineclawService, ...] = _build_services()


def render_route(template: str, instance_id: str) -> str:
    """Substitute {instance_id} in a route template and strip trailing slash."""
    return template.rstrip("/").replace("{instance_id}", instance_id)
