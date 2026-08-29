# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Static portable conformance suite shipped by the defaults plugin."""

from importlib.resources import files

from obst.conformance import ConformanceSuite, load_conformance_suite


def obst_conformance() -> ConformanceSuite:
    """Load the package-owned vectors without discovering test modules."""
    return load_conformance_suite(
        files("obst_defaults").joinpath("conformance_vectors")
    )


__all__ = ["obst_conformance"]
