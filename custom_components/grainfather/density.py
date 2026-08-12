from __future__ import annotations


def sg_to_plato(sg: float | None) -> float | None:
    """Convert specific gravity to degrees Plato."""
    if sg is None:
        return None
    return round(
        -616.868 + 1111.14 * sg - 630.272 * sg * sg + 135.997 * sg * sg * sg,
        1,
    )
