"""Internal failure normalization shared by concrete default carriers."""

from typing import Never

from obst_defaults.carriers import CarrierError


def raise_carrier_failure(
    operation: str,
    endpoint: str,
    primary: BaseException,
    secondary: list[BaseException],
) -> Never:
    if isinstance(primary, CarrierError):
        error: BaseException = primary
    elif isinstance(primary, OSError):
        error = CarrierError(f"cannot {operation} {endpoint}: {primary}")
    else:
        error = primary
    for cleanup_error in secondary:
        error.add_note(
            f"carrier cleanup also failed: "
            f"{type(cleanup_error).__name__}: {cleanup_error}"
        )
    if error is primary:
        raise error
    raise error from primary
