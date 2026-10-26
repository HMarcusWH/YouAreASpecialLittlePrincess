"""Additive R1 reading contracts fail closed without activating Premium."""
from __future__ import annotations

import copy
import json
from pathlib import Path

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


FIXTURES = Path(__file__).resolve().parents[1] / "contracts/product/v1/fixtures/valid"


def redigest(support):
    support["support_digest"] = None
    support["support_digest"] = canonical_digest(support)
    return support


def reading_packet():
    base = json.loads((FIXTURES / "premium-packet.json").read_text(encoding="utf-8"))
    support = synthetic_support()
    support["report_id"] = base["report_id"]
    support["report_revision"] = base["report_revision"]
    support["report_digest"] = base["report_digest"]
    redigest(support)
    facts = ["fact.SLANT_LEFT_FRACTION", "fact.WORD_SPACING_CV"]
    base["allowed_fact_ids"].extend(facts)
    return {
        "contract_version": "1.0.0",
        "packet_id": base["packet_id"],
        "reading_pack_version": "premium-reading/2",
        "output_schema_version": "premium-reading-output/2",
        "policy_manifest_sha256": "c" * 64,
        "selector_packet": base,
        "support": support,
        "block_specs": [
            {
                "block_id": "block.portrait",
                "kind": "PORTRAIT",
                "scope": "WHOLE_SAMPLE",
                "question_id": None,
                "allowed_candidate_ids": [
                    "descriptor.slant.mixed",
                    "descriptor.spacing.words_consistent",
                ],
                "allowed_fact_ids": facts,
                "allowed_region_refs": [],
                "max_characters": 500,
                "max_sentences": 3,
            },
            {
                "block_id": "block.relation",
                "kind": "RELATIONSHIP",
                "scope": "WHOLE_SAMPLE",
                "question_id": None,
                "allowed_candidate_ids": ["relation.space_direction_contrast"],
                "allowed_fact_ids": facts,
                "allowed_region_refs": [],
                "max_characters": 350,
                "max_sentences": 3,
            },
            {
                "block_id": "block.visual",
                "kind": "VISUAL_OBSERVATION",
                "scope": "WHOLE_SAMPLE",
                "question_id": "Q_CTX_TASK",
                "allowed_candidate_ids": ["candidate_task_copy"],
                "allowed_fact_ids": ["fact_img_width"],
                "allowed_region_refs": [],
                "max_characters": 280,
                "max_sentences": 2,
            },
        ],
    }


def test_reading_packet_binds_portrait_relation_and_visual_to_actual_support():
    packet = reading_packet()
    result = compile_document("PremiumReadingPacket", packet)
    assert result.ok, result.issues


def test_reading_packet_rejects_unsupported_but_base_allowlisted_editorial_fact():
    packet = reading_packet()
    packet["block_specs"][0]["allowed_fact_ids"][0] = "fact_img_width"
    assert "READING_BLOCK_FACT_ESCAPE" in codes(
        compile_document("PremiumReadingPacket", packet)
    )


def test_reading_packet_rejects_foreign_candidates_missing_families_and_regions():
    packet = reading_packet()
    packet["block_specs"][1]["allowed_candidate_ids"] = ["descriptor.slant.mixed"]
    assert "READING_BLOCK_CANDIDATE_ESCAPE" in codes(
        compile_document("PremiumReadingPacket", packet)
    )
    packet = reading_packet()
    packet["block_specs"][0]["allowed_candidate_ids"] = ["descriptor.slant.mixed"]
    assert "READING_PORTRAIT_FAMILY_COVERAGE" in codes(
        compile_document("PremiumReadingPacket", packet)
    )
    packet = reading_packet()
    packet["block_specs"][2]["scope"] = "LOCAL"
    assert "READING_LOCAL_REGION_MISSING" in codes(
        compile_document("PremiumReadingPacket", packet)
    )


def test_reading_packet_rejects_oversized_editorial_budget_and_missing_required_block():
    packet = reading_packet()
    packet["block_specs"][1]["max_characters"] = 400
    assert "READING_BLOCK_LIMIT_DRIFT" in codes(
        compile_document("PremiumReadingPacket", packet)
    )
    packet = reading_packet()
    packet["block_specs"][1]["kind"] = "QUALIFIER"
    assert "READING_BLOCK_COUNT" in codes(
        compile_document("PremiumReadingPacket", packet)
    )


def test_descriptor_alias_foreign_fact_and_unknown_region_fail_closed():
    s = synthetic_support()
    s["descriptors"][1]["source_candidate_id"] = "slant.mixed"
    assert "READING_DUPLICATE_SOURCE_CANDIDATE" in codes(
        compile_document("ReadingSupport", redigest(s))
    )
    s = synthetic_support()
    s["descriptors"][1]["support_fact_ids"] = ["fact.UNAUTHORIZED_FEATURE"]
    assert "READING_UNKNOWN_FEATURE" in codes(
        compile_document("ReadingSupport", redigest(s))
    )
    s = synthetic_support()
    s["descriptors"][0]["support_region_ids"] = ["region.not_approved"]
    assert "READING_FOREIGN_REGION" in codes(
        compile_document("ReadingSupport", redigest(s))
    )


def sample_region():
    return {
        "region_ref": "region.synthetic",
        "source_region_id": "source.synthetic",
        "frame_id": "frame.synthetic",
        "scope": "LINE",
        "polygon_normalized_input": [
            {"x": 0.1, "y": 0.1},
            {"x": 0.4, "y": 0.1},
            {"x": 0.4, "y": 0.3},
            {"x": 0.1, "y": 0.3},
        ],
    }


def test_mapped_regions_reject_collinear_self_crossed_and_duplicate_points():
    s = synthetic_support()
    s["regions"] = [sample_region()]
    assert compile_document("ReadingSupport", redigest(s)).ok
    for polygon in (
        [{"x": 0.1 * i, "y": 0.1 * i} for i in (1, 2, 3, 4)],
        [
            {"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.3},
            {"x": 0.4, "y": 0.1}, {"x": 0.1, "y": 0.3},
        ],
        [
            {"x": 0.1, "y": 0.1}, {"x": 0.1, "y": 0.1},
            {"x": 0.4, "y": 0.3}, {"x": 0.1, "y": 0.3},
        ],
    ):
        invalid = copy.deepcopy(s)
        invalid["regions"][0]["polygon_normalized_input"] = polygon
        assert "READING_REGION_GEOMETRY" in codes(
            compile_document("ReadingSupport", redigest(invalid))
        )


def test_offer_refuses_removed_image_even_if_consent_and_credits_exist():
    offer = {
        "contract_version": "1.0.0", "offer_version": "premium-offer/1",
        "source_report_id": "synthetic_report", "source_revision": 1,
        "source_digest": "a" * 64,
        "sample_state": "SUPPORTED", "source_image_state": "UNAVAILABLE",
        "support_state": "SUFFICIENT", "runtime_state": "AVAILABLE",
        "permission_state": "GRANTED", "entitlement_state": "CREDIT",
        "job_state": "NONE", "action": "GENERATE",
        "reason": None, "catalog_product_id": None,
    }
    assert "READING_UNAVAILABLE_ACTION" in codes(compile_document("PremiumOffer", offer))
