"""Vision nutrition-label parsing.

Stateless by design (decision D2): this endpoint extracts raw values and
normalizes them to per-100g; it NEVER writes to the database. The client
renders an editable proposal card and only a subsequent POST /api/meal-logs
(with explicit user confirmation) persists anything.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_profile
from app.models import UserProfile
from app.schemas.api import VisionParseRequest, VisionParseResponse
from app.schemas.llm_contracts import NutritionLabelExtraction
from app.services.llm import get_llm
from app.services.nutrition import normalize_extraction

router = APIRouter(prefix="/api/vision", tags=["vision"])

VISION_SYSTEM = (
    "You are a nutrition-label OCR extractor. Extract the nutrition facts "
    "table EXACTLY as printed: report the basis (per 100g or per serving) and "
    "the serving size in g/ml if shown. Copy numbers verbatim; never scale, "
    "convert units, or compute totals. If a value is not printed, use 0. "
    "Set confidence_score low when the image is blurry, angled, or partially "
    "cropped."
)


@router.post("/parse-label", response_model=VisionParseResponse)
async def parse_label(
    body: VisionParseRequest,
    _profile: UserProfile = Depends(get_current_profile),
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
    return VisionParseResponse(
        product_name=extraction.product_name,
        per100=per100,
        confidence_score=extraction.confidence_score,
    )
