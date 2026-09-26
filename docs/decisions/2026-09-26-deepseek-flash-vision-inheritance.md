# Use DeepSeek Flash for Text and Label Vision

**Occurred:** 2026-09-10 (DeepSeek model change)

**Verified:** 2026-09-26 (Europe/Lisbon; production browser test)

**Documented:** 2026-09-26T01:11:00+01:00

**Status:** Accepted locally; deployment pending

**Decision:** D54

## Context

The Settings preset and agent guidance treated DeepSeek's text and vision models
as separate. DeepSeek's current [Vision guide](https://api-docs.deepseek.com/guides/vision/)
states that `deepseek-flash` accepts images and that the older vision model name
is a retired compatibility alias. Its [2026-09-10 change log](https://api-docs.deepseek.com/updates/)
records the multimodal Flash release.

The deployed PlateOS Settings page showed vision inheriting the Coach's
`https://api.deepseek.com/` endpoint and `deepseek-flash` model. In an
authenticated production browser session, an uploaded Portuguese label with a
25 g serving produced the printed 141 kcal, 1.6 g protein, 12 g carbohydrates,
9.7 g fat, and 0.6 g fiber as 564 kcal, 6.4 g protein, 48 g carbohydrates,
38.8 g fat, and 2.4 g fiber per 100 g. The candidate had no product name and
suggested 25 g. A one-time Proposal Card showed 141 kcal at 25 g and 197 kcal
at 35 g. It was dismissed; Today remained empty. The Coach also returned a
reviewable meal draft which was dismissed without logging.

## Decision

Use `deepseek-flash` for both DeepSeek preset tasks. Permit vision to inherit
the text provider. Remove the blanket warning that DeepSeek text models cannot
read images; keep the notice that label photos go to the configured hosted
provider. Normalize a trailing slash when matching provider URLs in Settings.
Keep separate vision configuration for independent model and privacy choices.

## Alternatives considered

- Keep separate DeepSeek vision by default: unnecessary for the now multimodal
  Flash model and contradicted by the production round-trip.
- Keep legacy preset model names: the provider currently routes them to Flash,
  but a new preset should name the current model directly.

## Consequences and limits

- Existing saved provider settings are not rewritten. No production setting,
  product, or meal was changed by this decision.
- Label extraction quality was verified for one supplied image only. Physical
  iPhone camera capture, poor-quality image recovery, and other providers remain
  separate tests.
- The frontend preset and warning changes are local and undeployed. The live
  result was observed on the existing production release `539d17b`.
