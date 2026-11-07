from .base import ManagerError, Target, nxm_url
from .mo2 import MO2Target, find_instances, write_meta
from .vortex import VortexTarget


def make_target(kind: str, game: str, **paths) -> Target:
    """``kind`` is "vortex" or "mo2"; ``paths`` are the folder/exe settings."""
    kind = (kind or "").lower()
    if kind == "mo2":
        return MO2Target(game, instance=paths.get("mo2_instance") or None,
                         exe=paths.get("mo2_exe") or None,
                         downloads=paths.get("mo2_downloads") or None)
    if kind == "vortex":
        return VortexTarget(game, downloads=paths.get("vortex_downloads") or None,
                            exe=paths.get("vortex_exe") or None)
    raise ManagerError(f"Unknown mod manager {kind!r} (use vortex or mo2)")


__all__ = ["ManagerError", "Target", "nxm_url", "MO2Target", "VortexTarget",
           "find_instances", "write_meta", "make_target"]
