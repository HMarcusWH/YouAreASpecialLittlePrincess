"""Additive R1 reading contracts fail closed without activating Premium."""
from __future__ import annotations

import copy

from princess_contracts import canonical_digest, compile_document


def synthetic_support():
    descriptors = [
        {
            "descriptor_id": "descriptor.slant.mixed",
            "source_candidate_id": "slant.mixed",
            "family": "slant",
            "correlation_group": "slant.direction",
            "content_id": "content.highlight.v2.slant.mixed",
            "support_fact_ids": ["fact.SLANT_LEFT_FRACTION"],
            "support_region_ids": [],
        },
        {
            "descriptor_id": "descriptor.spacing.words_consistent",
            "source_candidate_id": "spacing.words_consistent",
            "family": "spacing",
            "correlation_group": "spacing.word_variation",
            "content_id": "content.highlight.v2.spacing.words_consistent",
            "support_fact_ids": ["fact.WORD_SPACING_CV"],
            "support_region_ids": [],
        },
    ]
    support = {
        "contract_version": "1.0.0",
        "support_version": "reading-support/1",
        "report_id": "synthetic_report",
        "report_revision": 1,
        "report_digest": "a" * 64,
        "evidence_digest": None,
        "image_sha256": "b" * 64,
        "descriptors": descriptors,
        "relations": [{
            "relation_id": "relation.space_direction_contrast",
            "relation_kind": "CONTRAST",
            "descriptor_ids": [
                "descriptor.slant.mixed", "descriptor.spacing.words_consistent",
            ],
            "support_fact_ids": [
                "fact.SLANT_LEFT_FRACTION", "fact.WORD_SPACING_CV",
            ],
            "support_region_ids": [],
            "claim_key": "content.relation.v1.space_direction_contrast",
        }],
        "regions": [],
        "support_digest": None,
    }
    support["support_digest"] = canonical_digest(support)
    return support


def codes(result):
    return {issue.code for issue in result.issues}


def test_synthetic_support_preserves_one_fact_bound_cross_family_relation():
    s = synthetic_support()
    compiled = compile_document("ReadingSupport", s)
    assert compiled.ok, compiled.issues
    assert compiled.value.to_dict() == s


def test_support_detects_unknown_relation_member_and_forged_union():
    s = synthetic_support()
    s["relations"][0]["descriptor_ids"][1] = "descriptor.foreign"
    s["support_digest"] = None
    s["support_digest"] = canonical_digest(s)
    assert "READING_FOREIGN_DESCRIPTOR" in codes(compile_document("ReadingSupport", s))

    s = synthetic_support()
    s["relations"][0]["support_fact_ids"] = ["fact.OTHER", "fact.UNRELATED"]
    s["support_digest"] = None
    s["support_digest"] = canonical_digest(s)
    assert "READING_RELATION_FACT_MISMATCH" in codes(
        compile_document("ReadingSupport", s)
    )


def test_support_digest_cannot_be_rotated_without_detecting_mutation():
    s = synthetic_support()
    s["image_sha256"] = "c" * 64
    assert "READING_SUPPORT_DIGEST_MISMATCH" in codes(
        compile_document("ReadingSupport", s)
    )


def test_disabled_offer_cannot_advertise_new_purchase_or_generation():
    offer = {
        "contract_version": "1.0.0",
        "offer_version": "premium-offer/1",
        "source_report_id": "synthetic_report",
        "source_revision": 1,
        "source_digest": "a" * 64,
        "sample_state": "SUPPORTED",
        "source_image_state": "AVAILABLE",
        "support_state": "SUFFICIENT",
        "runtime_state": "DISABLED",
        "permission_state": "NOT_GRANTED",
        "entitlement_state": "NONE",
        "job_state": "NONE",
        "action": "NONE",
        "reason": "premium_not_available",
        "catalog_product_id": None,
    }
    assert compile_document("PremiumOffer", offer).ok
    for action in ("PURCHASE", "GENERATE", "RETRY"):
        proposal = copy.deepcopy(offer)
        proposal["action"] = action
        assert "READING_UNAVAILABLE_ACTION" in codes(
            compile_document("PremiumOffer", proposal)
        )


def test_published_revision_must_be_later_than_source_basis():
    view = {
        "contract_version": "1.0.0",
        "view_version": "premium-reading-view/2",
        "source_report_id": "synthetic_report",
        "source_revision": 2,
        "source_digest": "b" * 64,
        "overlay_id": "synthetic_overlay",
        "overlay_digest": "c" * 64,
        "locale": "en",
        "blocks": [],
        "reflection_content_id": None,
        "basis_revision": 1,
        "basis_digest": "a" * 64,
    }
    assert compile_document("PremiumReadingView", view).ok
    for nonadjacent_revision in (2, 3):
        altered = copy.deepcopy(view)
        altered["source_revision"] = nonadjacent_revision + 1
        assert "READING_BASIS_REVISION_MISMATCH" in codes(
            compile_document("PremiumReadingView", altered)
        )
    view["basis_revision"] = 2
    assert "READING_BASIS_REVISION_MISMATCH" in codes(
        compile_document("PremiumReadingView", view)
    )


def test_relation_min_items_is_a_separate_structural_guard():
    s = synthetic_support()
    s["relations"][0]["support_fact_ids"] = ["fact.OTHER"]
    s["support_digest"] = None
    s["support_digest"] = canonical_digest(s)
    assert "MIN_ITEMS" in codes(compile_document("ReadingSupport", s))
