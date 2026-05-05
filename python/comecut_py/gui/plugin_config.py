"""Plugin service + subtitle translation settings persistence.

This module mirrors the HTML plugin panels at a practical level:
* service/provider profiles (base URL, API key, model list)
* subtitle translation settings (provider, model, prompt, glossary, batch size)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..ai.base import TranslateProvider
from ..ai.claude_translate import ClaudeTranslate
from ..ai.gemini_translate import GeminiTranslate
from ..ai.openai_translate import OpenAITranslate


_CONFIG_DIR = Path.home() / ".comecut_py"
_CONFIG_PATH = _CONFIG_DIR / "plugin_services.json"


@dataclass
class ProviderService:
    id: str
    name: str
    category: str = "LLM"  # LLM | API_MULTI
    provider_type: str = "openai"  # openai | gemini | claude | ollama | custom
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    models: list[str] = field(default_factory=list)
    current_model: str = ""
    is_preset: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderService":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            category=str(data.get("category") or "LLM"),
            provider_type=str(data.get("provider_type") or "openai"),
            base_url=str(data.get("base_url") or "https://api.openai.com/v1"),
            api_key=str(data.get("api_key") or ""),
            models=[str(v) for v in (data.get("models") or []) if str(v).strip()],
            current_model=str(data.get("current_model") or ""),
            is_preset=bool(data.get("is_preset", False)),
        )


@dataclass
class TranslationSettings:
    provider_id: str = ""
    current_model: str = ""
    batch_size: int = 10
    target_language: str = "Vietnamese"
    source_language: str = ""
    system_prompt: str = ""
    glossary: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranslationSettings":
        return cls(
            provider_id=str(data.get("provider_id") or ""),
            current_model=str(data.get("current_model") or ""),
            batch_size=max(1, int(data.get("batch_size") or 10)),
            target_language=str(data.get("target_language") or "Vietnamese"),
            source_language=str(data.get("source_language") or ""),
            system_prompt=str(data.get("system_prompt") or ""),
            glossary=str(data.get("glossary") or ""),
        )


def default_translation_prompt() -> str:
    return (
        "You are a professional subtitle translator.\n"
        "Translate the user's subtitle text into {target}.\n"
        "Keep meaning and tone natural.\n"
        "Return only the translated text, with no quotes or explanations."
    )


def default_provider_services() -> list[ProviderService]:
    return [
        ProviderService(
            id="preset_openai",
            name="ChatGPT / OpenAI",
            category="LLM",
            provider_type="openai",
            base_url="https://api.openai.com/v1",
            models=["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
            current_model="gpt-4o-mini",
            is_preset=True,
        ),
        ProviderService(
            id="preset_gemini",
            name="Google Gemini",
            category="LLM",
            provider_type="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            models=["gemini-1.5-flash", "gemini-1.5-pro"],
            current_model="gemini-1.5-flash",
            is_preset=True,
        ),
        ProviderService(
            id="preset_claude",
            name="Anthropic Claude",
            category="LLM",
            provider_type="claude",
            base_url="https://api.anthropic.com/v1",
            models=["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest"],
            current_model="claude-3-5-haiku-latest",
            is_preset=True,
        ),
        ProviderService(
            id="preset_deepseek",
            name="DeepSeek",
            category="LLM",
            provider_type="openai",
            base_url="https://api.deepseek.com/v1",
            models=["deepseek-chat", "deepseek-reasoner"],
            current_model="deepseek-chat",
            is_preset=True,
        ),
        ProviderService(
            id="preset_ollama",
            name="Ollama (Local)",
            category="API_MULTI",
            provider_type="ollama",
            base_url="http://localhost:11434/v1",
            models=["llama3", "qwen2.5", "gemma2"],
            current_model="llama3",
            is_preset=True,
        ),
    ]


@dataclass
class PluginConfigStore:
    providers: list[ProviderService] = field(default_factory=default_provider_services)
    translation: TranslationSettings = field(
        default_factory=lambda: TranslationSettings(system_prompt=default_translation_prompt())
    )
    path: Path = _CONFIG_PATH

    @classmethod
    def load_default(cls) -> "PluginConfigStore":
        store = cls()
        store.load()
        return store

    def to_dict(self) -> dict[str, Any]:
        return {
            "providers": [asdict(p) for p in self.providers],
            "translation": asdict(self.translation),
        }

    def load(self) -> None:
        if not self.path.exists():
            self._ensure_defaults()
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._ensure_defaults()
            return

        loaded_providers = [
            ProviderService.from_dict(p)
            for p in (payload.get("providers") or [])
            if isinstance(p, dict)
        ]
        loaded_by_id = {p.id: p for p in loaded_providers if p.id}

        merged: list[ProviderService] = []
        for preset in default_provider_services():
            existing = loaded_by_id.pop(preset.id, None)
            if existing is None:
                merged.append(preset)
                continue
            # Keep user-edited API key/model selection on preset cards.
            existing.is_preset = True
            if not existing.base_url.strip():
                existing.base_url = preset.base_url
            if not existing.models:
                existing.models = list(preset.models)
            if not existing.current_model.strip():
                existing.current_model = preset.current_model
            merged.append(existing)

        # Keep custom providers.
        merged.extend(loaded_by_id.values())
        self.providers = merged

        tr_raw = payload.get("translation")
        self.translation = (
            TranslationSettings.from_dict(tr_raw)
            if isinstance(tr_raw, dict)
            else TranslationSettings(system_prompt=default_translation_prompt())
        )
        if not self.translation.system_prompt.strip():
            self.translation.system_prompt = default_translation_prompt()
        self._normalize_translation_provider()

    def save(self) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _ensure_defaults(self) -> None:
        if not self.translation.system_prompt.strip():
            self.translation.system_prompt = default_translation_prompt()
        self._normalize_translation_provider()
        self.save()

    def _normalize_translation_provider(self) -> None:
        if not self.providers:
            self.providers = default_provider_services()
        if not self.translation.provider_id or self.get_provider(self.translation.provider_id) is None:
            self.translation.provider_id = self.providers[0].id
        provider = self.get_provider(self.translation.provider_id)
        if provider is not None:
            if not self.translation.current_model.strip():
                self.translation.current_model = (
                    provider.current_model or (provider.models[0] if provider.models else "")
                )

    def get_provider(self, provider_id: str) -> ProviderService | None:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        return None

    def upsert_provider(self, provider: ProviderService) -> None:
        for idx, existing in enumerate(self.providers):
            if existing.id == provider.id:
                self.providers[idx] = provider
                self._normalize_translation_provider()
                self.save()
                return
        self.providers.append(provider)
        self._normalize_translation_provider()
        self.save()

    def delete_provider(self, provider_id: str) -> None:
        provider = self.get_provider(provider_id)
        if provider is None:
            return
        if provider.is_preset:
            # Preserve preset card; clear secret only.
            provider.api_key = ""
            self.upsert_provider(provider)
            return
        self.providers = [p for p in self.providers if p.id != provider_id]
        self._normalize_translation_provider()
        self.save()


def build_translate_provider(
    service: ProviderService,
    settings: TranslationSettings,
) -> TranslateProvider:
    model = (
        (settings.current_model or "").strip()
        or (service.current_model or "").strip()
        or (service.models[0] if service.models else "")
    )
    provider_type = (service.provider_type or "").strip().lower()
    base_url = (service.base_url or "").strip()
    api_key = (service.api_key or "").strip() or None

    if provider_type == "gemini" or "generativelanguage.googleapis.com" in base_url:
        return GeminiTranslate(
            api_key=api_key,
            model=model or "gemini-1.5-flash",
            base_url=base_url or "https://generativelanguage.googleapis.com/v1beta",
            system_prompt=settings.system_prompt,
            glossary=settings.glossary,
        )

    if provider_type == "claude" or "anthropic.com" in base_url:
        return ClaudeTranslate(
            api_key=api_key,
            model=model or "claude-3-5-haiku-latest",
            base_url=base_url or "https://api.anthropic.com/v1",
            system_prompt=settings.system_prompt,
            glossary=settings.glossary,
        )

    # openai / deepseek / ollama / custom OpenAI-compatible
    return OpenAITranslate(
        api_key=api_key,
        model=model or "gpt-4o-mini",
        base_url=base_url or "https://api.openai.com/v1",
        system_prompt=settings.system_prompt,
        glossary=settings.glossary,
    )


__all__ = [
    "PluginConfigStore",
    "ProviderService",
    "TranslationSettings",
    "build_translate_provider",
    "default_provider_services",
    "default_translation_prompt",
]
