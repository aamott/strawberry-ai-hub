"""Utility functions for the Hub."""

import re
import unicodedata


def normalize_device_name(name: str) -> str:
    """Normalize a device name for consistent routing.

    Transforms device names into a canonical form:
    - Lowercased
    - Spaces/hyphens converted to underscores
    - Special characters removed
    - Unicode normalized to ASCII equivalents

    Examples:
        "Living Room PC" -> "living_room_pc"
        "John's Laptop" -> "johns_laptop"
        "Büro-Computer" -> "buro_computer"

    Args:
        name: Raw device name (display name)

    Returns:
        Normalized name suitable for routing
    """
    if not name:
        return ""

    # Normalize unicode (é -> e, ü -> u, etc.)
    normalized = unicodedata.normalize("NFKD", name)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")

    # Lowercase
    normalized = normalized.lower()

    # Replace spaces and hyphens with underscores
    normalized = re.sub(r"[\s\-]+", "_", normalized)

    # Remove non-alphanumeric characters (except underscores)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)

    # Collapse multiple underscores
    normalized = re.sub(r"_+", "_", normalized)

    # Strip leading/trailing underscores
    normalized = normalized.strip("_")

    return normalized


__all__ = ["normalize_device_name"]
