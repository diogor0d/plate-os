"""Build compact PlateOS catalogues from official Ciqual and Swedish releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

CIQUAL_NUTRIENTS = {
    "328": "calories",
    "25003": "protein_g",
    "31000": "carbs_g",
    "40000": "fat_g",
    "34100": "fiber_g",
}
SWEDISH_COLUMNS = {
    "Energi (kcal)": "calories",
    "Protein (g)": "protein_g",
    "Kolhydrater, tillgängliga (g)": "carbs_g",
    "Fett, totalt (g)": "fat_g",
    "Fiber (g)": "fiber_g",
}
XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
PINNED_SHA256 = {
    "ciqual_foods": "e0b1de25b3039028205e9d54a96892e403e1b313c2efeb41180fabe132627478",
    "ciqual_composition": "8c46a9032ece4eab4ffccc9dfcb0c490ec2f416aa664cc1ee013b241c6bdd4af",
    "swedish_xlsx": "568428a7ef219d2ab0e3ddc6bc9b83dcd39b9e40335f298c1461fbf65374fa4d",
    "swedish_english_names": "04d8defa3d37411cedfd07b26d453e50a5833e875946c9d78ac502558cdb0417",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_pinned_input(path: Path, key: str) -> str:
    actual = _sha256(path)
    if actual != PINNED_SHA256[key]:
        raise ValueError(
            f"{path} does not match pinned {key} input: expected {PINNED_SHA256[key]}, got {actual}"
        )
    return actual


def _text(element: ElementTree.Element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _exact_number(raw: str) -> float | None:
    value = raw.strip().replace(",", ".")
    if not value or value == "-" or value.lower() == "traces" or value.startswith("<"):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0:
        return None
    return float(number)


def _write_catalog(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _fits_plateos(values: dict[str, float | None]) -> bool:
    return (
        all(value is not None for value in values.values())
        and values["calories"] <= 1000
        and all(values[field] <= 100 for field in ("protein_g", "carbs_g", "fat_g", "fiber_g"))
    )


def generate_ciqual(foods_path: Path, composition_path: Path, output_path: Path) -> None:
    foods_sha256 = _require_pinned_input(foods_path, "ciqual_foods")
    composition_sha256 = _require_pinned_input(composition_path, "ciqual_composition")
    foods: dict[str, tuple[str, str]] = {}
    for _event, element in ElementTree.iterparse(foods_path, events=("end",)):
        if element.tag != "ALIM":
            continue
        code = _text(element, "alim_code")
        french_name = _text(element, "alim_nom_fr")
        english_name = _text(element, "alim_nom_eng")
        if code and (english_name or french_name):
            foods[code] = (english_name or french_name, french_name)
        element.clear()

    nutrients: dict[str, dict[str, float]] = {}
    for _event, element in ElementTree.iterparse(composition_path, events=("end",)):
        if element.tag != "COMPO":
            continue
        nutrient = CIQUAL_NUTRIENTS.get(_text(element, "const_code"))
        if nutrient:
            value = _exact_number(_text(element, "teneur"))
            if value is not None:
                nutrients.setdefault(_text(element, "alim_code"), {})[nutrient] = value
        element.clear()

    records = []
    for code, (name, alternate_name) in foods.items():
        values = nutrients.get(code, {})
        if values.keys() >= set(CIQUAL_NUTRIENTS.values()) and _fits_plateos(values):
            records.append({
                "id": code,
                "name": name,
                "alternate_name": alternate_name if alternate_name != name else None,
                **values,
            })
    records.sort(key=lambda record: (str(record["name"]).casefold(), str(record["id"])))
    _write_catalog(output_path, {
        "source": "ciqual",
        "version": "2025-11-19",
        "attribution": "Anses. 2025. Table de composition nutritionnelle des aliments Ciqual 2025.",
        "license": "Licence Ouverte / Etalab 2.0",
        "license_url": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
        "source_url": "https://doi.org/10.57745/RDMHWY",
        "upstream_sha256": {
            "foods_xml": foods_sha256,
            "composition_xml": composition_sha256,
        },
        "foods": records,
    })


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(f"{XML_NS}t")) for item in root]


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if letters is None:
        raise ValueError(f"Invalid spreadsheet cell reference: {reference}")
    value = 0
    for character in letters.group(0):
        value = value * 26 + ord(character) - ord("A") + 1
    return value - 1


def _xlsx_rows(path: Path) -> tuple[str, Iterator[list[str]]]:
    archive = zipfile.ZipFile(path)
    strings = _shared_strings(archive)
    sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    def rows() -> Iterator[list[str]]:
        try:
            for row in sheet.iter(f"{XML_NS}row"):
                values: list[str] = []
                for cell in row.findall(f"{XML_NS}c"):
                    index = _column_index(cell.attrib["r"])
                    while len(values) <= index:
                        values.append("")
                    raw = _text(cell, f"{XML_NS}v")
                    values[index] = strings[int(raw)] if cell.attrib.get("t") == "s" and raw else raw
                yield values
        finally:
            archive.close()

    version = strings[0] if strings else ""
    return version, rows()


def generate_swedish(xlsx_path: Path, english_names_path: Path, output_path: Path) -> None:
    xlsx_sha256 = _require_pinned_input(xlsx_path, "swedish_xlsx")
    english_names_sha256 = _require_pinned_input(
        english_names_path, "swedish_english_names"
    )
    english_payload = json.loads(english_names_path.read_text(encoding="utf-8"))
    english_names = {
        str(item["nummer"]): str(item["namn"]).strip()
        for item in english_payload["livsmedel"]
        if item.get("namn")
    }
    version_label, rows = _xlsx_rows(xlsx_path)
    iterator = iter(rows)
    next(iterator)
    next(iterator)
    headers = next(iterator)
    indexes = {header: index for index, header in enumerate(headers)}
    required = {"Livsmedelsnamn", "Livsmedelsnummer", *SWEDISH_COLUMNS}
    if not required.issubset(indexes):
        raise ValueError(f"Swedish workbook lacks columns: {sorted(required - indexes.keys())}")

    records = []
    for row in iterator:
        identifier = row[indexes["Livsmedelsnummer"]].strip()
        swedish_name = row[indexes["Livsmedelsnamn"]].strip()
        if not identifier or not swedish_name:
            continue
        values = {
            field: _exact_number(row[indexes[column]])
            for column, field in SWEDISH_COLUMNS.items()
        }
        if not _fits_plateos(values):
            continue
        name = english_names.get(identifier, swedish_name)
        records.append({
            "id": identifier,
            "name": name,
            "alternate_name": swedish_name if swedish_name != name else None,
            **values,
        })
    records.sort(key=lambda record: (str(record["name"]).casefold(), str(record["id"])))
    version_match = re.search(r"(\d{4}-\d{2}-\d{2})", version_label)
    if version_match is None:
        raise ValueError(f"Could not parse Swedish dataset version from {version_label!r}")
    version = version_match.group(1)
    if version != "2026-07-01":
        raise ValueError(f"Expected Swedish dataset version 2026-07-01, got {version}")
    _write_catalog(output_path, {
        "source": "swedish_food_agency",
        "version": version,
        "attribution": f"Livsmedelsverkets Livsmedelsdatabas version {version}",
        "license": "Creative Commons Attribution 4.0 International",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_url": "https://soknaringsinnehall.livsmedelsverket.se/",
        "upstream_sha256": {
            "xlsx": xlsx_sha256,
            "english_names_json": english_names_sha256,
        },
        "foods": records,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ciqual-foods", type=Path, required=True)
    parser.add_argument("--ciqual-composition", type=Path, required=True)
    parser.add_argument("--swedish-xlsx", type=Path, required=True)
    parser.add_argument("--swedish-english-names", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    generate_ciqual(
        args.ciqual_foods,
        args.ciqual_composition,
        args.output_dir / "ciqual-2025.json",
    )
    generate_swedish(
        args.swedish_xlsx,
        args.swedish_english_names,
        args.output_dir / "swedish-food-agency-2026-07-01.json",
    )


if __name__ == "__main__":
    main()
