"""Contract generator preserves legacy types and quotes new forward roots."""
from __future__ import annotations

from typing import ForwardRef, get_type_hints

import generate_product_contracts as codegen
from princess_contracts.generated import (
    PremiumReadingPacket, ReadingSupport, RenderEnvelope, ReportViewModel,
)


def test_new_reading_support_forward_ref_resolves_under_supported_python():
    annotation = PremiumReadingPacket.__annotations__["support"]
    assert isinstance(annotation, ForwardRef)
    assert get_type_hints(PremiumReadingPacket)["support"] is ReadingSupport
    assert isinstance(RenderEnvelope.__annotations__["view"], ForwardRef)
    assert get_type_hints(RenderEnvelope)["view"] is ReportViewModel


def test_reproducible_codegen_includes_the_verified_forward_reference():
    rendered = codegen.build()[codegen.PY_OUT]
    assert "'support': 'ReadingSupport'" in rendered
    assert "'support': ReadingSupport" not in rendered
    assert "'view': 'ReportViewModel'" in rendered
    assert "'view': ReportViewModel" not in rendered
    assert rendered == codegen.PY_OUT.read_text(encoding="utf-8")
