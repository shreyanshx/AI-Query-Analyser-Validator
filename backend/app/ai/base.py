"""Provider-agnostic AI abstraction.

Every provider implements :class:`AIProvider` and returns the single normalized
:class:`AISuggestion` shape regardless of the underlying API. The exception
hierarchy encodes the one rule the orchestrator cares about:

* :class:`ProviderUnavailable` means "try the next provider" - it is raised for
  transient conditions (timeout, HTTP 5xx, 429/quota, model-unavailable).
* :class:`ProviderRefusal` and :class:`ProviderError` do **not** trigger
  fallback. A safety refusal is a deliberate decision by the model and must be
  surfaced, not retried against another provider; a malformed response is a bug
  that masking by fallback would hide.

Provider credentials live in settings / the IAM role only. They are never
placed on an :class:`AISuggestion` and never logged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from app.ai.prompt import PromptContext
from app.config import Settings


class AISuggestion(BaseModel):
    """Normalized AI optimization suggestion.

    This is the single internal shape all providers map their responses to.
    It never contains credentials or raw provider payloads beyond the optional
    human-readable ``raw_notes``.
    """

    suggested_sql: str
    explanation: str = ""
    optimizations: list[str] = Field(default_factory=list)
    provider: str = ""
    raw_notes: str | None = None


class AIProviderException(Exception):
    """Base class for all AI provider errors."""


class ProviderUnavailable(AIProviderException):
    """Transient failure that SHOULD trigger fallback to the next provider.

    Raised for timeouts, HTTP 5xx, 429 / quota exhaustion, and
    model-unavailable conditions.
    """


class ProviderRefusal(AIProviderException):
    """The model declined to answer (e.g. a safety refusal).

    This is a deliberate decision and must NOT trigger fallback: trying another
    provider would be an attempt to route around a safety decision.
    """


class ProviderError(AIProviderException):
    """A non-transient provider error (e.g. malformed response, 4xx bug).

    This does NOT trigger fallback; masking it behind another provider would
    hide a real defect.
    """


class AllProvidersUnavailable(AIProviderException):
    """Raised when no provider is configured or every one was unavailable.

    The API layer catches this to degrade gracefully: deterministic syntax and
    schema validation still work, and the response signals that AI is
    temporarily unavailable.
    """


class AIProvider(ABC):
    """Abstract base for a swappable AI provider."""

    #: Stable short name, e.g. ``"gemini"``. Also used in ``AI_PROVIDER_ORDER``.
    name: str = ""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when this provider has the credentials/config it needs."""

    @abstractmethod
    async def suggest(self, context: PromptContext) -> AISuggestion:
        """Produce an :class:`AISuggestion` for the given prompt context.

        Implementations must map transient failures (timeout / 5xx / 429 /
        quota / model-unavailable) to :class:`ProviderUnavailable`, map safety
        refusals to :class:`ProviderRefusal`, and other hard failures to
        :class:`ProviderError`.
        """
