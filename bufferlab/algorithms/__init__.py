"""Queue-management algorithms."""

from bufferlab.algorithms.base import DequeueResult, DropReason, QueueManager
from bufferlab.algorithms.codel import CoDel
from bufferlab.algorithms.drop_tail import DropTail
from bufferlab.algorithms.red import RED
from bufferlab.algorithms.registry import (
    ALGORITHMS,
    AlgorithmSpec,
    ParamSpec,
    algorithm_keys,
    build_queue_manager,
    get_algorithm,
    resolve_params,
    validate_params,
)

__all__ = [
    "ALGORITHMS",
    "RED",
    "AlgorithmSpec",
    "CoDel",
    "DequeueResult",
    "DropReason",
    "DropTail",
    "ParamSpec",
    "QueueManager",
    "algorithm_keys",
    "build_queue_manager",
    "get_algorithm",
    "resolve_params",
    "validate_params",
]
