"""The admin dashboard: approval queue, activity log, and ROI metrics.

Split in two, like the rest of AAAAS:

  * ``service`` — a stdlib-only layer (``DashboardService`` + ``DashboardHITL``)
    that holds the approval queue, records activity, and computes metrics. Fully
    unit-testable with no web framework.
  * ``web``     — a thin FastAPI veneer (lazy-imported) exposing that service as
    a JSON API plus a single self-contained HTML page.
"""
from .service import (
    Activity,
    DashboardHITL,
    DashboardService,
    PendingApproval,
)

__all__ = [
    "Activity",
    "DashboardHITL",
    "DashboardService",
    "PendingApproval",
]
