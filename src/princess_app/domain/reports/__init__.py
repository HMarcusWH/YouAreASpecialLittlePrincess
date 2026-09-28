"""Immutable report snapshots and their authorized projections (T09)."""
from .assembly import assemble_report, check_revision, facts_from_result, revise_report
from .projection import PremiumAccess, PremiumAuthorization, ProjectionRequest, project_report
from .template import BASE_TEMPLATE_VERSION, HIGHLIGHT_TEMPLATE_VERSION, TEMPLATE_VERSION

__all__ = ["BASE_TEMPLATE_VERSION", "HIGHLIGHT_TEMPLATE_VERSION", "PremiumAccess", "PremiumAuthorization",
           "ProjectionRequest", "TEMPLATE_VERSION", "assemble_report",
           "check_revision", "facts_from_result", "project_report", "revise_report"]
