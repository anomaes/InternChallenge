"""Provider-neutral interface for the generative extraction step, so the model or vendor
can change without touching the pipeline (and tests can use a fake)."""

from dataclasses import dataclass
from typing import Protocol

from app.llm.schema import Extraction


class ExtractionError(Exception):
    """API down, timeout, refusal, truncation or unparseable output."""


@dataclass
class ExtractionCall:
    output: Extraction
    raw: str
    model: str
    prompt_version: str
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cached: bool


class Extractor(Protocol):
    model: str
    prompt_version: str

    def extract(self, source: str, feedback: list[str] | None = None) -> ExtractionCall: ...
