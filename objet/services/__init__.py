"""Services d'orchestration et composants applicatifs.

Les imports sont différés pour éviter de charger les dépendances écran/OCR
quand un seul service léger est demandé.
"""

__all__ = [
    "Controller",
    "Table",
]


def __getattr__(name: str):
    if name == "Controller":
        from .controller import Controller

        return Controller
    if name == "Table":
        from .table import Table

        return Table
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
