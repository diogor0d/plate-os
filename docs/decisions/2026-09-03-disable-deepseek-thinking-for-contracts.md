# Disable DeepSeek Thinking for Contract Calls

**Date:** 2026-09-03T02:31:00+01:00

**Status:** Accepted and implemented

**Decision:** D49

## Context

Production calls to the official `deepseek-v4-flash` model returned HTTP success
but an empty `message.content`. The connection test incorrectly displayed this
as a successful result, and assistant JSON validation retried the empty value
before failing.

DeepSeek's official API documentation states that thinking mode is enabled by
default and returns chain-of-thought separately in `reasoning_content`. Generated
reasoning and final output share the completion budget. PlateOS needs a bounded,
validated JSON contract rather than provider reasoning. A production-safe probe
confirmed that `thinking: disabled` returned `OK` with no reasoning tokens.

## Decision

When and only when the resolved endpoint hostname is `api.deepseek.com` and the
model starts with `deepseek-`, PlateOS sends DeepSeek's OpenAI-compatible
`extra_body={"thinking":{"type":"disabled"}}` option for structured extraction
and connection probes. Other providers and custom endpoints receive no extra
parameter. The probe allowance increases from 5 to 32 tokens.

An empty probe is a failed connection test rather than a successful test with a
warning message.

## Consequences

- Coach and vision contract calls use their output budget for final JSON.
- DeepSeek responses remain locally validated with one corrective retry.
- Ollama models named after DeepSeek are not assumed to support hosted API
  extensions.
- The Settings screen no longer reports an empty provider response as healthy.
