from app.aggregators.mock import MockAggregator
from app.aggregators.port import AggregatorPort

_SUPPORTED = {"talabat", "deliveroo", "careem", "ubereats"}


def get_aggregator_port(provider: str) -> AggregatorPort:
    if provider not in _SUPPORTED:
        raise ValueError(f"unsupported aggregator provider: {provider}")
    # No real Talabat/Deliveroo/Careem/Uber Eats SDK is wired in yet — each
    # needs its own signed partner agreement and API credentials. Every
    # provider runs through MockAggregator until that exists; swapping in a
    # real per-provider adapter here is the only change needed later.
    return MockAggregator(provider)
