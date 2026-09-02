"""Authenticated, short-lived acceptance proofs for external product candidates."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.schemas.llm_contracts import Per100Values

PROOF_TTL_SECONDS = 10 * 60


class CandidateProofError(ValueError):
    pass


def _candidate_fields(
    *,
    source: str,
    barcode: str | None,
    name: str,
    brand: str | None,
    serving_unit: str,
    per100: Per100Values,
) -> dict[str, Any]:
    return {
        "source": source,
        "barcode": barcode,
        "name": name,
        "brand": brand,
        "serving_unit": serving_unit,
        "per100": per100.model_dump(mode="json"),
    }


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_candidate_proof(
    *,
    user_id: uuid.UUID,
    source: str,
    barcode: str | None,
    name: str,
    brand: str | None,
    serving_unit: str,
    per100: Per100Values,
    now: datetime | None = None,
) -> str:
    issued_at = int(now.timestamp()) if now is not None else int(time.time())
    payload = {
        "v": 1,
        "user_id": str(user_id),
        "exp": issued_at + PROOF_TTL_SECONDS,
        **_candidate_fields(
            source=source,
            barcode=barcode,
            name=name,
            brand=brand,
            serving_unit=serving_unit,
            per100=per100,
        ),
    }
    encoded = _encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = hmac.new(
        get_settings().session_secret.encode(), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_encode(signature)}"


def verify_candidate_proof(
    proof: str,
    *,
    user_id: uuid.UUID,
    source: str,
    barcode: str | None,
    name: str,
    brand: str | None,
    serving_unit: str,
    per100: Per100Values,
    now: datetime | None = None,
) -> None:
    try:
        encoded, supplied_signature = proof.split(".", 1)
        expected_signature = hmac.new(
            get_settings().session_secret.encode(), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_decode(supplied_signature), expected_signature):
            raise CandidateProofError("candidate acceptance proof is invalid")
        payload = json.loads(_decode(encoded))
    except CandidateProofError:
        raise
    except (AttributeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise CandidateProofError("candidate acceptance proof is invalid") from exc

    current_time = int(now.timestamp()) if now is not None else int(time.time())
    if not isinstance(payload.get("exp"), int) or payload["exp"] <= current_time:
        raise CandidateProofError("candidate acceptance proof has expired")
    expected = {
        "v": 1,
        "user_id": str(user_id),
        **_candidate_fields(
            source=source,
            barcode=barcode,
            name=name,
            brand=brand,
            serving_unit=serving_unit,
            per100=per100,
        ),
    }
    actual = {key: payload.get(key) for key in expected}
    if actual != expected:
        raise CandidateProofError("candidate acceptance proof does not match this product")
