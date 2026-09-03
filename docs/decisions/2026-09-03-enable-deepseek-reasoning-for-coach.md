# Enable DeepSeek Reasoning for Coach

**Date:** 2026-09-03T03:00:00+01:00

**Status:** Accepted and implemented

**Decision:** D50, superseding D49 for coach contract calls

## Context

D49 disabled DeepSeek's default thinking mode after production requests consumed
the 2,000-token completion allowance in reasoning and returned no final JSON.
That restored reliability, but the operator prefers reasoning for higher-quality
coach advice. PlateOS still requires a validated final JSON contract and must not
persist or expose chain-of-thought content.

## Decision

Official `api.deepseek.com` text-task calls explicitly enable thinking at high
effort. The first contract attempt receives a 16,000-token completion allowance;
the existing single corrective retry receives 32,000. If an attempt contains no
final content, PlateOS retries without appending an empty assistant turn. Only
`message.content` is validated and persisted; `reasoning_content` is ignored.

Official DeepSeek vision extraction and connection probes keep thinking disabled.
They are deterministic OCR/connectivity tasks rather than advisory reasoning.
Other providers and custom OpenAI-compatible endpoints receive no DeepSeek-only
parameters.

While the non-streaming provider call runs, the SSE endpoint emits bounded,
mode-specific progress descriptions written by PlateOS. These describe the
application's intended review stages and keep the connection active; they are not
DeepSeek chain of thought. Disconnect cleanup cancels and awaits the provider task
before the request-scoped database session can close.

## Consequences

- Coach answers can benefit from DeepSeek reasoning while retaining the strict
  assistant block boundary.
- Typical coach calls may cost more and take longer than non-thinking calls.
- A reasoning-heavy first attempt can recover with a larger bounded retry rather
  than failing with empty content.
- Provider chain of thought is neither sent to clients nor stored in chat data.
- Users receive meaningful progress feedback without exposing private or
  potentially unsafe intermediate model reasoning.
