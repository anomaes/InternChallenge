"""Generative extraction with OpenAI structured outputs (Responses API + Pydantic schema)."""

import time
from pathlib import Path

import openai
from pydantic import ValidationError

from app.config import settings
from app.llm.cache import cache_get, cache_key, cache_put
from app.llm.provider import ExtractionCall, ExtractionError
from app.llm.schema import Extraction

PROMPT_VERSION = "extract_v2"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"


def render_prompt(gl_accounts: list[tuple[str, str]]) -> str:
    gl = "\n  ".join(f"- {code}: {name}" for code, name in gl_accounts)
    return _PROMPT_PATH.read_text(encoding="utf-8").replace("{gl_accounts}", gl)


class OpenAIExtractor:
    prompt_version = PROMPT_VERSION

    def __init__(self, gl_accounts: list[tuple[str, str]], *, use_cache: bool = True) -> None:
        self.model = settings.extraction_model
        self.reasoning = settings.extraction_reasoning
        self.instructions = render_prompt(gl_accounts)
        self.use_cache = use_cache
        key = settings.api_key()
        self._client = (
            openai.OpenAI(api_key=key, timeout=settings.llm_timeout_s, max_retries=2)
            if key
            else None
        )

    def extract(self, source: str, feedback: list[str] | None = None) -> ExtractionCall:
        key = cache_key(
            "extract", self.model, self.prompt_version, self.instructions, source, *(feedback or [])
        )
        if self.use_cache and (hit := cache_get(key)):
            try:
                return ExtractionCall(
                    output=Extraction.model_validate_json(hit["raw"]),
                    raw=hit["raw"],
                    model=hit["model"],
                    prompt_version=self.prompt_version,
                    latency_ms=hit.get("latency_ms"),
                    input_tokens=hit.get("input_tokens"),
                    output_tokens=hit.get("output_tokens"),
                    cached=True,
                )
            except (ValidationError, KeyError):
                pass  # stale entry: fall through to a live call

        if self._client is None:
            raise ExtractionError(
                "No OPENAI_API_KEY configured and no cached result for this email."
            )

        messages: list[dict] = [{"role": "user", "content": source}]
        if feedback:
            messages.append(
                {
                    "role": "user",
                    "content": "Your previous answer failed validation:\n- "
                    + "\n- ".join(feedback)
                    + "\nReturn the complete extraction again with these problems fixed. "
                    "Use null where the document does not state a value.",
                }
            )
        started = time.monotonic()
        try:
            resp = self._client.responses.parse(
                model=self.model,
                instructions=self.instructions,
                input=messages,  # type: ignore[arg-type]
                text_format=Extraction,
                reasoning={"effort": self.reasoning},  # type: ignore[typeddict-item]
                max_output_tokens=16000,
            )
        except (openai.APIError, ValidationError, ValueError) as err:
            raise ExtractionError(f"{type(err).__name__}: {str(err)[:300]}") from err
        latency = int((time.monotonic() - started) * 1000)

        if resp.status == "incomplete":
            reason = getattr(resp.incomplete_details, "reason", "unknown")
            raise ExtractionError(f"Model output incomplete ({reason}).")
        for item in resp.output:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise ExtractionError(f"Model refused: {part.refusal[:200]}")
        parsed = resp.output_parsed
        if parsed is None:
            raise ExtractionError("Model returned no parseable output.")

        raw = parsed.model_dump_json()
        usage = resp.usage
        call = ExtractionCall(
            output=parsed,
            raw=raw,
            model=resp.model,
            prompt_version=self.prompt_version,
            latency_ms=latency,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cached=False,
        )
        cache_put(
            key,
            {
                "raw": raw,
                "model": call.model,
                "latency_ms": latency,
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
            },
        )
        return call
