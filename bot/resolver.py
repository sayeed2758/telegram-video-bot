from dataclasses import dataclass


@dataclass
class ResolveResult:
    platform: str
    original_url: str
    title: str = ""
    playable_url: str | None = None
    note: str = ""


async def resolve_link(url: str, platform: str) -> ResolveResult:
    # Safe Phase-1 adapter:
    # return the user-supplied public URL as the playable/open link.
    #
    # A future resolver can be added here only when it uses an official,
    # licensed, or otherwise authorized API/integration.
    return ResolveResult(
        platform=platform,
        original_url=url,
        title="User submitted link",
        playable_url=url,
        note="Resolver adapter is ready for an official/licensed integration.",
    )
