"""AI provider abstraction and fallback orchestration.

This package defines a provider-agnostic interface (:mod:`app.ai.base`), a
prompt builder / response parser (:mod:`app.ai.prompt`), concrete provider
implementations (:mod:`app.ai.providers`), and an orchestrator
(:mod:`app.ai.orchestrator`) that iterates a configurable fallback chain.

Every AI-generated SQL suggestion is re-validated by the deterministic
SQLGlot validator before it is marked valid. Provider credentials are read
from settings / IAM only and are never serialized to clients or logged.
"""
