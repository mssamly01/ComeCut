"""Google Gemini adapter for subtitle translation."""

from __future__ import annotations

import json
import os

from .base import TranslateProvider


class GeminiTranslate(TranslateProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-1.5-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        system_prompt: str | None = None,
        glossary: str | None = None,
    ) -> None:
        self._api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        if not self._api_key:
            raise RuntimeError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set - pass api_key=... or export the env var."
            )
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._system_prompt = (system_prompt or "").strip()
        self._glossary = (glossary or "").strip()

    def _build_prompt(self, *, text: str, target: str, source: str | None) -> str:
        if self._system_prompt:
            try:
                header = self._system_prompt.format(
                    target=target,
                    source=(source or ""),
                    glossary=self._glossary,
                )
            except Exception:
                header = self._system_prompt
        else:
            src_hint = f" from {source}" if source else ""
            header = (
                "You are a professional subtitle translator. "
                f"Translate the following text{src_hint} into {target}. "
                "Return only the translation, no explanations, no quotes, no prefixes."
            )
        if self._glossary:
            header = f"{header}\n\nGlossary:\n{self._glossary}"
        return f"{header}\n\nText:\n{text}"

    @staticmethod
    def _extract_json_array(raw: str) -> str:
        text = (raw or "").strip()
        if text.startswith("[") and text.endswith("]"):
            return text
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            return text[start : end + 1]
        return text

    def translate(self, text: str, *, target: str, source: str | None = None) -> str:
        if not text.strip():
            return text
        try:
            import requests  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "gemini translate needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        prompt = self._build_prompt(text=text, target=target, source=source)
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        url = f"{self._base_url}/models/{self._model}:generateContent?key={self._api_key}"
        r = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(body),
            timeout=120,
        )
        r.raise_for_status()
        payload = r.json() if hasattr(r, "json") else json.loads(r.text)
        for cand in payload.get("candidates") or []:
            content = cand.get("content") or {}
            for part in content.get("parts") or []:
                t = (part.get("text") or "").strip()
                if t:
                    return t
        return text

    def translate_items(
        self,
        items: list[dict[str, str]],
        *,
        target: str,
        source: str | None = None,
    ) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for row in items:
            item_id = str((row or {}).get("id") or "").strip()
            if not item_id:
                continue
            normalized.append({"id": item_id, "text": str((row or {}).get("text") or "")})
        if not normalized:
            return []

        try:
            import requests  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "gemini translate needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        prompt = self._build_prompt(
            text=(
                f"Translate every `text` value into {target}. "
                "Keep each `id` unchanged. "
                "Return ONLY a JSON array of objects in this exact shape: "
                "[{\"id\":\"...\",\"text\":\"...\"}]. "
                "Do not use markdown, comments, or extra keys.\n\n"
                f"Items:\n{json.dumps(normalized, ensure_ascii=False)}"
            ),
            target=target,
            source=source,
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        url = f"{self._base_url}/models/{self._model}:generateContent?key={self._api_key}"
        r = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(body),
            timeout=120,
        )
        r.raise_for_status()
        payload = r.json() if hasattr(r, "json") else json.loads(r.text)

        content = ""
        for cand in payload.get("candidates") or []:
            c = cand.get("content") or {}
            for part in c.get("parts") or []:
                t = (part.get("text") or "").strip()
                if t:
                    content = t
                    break
            if content:
                break

        translated_rows: list[dict[str, str]] = []
        try:
            parsed = json.loads(self._extract_json_array(content))
            if isinstance(parsed, list):
                for row in parsed:
                    if not isinstance(row, dict):
                        continue
                    item_id = str(row.get("id") or "").strip()
                    text_out = str(
                        row.get("text") or row.get("translated") or row.get("translation") or ""
                    ).strip()
                    if item_id and text_out:
                        translated_rows.append({"id": item_id, "text": text_out})
        except Exception:
            translated_rows = []

        if not translated_rows:
            return super().translate_items(normalized, target=target, source=source)

        translated_by_id = {row["id"]: row["text"] for row in translated_rows}
        out: list[dict[str, str]] = []
        for row in normalized:
            out.append(
                {
                    "id": row["id"],
                    "text": translated_by_id.get(row["id"], row["text"]),
                }
            )
        return out


__all__ = ["GeminiTranslate"]
