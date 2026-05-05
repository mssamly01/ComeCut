"""Plugin / provider registry.

Third-party packages can extend ComeCut with custom AI providers
(image-gen, video-gen, TTS, voice clone) by declaring entry points
under one of these groups in their ``pyproject.toml``::

    [project.entry-points."comecut_py.video_providers"]
    my-provider = "my_pkg.providers:MyVideoGen"

    [project.entry-points."comecut_py.image_providers"]
    my-image    = "my_pkg.providers:make_image_gen"

    [project.entry-points."comecut_py.tts_providers"]
    my-tts      = "my_pkg.providers:MyTTS"

    [project.entry-points."comecut_py.voice_clone_providers"]
    my-cloner   = "my_pkg.providers:MyCloner"

Each entry point must resolve to a **factory** — either a class or a
callable — that accepts ``**kwargs`` from the CLI (typically
``model=...``) and returns an instance of the matching abstract base
in :mod:`comecut_py.ai.base`. The CLI then calls the appropriate
method (``generate``, ``synthesize``, or ``clone``) on it.

Discovery uses :func:`importlib.metadata.entry_points` so plugins
work as soon as their package is ``pip install``-ed in the same
environment as ``comecut-py``.

Builtin providers live in :mod:`comecut_py.ai` and are registered
internally so the CLI works without any third-party packages
installed. If a plugin registers the same name as a builtin, the
plugin wins (consistent with Python's "last wins" model for entry
points).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata as _md
from typing import Any

# Public group aliases — short keys used by the CLI and tests.
# The full entry-point group names are mapped here.
GROUPS: dict[str, str] = {
    "video": "comecut_py.video_providers",
    "image": "comecut_py.image_providers",
    "tts": "comecut_py.tts_providers",
    "voice_clone": "comecut_py.voice_clone_providers",
}


@dataclass(frozen=True)
class ProviderInfo:
    """Light-weight description of a registered provider.

    ``source`` is ``'builtin'`` for providers shipped with comecut-py
    and ``'plugin'`` for providers loaded via entry points (the value
    of the entry-point ``dist.name`` is appended after a colon when
    available — e.g. ``'plugin:my-pkg'``).
    """

    name: str
    source: str


# Builtin factories. Imports are lazy so adding a builtin doesn't
# pull every optional dependency at startup.
def _runway(model: str | None = None, **kw: Any) -> Any:
    from .ai.runway_video import RunwayVideoGen
    return RunwayVideoGen(model=model or "gen3a_turbo", **kw)


def _replicate_video(model: str | None = None, **kw: Any) -> Any:
    from .ai.replicate import ReplicateVideoGen
    return ReplicateVideoGen(model=model or "minimax/video-01", **kw)


def _luma(model: str | None = None, **kw: Any) -> Any:
    from .ai.luma_video import LumaVideoGen
    return LumaVideoGen(model=model or "ray-2", **kw)


def _kling(model: str | None = None, **kw: Any) -> Any:
    from .ai.kling_video import KlingVideoGen
    return KlingVideoGen(model=model or "kling-v2-6", **kw)


def _veo(model: str | None = None, **kw: Any) -> Any:
    from .ai.veo_video import VeoVideoGen
    return VeoVideoGen(model=model or "veo-3.1-generate-preview", **kw)


def _openai_image(model: str | None = None, **kw: Any) -> Any:
    from .ai.openai_image import OpenAIImageGen
    return OpenAIImageGen(model=model or "gpt-image-1", **kw)


def _stability_image(model: str | None = None, **kw: Any) -> Any:
    from .ai.stability_image import StabilityImageGen
    return StabilityImageGen(engine=model or "ultra", **kw)


def _replicate_image(model: str | None = None, **kw: Any) -> Any:
    from .ai.replicate import ReplicateImageGen
    return ReplicateImageGen(model=model or "black-forest-labs/flux-schnell", **kw)


def _openai_tts(model: str | None = None, **kw: Any) -> Any:
    from .ai.openai_tts import OpenAITTS
    return OpenAITTS(model=model or "tts-1", **kw)


def _elevenlabs_tts(model: str | None = None, **kw: Any) -> Any:
    from .ai.elevenlabs_tts import ElevenLabsTTS
    return ElevenLabsTTS(model=model or "eleven_multilingual_v2", **kw)


def _elevenlabs_voice_clone(**kw: Any) -> Any:
    from .ai.elevenlabs_voice_clone import ElevenLabsVoiceClone
    return ElevenLabsVoiceClone(**kw)


_BUILTINS: dict[str, dict[str, Callable[..., Any]]] = {
    "video": {
        "runway": _runway,
        "replicate": _replicate_video,
        "luma": _luma,
        "kling": _kling,
        "veo": _veo,
    },
    "image": {
        "openai": _openai_image,
        "stability": _stability_image,
        "replicate": _replicate_image,
    },
    "tts": {
        "openai": _openai_tts,
        "elevenlabs": _elevenlabs_tts,
    },
    "voice_clone": {
        "elevenlabs": _elevenlabs_voice_clone,
    },
}


def _entry_points_for(group_alias: str) -> list[_md.EntryPoint]:
    group = GROUPS.get(group_alias)
    if group is None:
        return []
    try:
        eps = _md.entry_points()
    except Exception:  # pragma: no cover - defensive
        return []
    # Python 3.10 returns a SelectableGroups; 3.12 supports .select(group=...).
    select = getattr(eps, "select", None)
    if callable(select):
        return list(select(group=group))
    # Pre-3.10 fallback (shouldn't trigger; project requires 3.10+).
    return list(eps.get(group, []))  # type: ignore[arg-type]


def list_providers(group_alias: str) -> list[ProviderInfo]:
    """Return every provider known for ``group_alias``.

    Plugins shadow builtins of the same name (the ``source`` for the
    overridden entry will read ``'plugin:…'``). The list is sorted by
    name for deterministic CLI output.
    """
    if group_alias not in GROUPS:
        raise ValueError(
            f"unknown provider group {group_alias!r}; expected one of "
            f"{sorted(GROUPS)}"
        )
    out: dict[str, ProviderInfo] = {}
    for name in _BUILTINS.get(group_alias, {}):
        out[name] = ProviderInfo(name=name, source="builtin")
    for ep in _entry_points_for(group_alias):
        dist_name = getattr(getattr(ep, "dist", None), "name", None)
        source = f"plugin:{dist_name}" if dist_name else "plugin"
        out[ep.name] = ProviderInfo(name=ep.name, source=source)
    return [out[k] for k in sorted(out)]


def get_provider(group_alias: str, name: str, /, **kwargs: Any) -> Any:
    """Resolve a provider by group + name and instantiate it.

    ``**kwargs`` are forwarded to the underlying factory (typically
    ``model=…``). External plugins always win over builtins of the
    same name so users can swap in alternate implementations without
    forking comecut-py.
    """
    if group_alias not in GROUPS:
        raise ValueError(
            f"unknown provider group {group_alias!r}; expected one of "
            f"{sorted(GROUPS)}"
        )

    # Plugins shadow builtins.
    for ep in _entry_points_for(group_alias):
        if ep.name == name:
            factory = ep.load()
            return factory(**kwargs)

    builtin = _BUILTINS.get(group_alias, {}).get(name)
    if builtin is not None:
        return builtin(**kwargs)

    known = ", ".join(p.name for p in list_providers(group_alias))
    raise KeyError(
        f"unknown provider {name!r} for group {group_alias!r}; "
        f"available providers: {known or '(none)'}"
    )


__all__ = [
    "GROUPS",
    "ProviderInfo",
    "get_provider",
    "list_providers",
]
