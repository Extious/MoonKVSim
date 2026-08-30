"""Pure GlobalDES policy primitives for the AegisKV branch.

This package contains no physical I/O, wall-clock reads, or implicit floating-point
conversions.  Capacity/data-plane integration is intentionally owned by later modules.
"""

from moonkvsim.aegiskv.lazy_refresh import (
    RefreshResult,
    RefreshTrigger,
    RentalEntry,
    refresh_if_stale,
)
from moonkvsim.aegiskv.rental_value import (
    RentalValue,
    RentalValueInputs,
    calculate_rental_value,
    compute_rental_value,
)
from moonkvsim.aegiskv.slack_landlord import (
    JOINT_LOSS_INTERPRETATION,
    JOINT_LOSS_REVIEW_STATUS,
    AdmissionPreview,
    MissingLatestRentalError,
    PathResolution,
    PendingAdmission,
    SlackLandlord,
    StalePreviewError,
)
from moonkvsim.aegiskv.types import (
    AdmissionOutcome,
    CanonicalFractionJSON,
    ChunkCandidate,
    PathCommitState,
    PolicyPool,
    RentalSignals,
    RentalWeights,
    SealedChunk,
    SignalVersions,
    SlackSignal,
    fraction_from_json,
    fraction_to_json,
)

__all__ = [
    "JOINT_LOSS_INTERPRETATION",
    "JOINT_LOSS_REVIEW_STATUS",
    "AdmissionOutcome",
    "AdmissionPreview",
    "CanonicalFractionJSON",
    "ChunkCandidate",
    "MissingLatestRentalError",
    "PathCommitState",
    "PathResolution",
    "PendingAdmission",
    "PolicyPool",
    "RefreshResult",
    "RefreshTrigger",
    "RentalEntry",
    "RentalSignals",
    "RentalValue",
    "RentalValueInputs",
    "RentalWeights",
    "SealedChunk",
    "SignalVersions",
    "SlackLandlord",
    "SlackSignal",
    "StalePreviewError",
    "calculate_rental_value",
    "compute_rental_value",
    "fraction_from_json",
    "fraction_to_json",
    "refresh_if_stale",
]
