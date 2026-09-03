import pytest

from app.schemas.llm_contracts import NutritionLabelExtraction, Per100Values
from app.services.nutrition import (
    normalize_extraction,
    scale_to_quantity,
    suggested_quantity_g,
    sum_totals,
)


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

    def test_impossible_normalized_density_is_rejected_before_arithmetic(self):
        with pytest.raises(ValueError):
            make_extraction(
                basis="per_serving",
                serving_size_g=1,
                calories=120,
            )


class TestSuggestedQuantity:
    def test_uses_printed_net_package_quantity(self):
        extraction = make_extraction(net_quantity=125, net_quantity_unit="g")
        assert suggested_quantity_g(extraction) == 125

    def test_converts_large_units_in_application_code(self):
        extraction = make_extraction(net_quantity=0.5, net_quantity_unit="kg")
        assert suggested_quantity_g(extraction) == 500

    def test_falls_back_to_printed_serving_size(self):
        extraction = make_extraction(serving_size_g=150)
        assert suggested_quantity_g(extraction) == 150

    def test_rejects_net_unit_that_does_not_match_reference_density(self):
        with pytest.raises(ValueError, match="must match"):
            make_extraction(reference_unit="g", net_quantity=1, net_quantity_unit="l")

    def test_rejects_net_quantity_over_proposal_limit_after_conversion(self):
        with pytest.raises(ValueError, match="exceeds 10000"):
            make_extraction(net_quantity=11, net_quantity_unit="kg")

    @pytest.mark.parametrize(
        "values",
        [
            {"net_quantity": 0.001, "net_quantity_unit": "g"},
            {"serving_size_g": 0.001},
        ],
    )
    def test_rejects_quantity_that_rounds_to_zero(self, values):
        with pytest.raises(ValueError, match="too small"):
            make_extraction(**values)


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

    @pytest.mark.parametrize(
        ("calories", "quantity", "expected"),
        [
            (209.0, 5.0, 10.5),
            (45.0, 5.0, 2.3),
            (1.0, 5.0, 0.1),
        ],
    )
    def test_positive_half_ties_round_up(self, calories, quantity, expected):
        totals = scale_to_quantity(
            Per100Values(
                calories=calories,
                protein_g=0,
                carbs_g=0,
                fat_g=0,
            ),
            quantity,
        )
        assert totals["calories"] == expected


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
