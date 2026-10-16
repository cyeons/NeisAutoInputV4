from __future__ import annotations

import sys


_injected = False


def configure_windows_trust_store(enabled: bool) -> bool:
    global _injected
    if not enabled or _injected or sys.platform != "win32":
        return False
    try:
        import truststore

        truststore.inject_into_ssl()
        _injected = True
        return True
    except Exception:
        return False
