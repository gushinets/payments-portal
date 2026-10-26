"""Optional independent profile attributes, never cross-system identity."""

MAX_NAME_LENGTH = 100


def normalize_name(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid profile name")
    result = value.strip()
    if len(result) > MAX_NAME_LENGTH or any(ord(char) < 32 or ord(char) == 127 for char in result):
        raise ValueError("invalid profile name")
    return result or None
