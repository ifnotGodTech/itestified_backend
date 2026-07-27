def normalize_full_name(value: str) -> str:
    """Title-cases each whitespace-separated word for display uniformity,
    e.g. "AIGUOSATILE AISOSA" / "john doe" -> "Aiguosatile Aisosa" / "John Doe".
    Also collapses repeated whitespace. Blank input is returned unchanged."""
    return " ".join(word.capitalize() for word in value.split())
