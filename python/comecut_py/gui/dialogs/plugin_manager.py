"""Plugin manager dialog with service + translation tabs."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from PySide6.QtCore import Qt  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..plugin_config import (
    PluginConfigStore,
    ProviderService,
    TranslationSettings,
    build_translate_provider,
    default_provider_services,
    default_translation_prompt,
)

# Kept for compatibility with existing imports/tests.
SECTIONS: dict[str, int] = {
    "API vendors": 0,
    "Subtitle Translation": 1,
    "ComfyUI": 2,
}

_SERVICE_TYPES: list[tuple[str, str]] = [
    ("OpenAI-compatible", "openai"),
    ("Gemini", "gemini"),
    ("Claude", "claude"),
    ("Ollama", "ollama"),
    ("Custom", "custom"),
]

_SERVICE_CATEGORIES: list[tuple[str, str]] = [
    ("LLM", "LLM"),
    ("API_MULTI", "API_MULTI"),
]


def _is_local_url(url: str) -> bool:
    u = (url or "").lower()
    return "localhost" in u or "127.0.0.1" in u or "0.0.0.0" in u


def _dedupe_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        v = (raw or "").strip()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _fetch_models(service: ProviderService) -> list[str]:
    try:
        import requests  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "Model sync needs the `requests` package. Install: pip install requests"
        ) from e

    base = (service.base_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("API base URL is required.")
    api_key = (service.api_key or "").strip()
    provider_type = (service.provider_type or "").strip().lower()

    def _json_get(url: str, *, headers: dict[str, str] | None = None) -> dict:
        r = requests.get(url, headers=headers or {}, timeout=20)
        r.raise_for_status()
        return r.json() if hasattr(r, "json") else {}

    if provider_type == "gemini" or "generativelanguage.googleapis.com" in base:
        if not api_key:
            raise RuntimeError("Gemini requires API key before syncing models.")
        payload = _json_get(f"{base}/models?key={api_key}")
        items = payload.get("models") or []
        names = []
        for item in items:
            name = str((item or {}).get("name") or "").strip()
            if name.startswith("models/"):
                name = name.split("/", 1)[1]
            names.append(name)
        return _dedupe_keep_order(names)

    if provider_type == "ollama":
        roots = [base]
        if base.endswith("/v1"):
            roots.insert(0, base[: -len("/v1")])
        last_error: Exception | None = None
        for root in roots:
            try:
                payload = _json_get(f"{root}/api/tags")
                models = payload.get("models") or []
                names = [str((m or {}).get("name") or "").strip() for m in models]
                out = _dedupe_keep_order(names)
                if out:
                    return out
            except Exception as e:  # pragma: no cover - network runtime branch
                last_error = e
        if last_error is not None:
            raise RuntimeError(str(last_error))
        return []

    if provider_type == "claude" or "anthropic.com" in base:
        if not api_key and not _is_local_url(base):
            raise RuntimeError("Claude requires API key before syncing models.")
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = _json_get(f"{base}/models", headers=headers)
        items = payload.get("data") or payload.get("models") or []
        names = [str((item or {}).get("id") or "").strip() for item in items]
        return _dedupe_keep_order(names)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = _json_get(f"{base}/models", headers=headers)
    items = payload.get("data") or payload.get("models") or []
    names = [str((item or {}).get("id") or (item or {}).get("name") or "").strip() for item in items]
    return _dedupe_keep_order(names)


class PluginManagerDialog(QDialog):
    """Plugin dialog mirroring HTML Plugin panel behavior."""

    def __init__(
        self,
        parent=None,
        *,
        store: PluginConfigStore | None = None,
        initial_tab: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plugin Manager")
        self.setMinimumSize(940, 620)
        self.setObjectName("pluginDialog")
        self._apply_dialog_styles()

        self._store = store or PluginConfigStore.load_default()
        self._editing_provider: ProviderService | None = None
        self._editing_is_new = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._nav = QListWidget()
        self._nav.setFixedWidth(220)
        for section_name in SECTIONS:
            self._nav.addItem(QListWidgetItem(section_name))
        outer.addWidget(self._nav)

        self._pages = QStackedWidget()
        outer.addWidget(self._pages, 1)

        self._pages.addWidget(self._build_tab_services())
        self._pages.addWidget(self._build_tab_translation())
        self._pages.addWidget(self._build_tab_comfyui())

        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)
        row = max(0, min(int(initial_tab), self._pages.count() - 1))
        self._nav.setCurrentRow(row)

        self._refresh_service_cards()
        self._load_translation_settings_into_form()

    def _apply_dialog_styles(self) -> None:
        self.setStyleSheet(
            """
            QDialog#pluginDialog {
                background: #151b26;
                color: #e8edf6;
            }

            QListWidget {
                background: #1b2230;
                border: none;
                border-right: 1px solid #2e3a4d;
            }
            QListWidget::item {
                color: #e4e8ef;
                padding: 10px 12px;
                border-left: 2px solid transparent;
                font-weight: 600;
            }
            QListWidget::item:hover {
                background: rgba(34, 211, 197, 0.06);
            }
            QListWidget::item:selected {
                background: #232c3a;
                color: #ffffff;
                border-left: 2px solid #20d0e6;
            }

            QScrollArea {
                background: transparent;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 6px 2px 6px 2px;
            }
            QScrollBar::handle:vertical {
                background: #334257;
                border-radius: 5px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3a4a60;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }

            QFrame#card, QFrame#pluginTranslationCard, QFrame#pluginProviderCard {
                background: #273142;
                border: 1px solid #334257;
                border-radius: 8px;
            }
            QFrame#pluginProviderCard:hover {
                border-color: #22d3c5;
            }
            QFrame#pluginProviderCard {
                margin: 1px;
            }
            QFrame#pluginProviderCard QLabel {
                background: transparent;
            }

            QLabel#pluginTagLabel {
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 6px 10px;
                font-weight: 600;
                color: #d9e1ee;
            }

            QLineEdit, QComboBox, QSpinBox, QTextEdit {
                background: #202938;
                border: 1px solid #334257;
                border-radius: 6px;
                color: #ecf2fb;
                padding: 6px 8px;
            }
            QComboBox {
                padding-right: 24px;
            }
            /* Editable combo uses an internal QLineEdit; force same background */
            QComboBox QLineEdit {
                background: #202938;
                border: none;
                padding: 0 2px;
                margin: 0;
                color: #ecf2fb;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 22px;
                border-left: 1px solid #334257;
                background: #253144;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            /* Keep Qt default arrow icon for compatibility; only tint dropdown area. */
            QComboBox QAbstractItemView {
                background: #202938;
                color: #ecf2fb;
                border: 1px solid #334257;
                selection-background-color: #2a3446;
                selection-color: #ecf2fb;
                outline: 0;
            }

            QSpinBox::up-button, QSpinBox::down-button {
                background: #253144;
                border-left: 1px solid #334257;
                width: 20px;
            }
            QSpinBox::up-button {
                border-top-right-radius: 6px;
            }
            QSpinBox::down-button {
                border-bottom-right-radius: 6px;
            }

            QTextEdit {
                line-height: 1.35em;
            }

            QTextEdit[readOnly="true"] {
                background: #1c2533;
                color: #d9e1ee;
            }

            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {
                border-color: #22d3c5;
            }

            QPushButton {
                background: #2a3446;
                border: 1px solid #3a4a60;
                color: #e8edf6;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: 600;
            }

            QPushButton:hover {
                border-color: #22d3c5;
            }
            QPushButton:pressed {
                background: #222b3a;
            }

            QPushButton#pluginGhost {
                background: transparent;
                border-color: #3a4a60;
            }
            QPushButton#pluginGhost:hover {
                border-color: #22d3c5;
                background: rgba(34, 211, 197, 0.06);
            }

            /* Small inline action button (e.g. edit on provider cards) */
            QPushButton#pluginMiniBtn {
                background: transparent;
                border: 1px solid #3a4a60;
                border-radius: 3px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
                color: #e8edf6;
                min-height: 18px;
            }
            QPushButton#pluginMiniBtn:hover {
                border-color: #22d3c5;
                background: rgba(34, 211, 197, 0.06);
            }

            QPushButton#pluginActionSecondary {
                background: #2a3446;
                border-color: #3a4a60;
            }

            QPushButton#pluginSave {
                background: #22d3c5;
                border-color: #22d3c5;
                color: #0e2525;
                font-weight: 700;
            }
            """
        )

    def _build_tab_services(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Global - API Model Service Management")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        self._service_count_label = QLabel("(0)")
        self._service_count_label.setStyleSheet("color: #8c93a0;")
        header.addWidget(title)
        header.addWidget(self._service_count_label)
        header.addStretch(1)

        self._btn_add_service = QPushButton("+ New Service")
        self._btn_add_service.setObjectName("pluginSave")
        self._btn_add_service.clicked.connect(lambda: self._open_service_editor(None))
        header.addWidget(self._btn_add_service)
        root.addLayout(header)

        desc = QLabel(
            "Manage provider profile, API key, base URL, model list, and connection test.\n"
            "These settings are used by subtitle translation in Text properties."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8c93a0;")
        root.addWidget(desc)

        self._service_stack = QStackedWidget()
        self._service_stack.addWidget(self._build_service_list_view())
        self._service_stack.addWidget(self._build_service_edit_view())
        root.addWidget(self._service_stack, 1)
        self._service_stack.setCurrentIndex(0)
        return page

    def _build_service_list_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self._service_cards_layout = QVBoxLayout(host)
        self._service_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._service_cards_layout.setSpacing(10)
        self._service_cards_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)
        return page

    def _build_service_edit_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        head = QHBoxLayout()
        self._btn_back_services = QPushButton("< Back")
        self._btn_back_services.clicked.connect(self._back_to_service_cards)
        head.addWidget(self._btn_back_services)
        head.addStretch(1)
        self._edit_title = QLabel("Edit Service")
        self._edit_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        head.addWidget(self._edit_title)
        layout.addLayout(head)

        form_host = QFrame()
        form_host.setObjectName("card")
        form = QFormLayout(form_host)
        form.setContentsMargins(16, 14, 16, 14)
        form.setSpacing(10)

        self._svc_name = QLineEdit()
        form.addRow("Service Name", self._svc_name)

        self._svc_type = QComboBox()
        for label, value in _SERVICE_TYPES:
            self._svc_type.addItem(label, value)
        form.addRow("Service Type", self._svc_type)

        self._svc_category = QComboBox()
        for label, value in _SERVICE_CATEGORIES:
            self._svc_category.addItem(label, value)
        form.addRow("Category", self._svc_category)

        self._svc_base_url = QLineEdit()
        self._svc_base_url.setPlaceholderText("https://api.example.com/v1")
        form.addRow("API Base URL", self._svc_base_url)

        key_row = QWidget()
        key_row_layout = QHBoxLayout(key_row)
        key_row_layout.setContentsMargins(0, 0, 0, 0)
        key_row_layout.setSpacing(6)
        self._svc_api_key = QLineEdit()
        self._svc_api_key.setPlaceholderText("Enter API key")
        self._svc_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        key_row_layout.addWidget(self._svc_api_key, 1)
        self._svc_show_key = QCheckBox("Show")
        self._svc_show_key.toggled.connect(self._toggle_service_key_visibility)
        key_row_layout.addWidget(self._svc_show_key)
        self._btn_clear_key = QPushButton("Clear")
        self._btn_clear_key.clicked.connect(lambda: self._svc_api_key.setText(""))
        key_row_layout.addWidget(self._btn_clear_key)
        form.addRow("API Key", key_row)

        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(6)
        self._svc_model = QComboBox()
        self._svc_model.setEditable(True)
        model_layout.addWidget(self._svc_model, 1)
        self._btn_sync_models = QPushButton("Sync models / GET")
        self._btn_sync_models.clicked.connect(self._sync_models_for_editor_service)
        model_layout.addWidget(self._btn_sync_models)
        form.addRow("Current Model", model_row)

        actions = QHBoxLayout()
        self._btn_test_service = QPushButton("Test connection / TEST")
        self._btn_test_service.clicked.connect(self._test_editor_service)
        actions.addWidget(self._btn_test_service)
        actions.addStretch(1)
        self._btn_delete_or_reset = QPushButton("Delete")
        self._btn_delete_or_reset.clicked.connect(self._delete_or_reset_editor_service)
        actions.addWidget(self._btn_delete_or_reset)
        form.addRow("", _wrap_layout(actions))

        layout.addWidget(form_host)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self._btn_save_service = QPushButton("Save")
        self._btn_save_service.setObjectName("primary")
        self._btn_save_service.clicked.connect(self._save_editor_service)
        foot.addWidget(self._btn_save_service)
        layout.addLayout(foot)
        layout.addStretch(1)
        return page

    def _build_tab_translation(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("Subtitle Translation Settings")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(title)

        note = QLabel(
            "These settings are used when you click Tr in TEXT PROPERTIES.\n"
            "Workflow: Main text -> translated text -> saved into Second."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #8c93a0;")
        root.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        form_card = QFrame()
        form_card.setObjectName("pluginTranslationCard")
        form_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(16, 14, 16, 14)
        form_layout.setSpacing(10)

        provider_row = QWidget()
        provider_layout = QHBoxLayout(provider_row)
        provider_layout.setContentsMargins(0, 0, 0, 0)
        provider_layout.setSpacing(6)
        self._tr_provider = QComboBox()
        self._tr_provider.setFixedHeight(32)
        self._tr_provider.currentIndexChanged.connect(self._on_translation_provider_changed)
        provider_layout.addWidget(self._tr_provider, 1)
        self._btn_open_service_tab = QPushButton("Edit provider")
        self._btn_open_service_tab.setFixedWidth(112)
        self._btn_open_service_tab.setFixedHeight(32)
        self._btn_open_service_tab.clicked.connect(self._jump_to_service_tab_for_selected_provider)
        provider_layout.addWidget(self._btn_open_service_tab)
        form_layout.addLayout(self._translation_form_row("Provider", provider_row))

        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(6)
        self._tr_model = QComboBox()
        self._tr_model.setEditable(True)
        self._tr_model.setFixedHeight(32)
        model_layout.addWidget(self._tr_model, 1)
        self._btn_sync_translation_models = QPushButton("Sync models")
        self._btn_sync_translation_models.setFixedWidth(112)
        self._btn_sync_translation_models.setFixedHeight(32)
        self._btn_sync_translation_models.clicked.connect(self._sync_models_for_translation_provider)
        model_layout.addWidget(self._btn_sync_translation_models)
        form_layout.addLayout(self._translation_form_row("Model", model_row))

        def _add_lang_items(cb: QComboBox, items: list[str]) -> None:
            cb.blockSignals(True)
            cb.clear()
            for it in items:
                cb.addItem(it)
            cb.blockSignals(False)

        # Target language
        self._tr_target = QComboBox()
        self._tr_target.setEditable(True)
        self._tr_target.setFixedHeight(32)
        _add_lang_items(
            self._tr_target,
            [
                "Vietnamese",
                "English",
                "Chinese",
                "Japanese",
                "Korean",
                "Thai",
                "Indonesian",
                "Spanish",
                "French",
                "German",
                "Portuguese",
                "Russian",
                "Arabic",
            ],
        )
        form_layout.addLayout(self._translation_form_row("Target language", self._tr_target))

        # Source language
        self._tr_source = QComboBox()
        self._tr_source.setEditable(True)
        self._tr_source.setFixedHeight(32)
        _add_lang_items(
            self._tr_source,
            [
                "Chinese",
                "Vietnamese",
                "English",
                "Japanese",
                "Korean",
                "Thai",
                "Indonesian",
                "Spanish",
                "French",
                "German",
                "Portuguese",
                "Russian",
                "Arabic",
                "auto",
            ],
        )
        form_layout.addLayout(self._translation_form_row("Source language", self._tr_source))

        self._tr_batch = QSpinBox()
        self._tr_batch.setFixedHeight(32)
        self._tr_batch.setRange(1, 200)
        form_layout.addLayout(self._translation_form_row("Batch size", self._tr_batch))

        self._tr_system_prompt = QTextEdit()
        self._tr_system_prompt.setPlaceholderText("System prompt")
        self._tr_system_prompt.setMinimumHeight(170)
        form_layout.addLayout(
            self._translation_form_row("System prompt", self._tr_system_prompt, top_align=True)
        )

        self._tr_glossary = QTextEdit()
        self._tr_glossary.setPlaceholderText("One term per line: source = target")
        self._tr_glossary.setMinimumHeight(150)
        form_layout.addLayout(self._translation_form_row("Glossary", self._tr_glossary, top_align=True))

        self._tr_test_input = QTextEdit()
        self._tr_test_input.setPlaceholderText("Type sample subtitle text to test translation.")
        self._tr_test_input.setMinimumHeight(170)
        form_layout.addLayout(self._translation_form_row("Test input", self._tr_test_input, top_align=True))

        self._tr_test_output = QTextEdit()
        self._tr_test_output.setReadOnly(True)
        self._tr_test_output.setMinimumHeight(170)
        form_layout.addLayout(
            self._translation_form_row("Test output", self._tr_test_output, top_align=True)
        )

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 8, 0, 0)
        btn_row.setSpacing(8)
        self._btn_restore_prompt = QPushButton("Restore default prompt")
        self._btn_restore_prompt.setObjectName("pluginActionSecondary")
        self._btn_restore_prompt.setFixedHeight(32)
        self._btn_restore_prompt.clicked.connect(
            lambda: self._tr_system_prompt.setPlainText(default_translation_prompt())
        )
        btn_row.addWidget(self._btn_restore_prompt)
        self._btn_test_translation = QPushButton("Test translation")
        self._btn_test_translation.setObjectName("pluginActionSecondary")
        self._btn_test_translation.setFixedHeight(32)
        self._btn_test_translation.clicked.connect(self._test_translation_with_current_form)
        btn_row.addWidget(self._btn_test_translation)
        btn_row.addStretch(1)
        self._btn_save_translation = QPushButton("Save settings")
        self._btn_save_translation.setObjectName("pluginSave")
        self._btn_save_translation.setFixedHeight(32)
        self._btn_save_translation.setFixedWidth(112)
        self._btn_save_translation.clicked.connect(self._save_translation_settings)
        btn_row.addWidget(self._btn_save_translation)
        form_layout.addLayout(btn_row)

        body_layout.addWidget(form_card)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        return page

    @staticmethod
    def _translation_form_row(label: str, field: QWidget, *, top_align: bool = False) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        lbl = QLabel(label)
        lbl.setObjectName("pluginTagLabel")
        lbl.setFixedWidth(100)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(lbl, 0, Qt.AlignmentFlag.AlignTop if top_align else Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(field, 1)
        return row

    def _build_tab_comfyui(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        lbl = QLabel("ComfyUI")
        lbl.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(lbl)
        note = QLabel(
            "ComfyUI plugin panel from HTML is reserved in PY.\n"
            "Current port keeps this tab as placeholder."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #8c93a0;")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _refresh_service_cards(self) -> None:
        _clear_layout(self._service_cards_layout)
        providers = list(self._store.providers)
        self._service_count_label.setText(f"({len(providers)})")
        if not providers:
            empty = QLabel("No providers configured.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #8c93a0;")
            self._service_cards_layout.addWidget(empty)
            self._service_cards_layout.addStretch(1)
            return

        for provider in providers:
            self._service_cards_layout.addWidget(self._build_provider_card(provider))
        self._service_cards_layout.addStretch(1)

    def _build_provider_card(self, provider: ProviderService) -> QWidget:
        card = QFrame()
        card.setObjectName("pluginProviderCard")
        card.setMinimumHeight(92)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        badge = QLabel((provider.provider_type or "custom").upper())
        badge.setStyleSheet(
            "color: #22d3c5; background: rgba(34,211,197,.12); "
            "padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700;"
        )
        top.addWidget(badge)
        top.addStretch(1)
        edit_btn = QPushButton("✎ edit")
        edit_btn.setObjectName("pluginMiniBtn")
        edit_btn.clicked.connect(lambda _=False, pid=provider.id: self._open_service_editor(pid))
        top.addWidget(edit_btn)
        layout.addLayout(top)

        name = QLabel(provider.name or provider.id)
        name.setStyleSheet("font-size: 14px; font-weight: 700;")
        layout.addWidget(name)

        model_txt = provider.current_model or (provider.models[0] if provider.models else "No model")
        meta = QLabel(f"{provider.category} - {model_txt}")
        meta.setStyleSheet("color: #8c93a0;")
        layout.addWidget(meta)

        foot = QHBoxLayout()
        key_state = "API key set" if (provider.api_key or "").strip() else "No API key"
        key_lbl = QLabel(key_state)
        key_lbl.setStyleSheet("color: #8c93a0; font-size: 11px;")
        foot.addWidget(key_lbl)
        foot.addStretch(1)
        layout.addLayout(foot)
        return card

    def _open_service_editor(self, provider_id: str | None) -> None:
        if provider_id:
            existing = self._store.get_provider(provider_id)
            if existing is None:
                QMessageBox.warning(self, "Plugin", "Provider not found.")
                return
            provider = replace(existing)
            self._editing_is_new = False
        else:
            provider = ProviderService(
                id=f"custom_{uuid4().hex[:12]}",
                name="Custom Provider",
                category="LLM",
                provider_type="openai",
                base_url="https://api.openai.com/v1",
                api_key="",
                models=[],
                current_model="",
                is_preset=False,
            )
            self._editing_is_new = True

        self._editing_provider = provider
        self._edit_title.setText("New Service" if self._editing_is_new else "Edit Service")
        self._svc_name.setText(provider.name)
        self._set_combo_data(self._svc_type, provider.provider_type or "openai")
        self._set_combo_data(self._svc_category, provider.category or "LLM")
        self._svc_base_url.setText(provider.base_url)
        self._svc_api_key.setText(provider.api_key)
        self._svc_show_key.setChecked(False)
        self._toggle_service_key_visibility(False)
        self._set_model_combo_items(
            self._svc_model,
            provider.models,
            provider.current_model,
        )
        self._btn_delete_or_reset.setText("Reset preset" if provider.is_preset else "Delete")
        self._service_stack.setCurrentIndex(1)

    def _toggle_service_key_visibility(self, checked: bool) -> None:
        self._svc_api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def _back_to_service_cards(self) -> None:
        self._editing_provider = None
        self._service_stack.setCurrentIndex(0)

    def _collect_editor_service(self) -> ProviderService:
        if self._editing_provider is None:
            raise RuntimeError("No provider in edit mode.")
        provider = replace(self._editing_provider)
        provider.name = self._svc_name.text().strip()
        provider.provider_type = str(self._svc_type.currentData() or "openai")
        provider.category = str(self._svc_category.currentData() or "LLM")
        provider.base_url = self._svc_base_url.text().strip()
        provider.api_key = self._svc_api_key.text().strip()
        model_values = [self._svc_model.itemText(i) for i in range(self._svc_model.count())]
        model_values.append(self._svc_model.currentText())
        provider.models = _dedupe_keep_order(model_values)
        provider.current_model = (self._svc_model.currentText() or "").strip()
        if not provider.name:
            raise RuntimeError("Service name is required.")
        if not provider.base_url:
            raise RuntimeError("API base URL is required.")
        return provider

    def _save_editor_service(self) -> None:
        try:
            provider = self._collect_editor_service()
            self._store.upsert_provider(provider)
            self._store.save()
            self._refresh_service_cards()
            self._reload_translation_provider_options()
            self._back_to_service_cards()
            QMessageBox.information(self, "Plugin", "Service saved.")
        except Exception as e:
            QMessageBox.warning(self, "Save service failed", str(e))

    def _delete_or_reset_editor_service(self) -> None:
        if self._editing_provider is None:
            return
        provider = self._collect_editor_service()
        if provider.is_preset:
            defaults = {p.id: p for p in default_provider_services()}
            default = defaults.get(provider.id)
            if default is not None:
                provider.base_url = default.base_url
                provider.models = list(default.models)
                provider.current_model = default.current_model
            provider.api_key = ""
            self._store.upsert_provider(provider)
            self._store.save()
            QMessageBox.information(self, "Plugin", "Preset was reset.")
        else:
            self._store.delete_provider(provider.id)
            self._store.save()
            QMessageBox.information(self, "Plugin", "Service deleted.")
        self._refresh_service_cards()
        self._reload_translation_provider_options()
        self._back_to_service_cards()

    def _sync_models_for_editor_service(self) -> None:
        try:
            provider = self._collect_editor_service()
            models = _fetch_models(provider)
            if not models:
                raise RuntimeError("No models returned from provider.")
            self._set_model_combo_items(self._svc_model, models, models[0])
            QMessageBox.information(self, "Plugin", f"Fetched {len(models)} models.")
        except Exception as e:
            QMessageBox.warning(self, "Sync models failed", str(e))

    def _test_editor_service(self) -> None:
        try:
            provider = self._collect_editor_service()
            models = _fetch_models(provider)
            count = len(models)
            msg = f"Connection OK. Models: {count}" if count else "Connection OK."
            QMessageBox.information(self, "Plugin", msg)
        except Exception as e:
            QMessageBox.warning(self, "Connection test failed", str(e))

    def _load_translation_settings_into_form(self) -> None:
        self._reload_translation_provider_options()
        tr = self._store.translation
        target = (tr.target_language or "").strip() or "Vietnamese"
        source = (tr.source_language or "").strip() or "Chinese"
        self._tr_target.setCurrentText(target)
        self._tr_source.setCurrentText(source)
        self._tr_batch.setValue(max(1, int(tr.batch_size or 10)))
        self._tr_system_prompt.setPlainText(
            (tr.system_prompt or "").strip() or default_translation_prompt()
        )
        self._tr_glossary.setPlainText(tr.glossary or "")
        self._tr_test_input.setPlainText("Hello, welcome to ComeCut.")
        self._tr_test_output.clear()

    def _reload_translation_provider_options(self) -> None:
        providers = [p for p in self._store.providers if p.category in {"LLM", "API_MULTI"}]
        self._tr_provider.blockSignals(True)
        self._tr_provider.clear()
        for provider in providers:
            self._tr_provider.addItem(provider.name, provider.id)
        target_id = self._store.translation.provider_id
        idx = 0
        if target_id:
            found = self._tr_provider.findData(target_id)
            if found >= 0:
                idx = found
        if self._tr_provider.count() > 0:
            self._tr_provider.setCurrentIndex(idx)
        self._tr_provider.blockSignals(False)
        self._on_translation_provider_changed()

    def _current_translation_provider(self) -> ProviderService | None:
        provider_id = str(self._tr_provider.currentData() or "")
        if not provider_id:
            return None
        return self._store.get_provider(provider_id)

    def _on_translation_provider_changed(self) -> None:
        provider = self._current_translation_provider()
        if provider is None:
            self._set_model_combo_items(self._tr_model, [], "")
            return
        preferred = (
            self._store.translation.current_model or ""
        )
        if preferred and provider.models and preferred not in provider.models:
            preferred = provider.current_model or provider.models[0]
        if not preferred:
            preferred = provider.current_model or (provider.models[0] if provider.models else "")
        self._set_model_combo_items(self._tr_model, provider.models, preferred)

    def _sync_models_for_translation_provider(self) -> None:
        provider = self._current_translation_provider()
        if provider is None:
            QMessageBox.warning(self, "Plugin", "No provider selected.")
            return
        try:
            models = _fetch_models(provider)
            if not models:
                raise RuntimeError("No models returned from provider.")
            provider.models = models
            provider.current_model = models[0]
            self._store.upsert_provider(provider)
            self._set_model_combo_items(self._tr_model, models, models[0])
            QMessageBox.information(self, "Plugin", f"Fetched {len(models)} models.")
        except Exception as e:
            QMessageBox.warning(self, "Sync models failed", str(e))

    def _translation_settings_from_form(self) -> TranslationSettings:
        provider_id = str(self._tr_provider.currentData() or "")
        source_text = (self._tr_source.currentText() or "").strip()
        # Keep empty for "auto" to preserve legacy behavior.
        src_norm = "" if source_text.lower() in {"", "auto"} else source_text
        return TranslationSettings(
            provider_id=provider_id,
            current_model=(self._tr_model.currentText() or "").strip(),
            batch_size=max(1, int(self._tr_batch.value())),
            target_language=(self._tr_target.currentText() or "").strip() or "Vietnamese",
            source_language=src_norm,
            system_prompt=(self._tr_system_prompt.toPlainText() or "").strip()
            or default_translation_prompt(),
            glossary=(self._tr_glossary.toPlainText() or "").strip(),
        )

    def _save_translation_settings(self) -> None:
        try:
            settings = self._translation_settings_from_form()
            provider = self._store.get_provider(settings.provider_id)
            if provider is None:
                raise RuntimeError("Selected provider is missing.")
            provider.current_model = settings.current_model
            if settings.current_model and settings.current_model not in provider.models:
                provider.models = _dedupe_keep_order(provider.models + [settings.current_model])
            self._store.upsert_provider(provider)
            self._store.translation = settings
            self._store.save()
            QMessageBox.information(self, "Plugin", "Translation settings saved.")
        except Exception as e:
            QMessageBox.warning(self, "Save translation settings failed", str(e))

    def _test_translation_with_current_form(self) -> None:
        try:
            provider = self._current_translation_provider()
            if provider is None:
                raise RuntimeError("No provider selected.")
            settings = self._translation_settings_from_form()
            test_text = (self._tr_test_input.toPlainText() or "").strip()
            if not test_text:
                raise RuntimeError("Please enter test input text.")
            runtime_provider = replace(provider)
            runtime_provider.current_model = settings.current_model
            if settings.current_model and settings.current_model not in runtime_provider.models:
                runtime_provider.models = _dedupe_keep_order(
                    runtime_provider.models + [settings.current_model]
                )
            translator = build_translate_provider(runtime_provider, settings)
            translated = translator.translate(
                test_text,
                target=settings.target_language,
                source=settings.source_language or None,
            )
            self._tr_test_output.setPlainText((translated or "").strip())
        except Exception as e:
            QMessageBox.warning(self, "Test translation failed", str(e))

    def _jump_to_service_tab_for_selected_provider(self) -> None:
        provider_id = str(self._tr_provider.currentData() or "")
        self._nav.setCurrentRow(SECTIONS["API vendors"])
        if provider_id:
            self._open_service_editor(provider_id)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    @staticmethod
    def _set_model_combo_items(combo: QComboBox, models: list[str], current: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        for model in _dedupe_keep_order(models):
            combo.addItem(model)
        current_text = (current or "").strip()
        if current_text and combo.findText(current_text) < 0:
            combo.addItem(current_text)
        if combo.count() > 0:
            idx = combo.findText(current_text) if current_text else 0
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            combo.setEditText(current_text)
        combo.blockSignals(False)


def _wrap_layout(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
            continue
        child_layout = item.layout()
        if child_layout is not None:
            while child_layout.count():
                child_item = child_layout.takeAt(0)
                child_widget = child_item.widget()
                if child_widget is not None:
                    child_widget.deleteLater()


__all__ = ["PluginManagerDialog", "SECTIONS"]
