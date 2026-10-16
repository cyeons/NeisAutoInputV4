from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    label: str
    description: str

    @property
    def display_name(self) -> str:
        return f"{self.label} · {self.description}"


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    label: str
    models: tuple[ModelSpec, ...]
    default_model_id: str


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        provider_id="Gemini",
        label="Gemini",
        models=(
            ModelSpec("gemini-3.5-flash", "Gemini 3.5 Flash", "균형형"),
            ModelSpec("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", "빠름·저비용"),
        ),
        default_model_id="gemini-3.5-flash",
    ),
    ProviderSpec(
        provider_id="OpenAI",
        label="OpenAI",
        models=(
            ModelSpec("gpt-5.4-mini", "GPT-5.4 mini", "균형형"),
            ModelSpec("gpt-5.4-nano", "GPT-5.4 nano", "빠름·저비용"),
        ),
        default_model_id="gpt-5.4-mini",
    ),
)

_PROVIDERS_BY_ID = {item.provider_id: item for item in PROVIDERS}


def provider_spec(provider_id: str) -> ProviderSpec:
    return _PROVIDERS_BY_ID.get(provider_id, _PROVIDERS_BY_ID["Gemini"])


def provider_ids() -> tuple[str, ...]:
    return tuple(item.provider_id for item in PROVIDERS)


def model_ids(provider_id: str) -> tuple[str, ...]:
    return tuple(item.model_id for item in provider_spec(provider_id).models)


def normalize_provider(provider_id: str) -> str:
    return provider_id if provider_id in _PROVIDERS_BY_ID else "Gemini"


def normalize_model(provider_id: str, model_id: str) -> str:
    spec = provider_spec(provider_id)
    return model_id if model_id in model_ids(provider_id) else spec.default_model_id
