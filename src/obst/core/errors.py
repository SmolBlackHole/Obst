"""Public core OBST error hierarchy."""


class ObstError(Exception):
    """Base class for OBST failures."""


class BinaryIOContractError(ObstError):
    """A binary endpoint violated the minimal reader or writer contract."""

    def __init__(self, endpoint: str, reason: str) -> None:
        self.endpoint = endpoint
        self.reason = reason
        super().__init__(f"binary {endpoint} contract violation: {reason}")


class ExtensionError(ObstError):
    """A registered extension capability is missing, conflicting or invalid."""


class ExtensionRegistrationError(ExtensionError):
    """An extension registration conflicts with an existing capability."""

    def __init__(self, extension_id: str, reason: str) -> None:
        self.extension_id = extension_id
        self.reason = reason
        super().__init__(f"cannot register extension {extension_id}: {reason}")


class ExtensionContractError(ExtensionError):
    """An extension provider violates its declared Python capability contract."""

    def __init__(self, extension_id: str, capability: str, reason: str) -> None:
        self.extension_id = extension_id
        self.capability = capability
        self.reason = reason
        super().__init__(
            f"extension {extension_id} {capability} contract violation: {reason}"
        )


class OperationStateError(ObstError):
    """A stateful public operation was invoked in an invalid state."""

    def __init__(self, operation: str, state: str) -> None:
        self.operation = operation
        self.state = state
        super().__init__(f"cannot {operation} in {state} state")


class ResourceLimitError(ObstError):
    """A valid operation was refused by its local resource policy."""

    def __init__(
        self,
        *,
        resource: str,
        scope: str,
        maximum: int,
        observed: int,
        phase: str,
    ) -> None:
        self.resource = resource
        self.scope = scope
        self.maximum = maximum
        self.observed = observed
        self.phase = phase
        super().__init__(
            f"{phase} refused {scope} {resource}: "
            f"observed {observed}, maximum {maximum}"
        )


class ProviderRejectedError(Exception):
    """A stage provider deliberately rejected parameters or payload bytes."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str:
            raise TypeError("provider rejection reason must be an exact string")
        if not reason:
            raise ValueError("provider rejection reason cannot be empty")
        self.reason = reason
        super().__init__(reason)

    @property
    def resource_limit(self) -> ResourceLimitError | None:
        """Return a structured core output ceiling when the helper supplied one."""
        return None


class SelectionError(ObstError):
    """A requested logical stream or recipe is not declared."""


class UnknownStreamError(SelectionError):
    """A requested stream ID is not declared."""

    def __init__(self, stream_id: int) -> None:
        self.stream_id = stream_id
        super().__init__(f"unknown stream id {stream_id}")


class UnknownRecipeError(SelectionError):
    """A requested recipe ID is not declared."""

    def __init__(self, recipe_id: int) -> None:
        self.recipe_id = recipe_id
        super().__init__(f"unknown recipe id {recipe_id}")


class PackagingError(ObstError):
    """Logical sources cannot be packaged under the requested policy."""


class SourceConsumedError(PackagingError):
    """A single-use logical stream source was requested more than once."""

    def __init__(self) -> None:
        super().__init__("logical stream source has already been consumed")


class InvalidContainerError(ObstError):
    """The input does not follow the OBST structural contract."""


class CorruptContainerError(InvalidContainerError):
    """The input is structurally recognizable as OBST but failed integrity checks."""


class TruncatedContainerError(CorruptContainerError):
    """The input ended before a declared structure was complete."""

    def __init__(self, structure: str, expected: int, actual: int) -> None:
        self.structure = structure
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"truncated {structure}: expected {expected} bytes, got {actual}"
        )


class UnsupportedVersionError(InvalidContainerError):
    """The OBST version is valid but unsupported by this implementation."""

    def __init__(self, structure: str, version: tuple[int, int]) -> None:
        self.structure = structure
        self.version = version
        super().__init__(f"unsupported {structure} version {version[0]}.{version[1]}")


class MissingStageError(ExtensionError):
    """A valid recipe requires a stage capability that is not installed."""

    def __init__(self, stage_id: str, *, capability: str) -> None:
        self.stage_id = stage_id
        self.capability = capability
        super().__init__(f"missing stage {capability}: {stage_id}")


class MissingExtensionCapabilityError(ExtensionError):
    """A selected runtime extension does not provide a required capability."""

    def __init__(self, extension_id: str, *, capability: str) -> None:
        self.extension_id = extension_id
        self.capability = capability
        super().__init__(f"missing extension {capability}: {extension_id}")


class PipelineError(ObstError):
    """A known pipeline stage could not encode or decode its input."""

    def __init__(
        self,
        reason: str,
        *,
        stage_id: str | None = None,
        direction: str | None = None,
        phase: str | None = None,
    ) -> None:
        if type(reason) is not str:
            raise TypeError("pipeline error reason must be an exact string")
        if not reason:
            raise ValueError("pipeline error reason cannot be empty")
        context = (stage_id, direction, phase)
        if any(value is not None for value in context) and any(
            value is None for value in context
        ):
            raise TypeError("stage_id, direction and phase must be provided together")
        self.reason = reason
        self.stage_id = stage_id
        self.direction = direction
        self.phase = phase
        message = (
            reason if stage_id is None else f"{stage_id} {direction} {phase}: {reason}"
        )
        super().__init__(message)
