"""Production-safety guards used by the Telegram bot."""

def validate_incoming_text(text: str, max_length: int) -> tuple[bool, str]:
    value = (text or "").strip()
    if not value:
        return False, "empty"
    if len(value) > max_length:
        return False, "too_long"
    return True, value
