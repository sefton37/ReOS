"""Request routing — classify and dispatch to agents."""

from trcore.atomic_ops.processor import AtomicOpsProcessor

from .router import RequestRouter, RoutingResult

__all__ = ["AtomicOpsProcessor", "RequestRouter", "RoutingResult"]
