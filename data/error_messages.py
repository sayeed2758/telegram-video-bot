"""User-facing error classification for Advance Tera Video Bot."""


def classify_resolver_error(reason: str) -> tuple[str, str]:
    """Return (short_title, friendly_message) without exposing raw internals."""
    lowered = str(reason or "").lower()

    if any(token in lowered for token in ("invalid tera", "invalid", "unsupported")) and "api" not in lowered:
        return (
            "⚠️ Invalid Link",
            "Please send a valid public TeraBox share link and try again.",
        )

    if "password required" in lowered or "extraction" in lowered or "password" in lowered:
        return (
            "🔐 Password Required",
            "This TeraBox share is protected by a password. Send the share password to retry.",
        )

    if any(token in lowered for token in ("need verify", "verification required", "verify", "session")):
        return (
            "🛡️ TeraBox Verification Required",
            "TeraBox is asking for a verified session for this share.\n\n"
            "The bot stopped safely instead of repeatedly calling other resolvers.",
        )

    if "httpx" in lowered or "timeout" in lowered or "connecterror" in lowered or "request failed" in lowered:
        return (
            "🌐 Temporary Connection Problem",
            "The service took too long to respond. The bot already tried again automatically. Please tap Retry after a short wait if needed.",
        )

    if "401" in lowered or "api key is invalid" in lowered:
        return (
            "🔑 API Authentication Failed",
            "The PlayTeraBox API key was rejected. Check the Render environment variable.",
        )

    if "402" in lowered or "wallet balance" in lowered:
        return (
            "💳 API Credits Unavailable",
            "The PlayTeraBox API account does not have enough credits for this request.",
        )

    if "403" in lowered or "access is denied" in lowered or "not subscribed" in lowered:
        return (
            "🚫 API Access Denied",
            "The PlayTeraBox API currently refused this request. Check the API subscription/status.",
        )

    if "404" in lowered or "not found" in lowered:
        return (
            "🔎 File or Endpoint Not Found",
            "The requested share or API resource could not be found. Please check the link and try again.",
        )

    if "429" in lowered or "too many" in lowered or "rate limit" in lowered:
        return (
            "⏳ Too Many Requests",
            "The service is temporarily rate-limiting requests. Please wait a little and tap Retry.",
        )

    if "500" in lowered or "502" in lowered or "503" in lowered or "504" in lowered or "server" in lowered:
        return (
            "🛠️ Service Temporarily Unavailable",
            "The upstream service returned a temporary server error. Please try again shortly.",
        )

    if "no usable" in lowered or "no file" in lowered or "no files" in lowered:
        return (
            "📭 No Usable File Found",
            "The share responded, but no playable file information was returned.",
        )

    return (
        "❌ Could Not Process Link",
        "The share could not be processed right now. Please tap Retry or try another link.",
    )
