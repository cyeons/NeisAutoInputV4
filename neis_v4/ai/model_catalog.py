from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    label: str
    description: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.label} · {self.description}" if self.description else self.label


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    label: str
    models: tuple[ModelSpec, ...]
    default_model_id: str
    # API 키를 발급받는 웹 페이지
    key_url: str = ""


# 화면에 이 순서대로 보입니다. 저장된 값이 잘못되면 맨 앞 서비스를 씁니다.
# Upstage는 기본 키가 내장되어 키 등록 없이 쓸 수 있지만 글 품질이 낮아 맨 뒤에 둡니다.
PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        provider_id="Gemini",
        label="Gemini",
        models=(
            # 2026-11 실측(가짜 학생 25명): 평어 3.8 Flash 29초·4 Hydrogen 36초·4 Neon 92초,
            # 행발 3.8 Flash 27초·4 Hydrogen 113초.
            # 권장(기본) 모델은 3.5 Flash-Lite입니다 (2026-11 사용자 결정). 권장 모델을 목록 맨 앞에 둡니다.
            ModelSpec("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "권장"),
            ModelSpec("gemini-3.8-flash", "Gemini 3.8 Flash"),
            ModelSpec("gemini-4-hydrogen", "Gemini 4 Hydrogen"),
            ModelSpec("gemini-4-neon", "Gemini 4 Neon"),
        ),
        default_model_id="gemini-3.5-flash-lite",
        key_url="https://aistudio.google.com/apikey",
    ),
    ProviderSpec(
        provider_id="OpenAI",
        label="OpenAI",
        models=(
            ModelSpec("gpt-6-luna", "GPT 6 Luna", "권장"),
            ModelSpec("gpt-6.1-terra", "GPT 6.1 Terra"),
            ModelSpec("gpt-6.2-sol", "GPT 6.2 Sol"),
        ),
        default_model_id="gpt-6-luna",
        key_url="https://platform.openai.com/api-keys",
    ),
    ProviderSpec(
        provider_id="Claude",
        label="Claude",
        models=(
            ModelSpec("claude-haiku-5-5", "Claude Haiku 5.5", "권장"),
            ModelSpec("claude-sonnet-5-5", "Claude Sonnet 5.5"),
            ModelSpec("claude-opus-5-5", "Claude Opus 5.5"),
        ),
        default_model_id="claude-haiku-5-5",
        key_url="https://platform.claude.com/settings/keys",
    ),
    ProviderSpec(
        provider_id="Upstage",
        label="Upstage",
        models=(ModelSpec("solar-pro4", "Solar Pro 4"),),
        default_model_id="solar-pro4",
        key_url="https://console.upstage.ai/api-keys",
    ),
)

_PROVIDERS_BY_ID = {item.provider_id: item for item in PROVIDERS}

# API 키 관리 창의 '최신 모델 불러오기'로 받아 온 모델. 기본 목록 뒤에 붙습니다.
_fetched: dict[str, tuple[ModelSpec, ...]] = {}
# 글쓰기에 맞지 않는 모델(음성·이미지·검색·임베딩 등)은 이름으로 거릅니다.
_SKIP_WORDS = (
    "audio", "realtime", "tts", "transcribe", "image", "search", "embedding", "moderation",
    "instruct", "codex", "computer", "live", "robotics", "nano-banana", "omni", "chat-latest",
)
_DATED = re.compile(r"-\d{4}-?\d{2}-?\d{2}$")


def set_fetched_models(provider_id: str, model_list: list[str]) -> None:
    builtin = {item.model_id for item in provider_spec(provider_id).models}
    _fetched[provider_id] = tuple(
        ModelSpec(model_id, model_id) for model_id in model_list if model_id not in builtin
    )


def fetched_model_ids(provider_id: str) -> list[str]:
    return [item.model_id for item in _fetched.get(provider_id, ())]


def models_for(provider_id: str) -> tuple[ModelSpec, ...]:
    return provider_spec(provider_id).models + _fetched.get(provider_id, ())


def filter_text_models(model_list: list[str]) -> list[str]:
    """최신순으로 받은 모델 이름에서 글쓰기용만 남깁니다 (날짜 붙은 고정판도 뺌)."""
    kept = [
        model_id for model_id in model_list
        if not _DATED.search(model_id) and not any(word in model_id for word in _SKIP_WORDS)
    ]
    return kept


def _version_key(model_id: str) -> list[int]:
    return [int(number) for number in re.findall(r"\d+", model_id)]


def fetch_latest_models(provider_id: str, api_key: str) -> list[str]:
    """서비스에 지금 쓸 수 있는 모델 목록을 물어 최신순으로 돌려줍니다. 실패하면 예외가 납니다."""
    if provider_id == "OpenAI":
        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=30)
        items = list(client.models.list())  # client를 변수에 둬야 목록을 다 읽기 전에 연결이 닫히지 않습니다.
        ordered = [item.id for item in sorted(items, key=lambda item: item.created, reverse=True)]
        ordered = [model_id for model_id in ordered if model_id.startswith("gpt-") or re.match(r"o\d", model_id)]
    elif provider_id == "Gemini":
        from google import genai

        client = genai.Client(api_key=api_key)
        items = list(client.models.list())
        names = [
            item.name.removeprefix("models/")
            for item in items
            if "generateContent" in (item.supported_actions or []) and "gemini" in item.name
        ]
        ordered = sorted(names, key=_version_key, reverse=True)
    elif provider_id == "Claude":
        import anthropic

        client = anthropic.Anthropic(api_key=api_key, timeout=30)
        items = list(client.models.list())
        ordered = [item.id for item in sorted(items, key=lambda item: item.created_at, reverse=True)]
    else:
        return []
    return filter_text_models(ordered)


def provider_spec(provider_id: str) -> ProviderSpec:
    return _PROVIDERS_BY_ID.get(provider_id, PROVIDERS[0])


def provider_ids() -> tuple[str, ...]:
    return tuple(item.provider_id for item in PROVIDERS)


def model_ids(provider_id: str) -> tuple[str, ...]:
    return tuple(item.model_id for item in models_for(provider_id))


def normalize_provider(provider_id: str) -> str:
    return provider_id if provider_id in _PROVIDERS_BY_ID else PROVIDERS[0].provider_id


def normalize_model(provider_id: str, model_id: str) -> str:
    spec = provider_spec(provider_id)
    return model_id if model_id in model_ids(provider_id) else spec.default_model_id
