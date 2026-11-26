from __future__ import annotations

import base64
from datetime import date

from neis_v4.ai.model_catalog import provider_ids

SERVICE_NAME = "NeisAutoInputV4"  # 프로그램 이름이 바뀌어도 그대로 둡니다. 바꾸면 저장해 둔 API 키를 못 찾습니다.

# Upstage AI Initiative 무료 사용 기간 동안 exe에 내장해 배포하는 Upstage(Solar Pro 4) 기본 키.
# 키는 빌드할 때 .env에서 읽어 neis_v4/_bundled_key.py(Git 제외)로 만듭니다 — NeisAutoInputV4.spec 참고.
BUNDLED_KEY_PROVIDER = "Upstage"
BUNDLED_KEY_EXPIRES = date(2027, 3, 31)
# 2026-11-23 실제 응답 헤더(x-upstage-ratelimit-*)로 확인한 한도. 하루·한 달 한도는 공식 문서에 없음.
# 한도는 계정 단위라 이 키로 접속하는 모든 사용자가 함께 씁니다.
BUNDLED_KEY_LIMITS = "1분에 요청 400회 · 토큰 180만 개"
EXPIRY_WARNING_DAYS = 30
# ponytail: XOR 가리기일 뿐 암호화가 아님. exe를 분석하면 키를 꺼낼 수 있으니 만료 후 콘솔에서 키를 폐기할 것.
_MASK = b"NeisAutoInputV4-solar"


def _xor(data: bytes) -> bytes:
    return bytes(value ^ _MASK[index % len(_MASK)] for index, value in enumerate(data))


def obfuscate_key(api_key: str) -> str:
    return base64.b85encode(_xor(api_key.encode("utf-8"))).decode("ascii")


def reveal_key(text: str) -> str:
    return _xor(base64.b85decode(text)).decode("utf-8")


def _bundled_key_text() -> str:
    try:
        from neis_v4._bundled_key import DATA

        return reveal_key(DATA)
    except Exception:
        return ""


def bundled_api_key(today: date | None = None) -> str:
    if (today or date.today()) > BUNDLED_KEY_EXPIRES:
        return ""
    return _bundled_key_text()


def bundled_days_left(today: date | None = None) -> int:
    return (BUNDLED_KEY_EXPIRES - (today or date.today())).days


def bundled_key_expired(today: date | None = None) -> bool:
    """기본 키가 들어 있지만 무료 사용 기간이 끝났는지 알려 줍니다."""
    return bundled_days_left(today) < 0 and bool(_bundled_key_text())


def no_key_message(today: date | None = None) -> str:
    message = "Upstage·Gemini·OpenAI·Claude 중 하나의 API 키를 먼저 등록하세요."
    if bundled_key_expired(today):
        message = (
            f"{BUNDLED_KEY_PROVIDER} 기본 키의 무료 사용 기간({BUNDLED_KEY_EXPIRES.isoformat()})이 끝났습니다. "
            + message
        )
    return message


class SecretStore:
    def __init__(self) -> None:
        try:
            import keyring

            self._keyring = keyring
        except Exception:
            self._keyring = None

    def get_api_key(self, provider: str) -> str:
        """직접 등록한 키를 먼저 쓰고, 없으면 기본 키(Upstage만, 기한 내)를 씁니다."""
        user_key = self.get_user_api_key(provider)
        if user_key or provider != BUNDLED_KEY_PROVIDER:
            return user_key
        return bundled_api_key()

    def uses_bundled_key(self, provider: str) -> bool:
        return not self.get_user_api_key(provider) and bool(self.get_api_key(provider))

    def key_status_text(self, provider: str) -> str:
        if self.uses_bundled_key(provider):
            days = bundled_days_left()
            if days <= EXPIRY_WARNING_DAYS:
                # 끝나기 한 달 전부터 남은 날을 보여 줘 미리 키를 준비하게 합니다.
                return f"{provider} 기본 키 · {'오늘까지' if days == 0 else f'{days}일 뒤 끝남'}"
            return f"{provider} 기본 키 ({BUNDLED_KEY_EXPIRES.isoformat()}까지)"
        return f"{provider} 등록됨"

    def get_user_api_key(self, provider: str) -> str:
        if not self._keyring:
            return ""
        try:
            return self._keyring.get_password(SERVICE_NAME, provider.lower()) or ""
        except Exception:
            return ""

    def set_api_key(self, provider: str, api_key: str) -> bool:
        if not self._keyring or not api_key.strip():
            return False
        try:
            self._keyring.set_password(SERVICE_NAME, provider.lower(), api_key.strip())
            return True
        except Exception:
            return False

    def delete_api_key(self, provider: str) -> bool:
        if not self._keyring:
            return False
        try:
            self._keyring.delete_password(SERVICE_NAME, provider.lower())
            return True
        except Exception:
            return False

    def has_api_key(self, provider: str) -> bool:
        return bool(self.get_api_key(provider))

    def registered_providers(self) -> list[str]:
        return [
            provider
            for provider in provider_ids()
            if self.has_api_key(provider)
        ]

    def has_secure_backend(self) -> bool:
        return self._keyring is not None
