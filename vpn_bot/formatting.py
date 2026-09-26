def infinit_or_real(value: int, unit: str) -> str:
    return "نامحدود" if value in (-1, 0) else f"{value} {unit}"
