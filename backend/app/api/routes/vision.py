"""Vision nutrition-label parsing.

Stateless by design (decision D2): this endpoint extracts raw values and
normalizes them to per-100g; it NEVER writes to the database. The client
renders an editable proposal card and only a subsequent POST /api/meal-logs
(with explicit user confirmation) persists anything.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_profile
from app.models import UserProfile
from app.schemas.api import VisionParseRequest
from app.schemas.llm_contracts import NutritionLabelExtraction
from app.schemas.products import ProductCandidate
from app.services.llm import get_llm
from app.services.nutrition import normalize_extraction
from app.services.product_candidates import issue_candidate_proof

router = APIRouter(prefix="/api/vision", tags=["vision"])

VISION_SYSTEM = (
    "You are a nutrition-label OCR extractor. Extract the nutrition facts "
    "table EXACTLY as printed: report the basis (per 100g or per serving) and "
    "the serving size in g/ml if shown. Copy numbers verbatim; never scale, "
    "convert units, or compute totals. If a value is not printed, use 0. "
    "Set confidence_score low when the image is blurry, angled, or partially "
    "cropped."
)


@router.post("/parse-label", response_model=ProductCandidate)
async def parse_label(
    body: VisionParseRequest,
    barcode: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    profile: UserProfile = Depends(get_current_profile),
):
    data_url = body.image_base64
    if not data_url.startswith("data:"):
        data_url = "data:image/jpeg;base64," + data_url

    llm = get_llm("vision")
    extraction = await llm.extract_json(
        system=VISION_SYSTEM,
        prompt="Extract the nutrition facts from this label image.",
        schema=NutritionLabelExtraction,
        image_data_urls=[data_url],
    )
    per100 = normalize_extraction(extraction)
    issues = []
    if extraction.product_name is None:
        issues.append("missing_name")
    for field, issue in (
        ("calories", "missing_calories"),
        ("protein_g", "missing_protein"),
        ("carbs_g", "missing_carbs"),
        ("fat_g", "missing_fat"),
        ("fiber_g", "missing_fiber"),
    ):
        if getattr(extraction, field) == 0:
            issues.append(issue)
    retrieved_at = datetime.now(timezone.utc)
    name = extraction.product_name or (f"Barcode {barcode}" if barcode else "Unidentified product")
    candidate = ProductCandidate(
        source="vision_label",
        barcode=barcode,
        name=name,
        per100=per100,
        retrieved_at=retrieved_at,
        confidence_score=extraction.confidence_score,
        issues=issues,
        acceptance_proof="pending",
    )
    candidate.acceptance_proof = issue_candidate_proof(
        user_id=profile.id,
        source=candidate.source,
        barcode=candidate.barcode,
        name=candidate.name,
        brand=candidate.brand,
        serving_unit=candidate.serving_unit,
        per100=candidate.per100,
        now=retrieved_at,
    )
    return candidate
