from __future__ import annotations

SERVICE_NAME = "NeisAutoInputV4"


class SecretStore:
    def __init__(self) -> None:
        try:
            import keyring

            self._keyring = keyring
        except Exception:
            self._keyring = None

    def get_api_key(self, provider: str) -> str:
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
            for provider in ("Gemini", "OpenAI")
            if self.has_api_key(provider)
        ]

    def has_secure_backend(self) -> bool:
        return self._keyring is not None
