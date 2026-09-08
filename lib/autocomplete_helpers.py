DISCORD_CHOICE_NAME_LIMIT = 100


def build_choice_name(
    title: str, media_id, source: str, label: str | None = None
) -> str:
    """`[Label] Title (ID: 123) (API)`, truncating only the title to stay within Discord's limit."""
    prefix = f"[{label}] " if label else ""
    suffix = f" (ID: {media_id}) ({source})"
    room_for_title = max(0, DISCORD_CHOICE_NAME_LIMIT - len(prefix) - len(suffix))
    return f"{prefix}{title[:room_for_title]}{suffix}"
