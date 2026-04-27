"""Public API surface for Eau du Grand Lyon."""
from .auth import ApiError, AuthenticationError, NetworkError, WafBlockedError
from .client import EauGrandLyonApi
from .endpoints import MONTHS_FR

__all__ = [
    "ApiError",
    "AuthenticationError",
    "EauGrandLyonApi",
    "MONTHS_FR",
    "NetworkError",
    "WafBlockedError",
]
