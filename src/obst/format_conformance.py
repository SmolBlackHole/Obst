"""Package-owned conformance suite for the OBST wire format."""

from importlib.resources import files

from obst.conformance import ConformanceSuite, load_conformance_suite


def obst_conformance() -> ConformanceSuite:
    """Load the static format vectors shipped with the runtime distribution."""
    return load_conformance_suite(files("obst.conformance").joinpath("corpus"))


__all__ = ["obst_conformance"]
