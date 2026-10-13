"""Amazon Bedrock provider (bedrock-runtime invoke_model).

Authentication uses the boto3 default credential chain - on EC2 this is the
instance IAM role, so there is NO static API key. ``is_configured`` reflects
whether a region and model id are present. Throttling / server / timeout
errors from botocore map to :class:`ProviderUnavailable`.

The request body follows the Anthropic-on-Bedrock message schema, which is the
schema used by the Claude models referenced by ``BEDROCK_MODEL_ID``.
"""

from __future__ import annotations

import asyncio
import json

from app.ai.base import (
    AIProvider,
    AISuggestion,
    ProviderError,
    ProviderRefusal,
    ProviderUnavailable,
)
from app.ai.prompt import PromptContext, build_prompt, parse_response

# botocore error codes that indicate a transient / retryable condition.
_UNAVAILABLE_ERROR_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "ServiceUnavailable",
    "InternalServerException",
    "InternalFailure",
    "ModelTimeoutException",
    "ModelNotReadyException",
    "ModelStreamErrorException",
}
# Codes indicating the requested model is unavailable -> fall back.
_MODEL_UNAVAILABLE_CODES = {
    "ResourceNotFoundException",
    "ModelNotReadyException",
}


class BedrockProvider(AIProvider):
    """Bedrock provider backed by ``bedrock-runtime`` ``invoke_model``."""

    name = "bedrock"

    def is_configured(self) -> bool:
        return bool(self.settings.BEDROCK_REGION and self.settings.BEDROCK_MODEL_ID)

    def _client(self):
        import boto3

        return boto3.client("bedrock-runtime", region_name=self.settings.BEDROCK_REGION)

    def _invoke(self, prompt: str) -> dict:
        """Synchronous boto3 call executed in a worker thread."""
        from botocore.exceptions import BotoCoreError, ClientError

        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}],
            }
        )
        try:
            client = self._client()
            response = client.invoke_model(
                modelId=self.settings.BEDROCK_MODEL_ID,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            if (
                code in _UNAVAILABLE_ERROR_CODES
                or code in _MODEL_UNAVAILABLE_CODES
                or (isinstance(status, int) and status >= 500)
                or status == 429
            ):
                raise ProviderUnavailable(f"bedrock {code or status}") from exc
            if code == "AccessDeniedException":
                # Deliberate deny (e.g. model not granted) - do not fall back.
                raise ProviderError(f"bedrock {code}") from exc
            raise ProviderError(f"bedrock {code or status}") from exc
        except BotoCoreError as exc:
            # Connection/timeout failures at the botocore transport level.
            raise ProviderUnavailable(f"bedrock transport: {type(exc).__name__}") from exc

        raw = response.get("body")
        payload = raw.read() if hasattr(raw, "read") else raw
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        return json.loads(payload)

    async def suggest(self, context: PromptContext) -> AISuggestion:
        prompt = build_prompt(context)
        data = await asyncio.to_thread(self._invoke, prompt)

        if data.get("stop_reason") == "refusal":
            raise ProviderRefusal("bedrock model refused the request")

        blocks = data.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        if not text.strip():
            raise ProviderError("bedrock returned empty content")

        try:
            suggested_sql, explanation, optimizations = parse_response(text, self.name)
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc

        return AISuggestion(
            suggested_sql=suggested_sql,
            explanation=explanation,
            optimizations=optimizations,
            provider=self.name,
        )
