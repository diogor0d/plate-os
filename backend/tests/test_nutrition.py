import pytest

from app.schemas.llm_contracts import NutritionLabelExtraction, Per100Values
from app.services.nutrition import normalize_extraction, scale_to_quantity, sum_totals


def make_extraction(**overrides) -> NutritionLabelExtraction:
    defaults = dict(
        product_name="Test product",
        basis="per_100g",
        serving_size_g=None,
        calories=250.0,
        protein_g=10.0,
        carbs_g=30.0,
        fat_g=8.0,
        fiber_g=4.0,
        confidence_score=0.9,
    )
    defaults.update(overrides)
    return NutritionLabelExtraction(**defaults)


class TestNormalizeExtraction:
    def test_per_100g_passthrough(self):
        per100 = normalize_extraction(make_extraction())
        assert per100.calories == 250.0
        assert per100.protein_g == 10.0

    def test_per_serving_converted(self):
        per100 = normalize_extraction(
            make_extraction(basis="per_serving", serving_size_g=30.0, calories=120.0)
        )
        assert per100.calories == pytest.approx(400.0)

    def test_per_serving_without_serving_size_raises(self):
        with pytest.raises(ValueError):
            normalize_extraction(make_extraction(basis="per_serving", serving_size_g=None))


class TestScaleToQuantity:
    def test_doubles_at_200g(self):
        totals = scale_to_quantity(
            Per100Values(calories=250, protein_g=10, carbs_g=30, fat_g=8, fiber_g=4), 200.0
        )
        assert totals == {
            "calories": 500.0,
            "protein_g": 20.0,
            "carbs_g": 60.0,
            "fat_g": 16.0,
            "fiber_g": 8.0,
        }

    def test_rounding_to_one_decimal(self):
        totals = scale_to_quantity(
            Per100Values(calories=113.0, protein_g=7.3, carbs_g=0.5, fat_g=9.8), 37.0
        )
        assert all(abs(v - round(v, 1)) < 1e-9 for v in totals.values())
        assert totals["calories"] == 41.8


class TestTotals:
    def test_sum_totals(self):
        a = {"calories": 100.0, "protein_g": 5.0, "carbs_g": 10.0, "fat_g": 2.0, "fiber_g": 1.0}
        b = {"calories": 50.05, "protein_g": 2.5, "carbs_g": 0.0, "fat_g": 4.0, "fiber_g": 0.0}
        assert sum_totals([a, b])["calories"] == 150.1
        assert sum_totals([]) == {
            "calories": 0.0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
            "fiber_g": 0.0,
        }
