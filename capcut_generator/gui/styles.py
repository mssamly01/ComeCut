"""
GUI Styling for CapCut Draft Generator
Separated styles for better maintainability
"""

APP_STYLES = """
QMainWindow {
    background-color: #2b2b2b;
    color: #ffffff;
}

QGroupBox {
    font-weight: bold;
    border: 2px solid #555555;
    border-radius: 8px;
    margin-top: 1ex;
    padding-top: 10px;
    background-color: #3a3a3a;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px 0 5px;
    color: #00d4ff;
    font-size: 14px;
}

QLineEdit {
    border: 2px solid #555555;
    border-radius: 4px;
    padding: 8px;
    background-color: #404040;
    color: #ffffff;
    font-size: 11px;
}

QLineEdit:focus {
    border: 2px solid #00d4ff;
}

QLineEdit:hover {
    border: 2px solid #777777;
}

QPushButton {
    background-color: #4CAF50;
    border: none;
    color: white;
    padding: 8px 16px;
    text-align: center;
    font-size: 12px;
    border-radius: 4px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #45a049;
}

QPushButton:pressed {
    background-color: #3d8b40;
}

QPushButton:disabled {
    background-color: #666666;
    color: #999999;
}

QLabel {
    color: #ffffff;
    font-size: 11px;
}

QTextEdit, QPlainTextEdit {
    background-color: #1e1e1e;
    color: #00ff00;
    border: 2px solid #555555;
    border-radius: 4px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 10px;
    selection-background-color: #0078d7;
}

QTextEdit:focus, QPlainTextEdit:focus {
    border: 2px solid #00d4ff;
}

QCheckBox {
    color: #ffffff;
    font-size: 11px;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid #555555;
    background-color: #404040;
}

QCheckBox::indicator:checked {
    background-color: qradialgradient(
        cx:0.5, cy:0.5, fx:0.5, fy:0.5, radius:0.5,
        stop:0.4 #00d4ff, stop:0.5 #404040
    );
    border: 2px solid #555555;
}

QCheckBox::indicator:hover {
    border: 2px solid #00d4ff;
}

QCheckBox::indicator:checked:hover {
    border: 2px solid #00d4ff;
}

QRadioButton {
    color: #ffffff; /* Đặt màu chữ thành trắng */
    font-size: 11px;
    spacing: 8px;
    padding: 2px 0px; /* Thêm chút đệm cho đẹp */
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid #555555;
    background-color: #404040;
}

QRadioButton::indicator:checked {
    background-color: qradialgradient(
        cx:0.5, cy:0.5, fx:0.5, fy:0.5, radius:0.6,
        stop:0.4 #00d4ff, stop:0.5 #404040
    );
}

QRadioButton::indicator:hover {
    border: 2px solid #00d4ff;
}

QListWidget {
    background-color: #2c313c;
    color: #d1d1d1;
    border: 2px solid #555555;
    border-radius: 4px;
    padding: 5px;
    font-size: 11px;
    alternate-background-color: #363b47;
}

QListWidget::item {
    padding: 5px;
    border-radius: 2px;
    margin: 1px 0px;
}

QListWidget::item:hover {
    background-color: #3a3f4b;
    color: #ffffff;
}

QListWidget::item:selected {
    background-color: #0078d7;
    color: #ffffff;
    border: 1px solid #005a9e;
}

QListWidget::item:selected:active {
    background-color: #106ebe;
}

QListWidget:focus {
    border: 2px solid #00d4ff;
}

QSplitter::handle {
    background-color: #555555;
    height: 2px;
}

QSplitter::handle:hover {
    background-color: #777777;
}

QSplitter::handle:pressed {
    background-color: #00d4ff;
}

QScrollBar:vertical {
    background-color: #3a3a3a;
    width: 12px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background-color: #555555;
    border-radius: 6px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #777777;
}

QScrollBar::handle:vertical:pressed {
    background-color: #00d4ff;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background-color: #3a3a3a;
    height: 12px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background-color: #555555;
    border-radius: 6px;
    min-width: 20px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #777777;
}

QScrollBar::handle:horizontal:pressed {
    background-color: #00d4ff;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}

/* Message Box Styling */
QMessageBox {
    background-color: #2b2b2b;
    color: #ffffff;
}

QMessageBox QLabel {
    color: #ffffff;
    font-size: 12px;
}

QMessageBox QPushButton {
    min-width: 80px;
    min-height: 25px;
    padding: 5px 15px;
    margin: 2px;
}

/* File Dialog Styling */
QFileDialog {
    background-color: #2b2b2b;
    color: #ffffff;
}

QFileDialog QListView {
    background-color: #3a3a3a;
    color: #ffffff;
    border: 1px solid #555555;
}

QFileDialog QTreeView {
    background-color: #3a3a3a;
    color: #ffffff;
    border: 1px solid #555555;
}

/* Progress Bar Styling */
QProgressBar {
    border: 2px solid #555555;
    border-radius: 5px;
    background-color: #3a3a3a;
    text-align: center;
    color: #ffffff;
    font-weight: bold;
}

QProgressBar::chunk {
    background-color: #4CAF50;
    border-radius: 3px;
}

/* Menu Styling */
QMenuBar {
    background-color: #3a3a3a;
    color: #ffffff;
    border-bottom: 1px solid #555555;
}

QMenuBar::item {
    padding: 5px 10px;
    background: transparent;
}

QMenuBar::item:selected {
    background-color: #555555;
}

QMenu {
    background-color: #3a3a3a;
    color: #ffffff;
    border: 1px solid #555555;
}

QMenu::item {
    padding: 5px 20px;
}

QMenu::item:selected {
    background-color: #555555;
}

/* Tooltip Styling */
QToolTip {
    background-color: #2b2b2b;
    color: #ffffff;
    border: 1px solid #555555;
    padding: 5px;
    border-radius: 3px;
    font-size: 11px;
}

/* Status Bar Styling */
QStatusBar {
    background-color: #3a3a3a;
    color: #ffffff;
    border-top: 1px solid #555555;
}

QStatusBar::item {
    border: none;
}

/* Tab Widget Styling */
QTabWidget::pane {
    border: 2px solid #555555;
    background-color: #3a3a3a;
}

QTabBar::tab {
    background-color: #2b2b2b;
    color: #ffffff;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background-color: #3a3a3a;
    border-bottom: 2px solid #00d4ff;
}

QTabBar::tab:hover:!selected {
    background-color: #555555;
}

/* Table Styling */
QTableWidget {
    background-color: #3a3a3a;
    color: #ffffff;
    border: 2px solid #555555;
    gridline-color: #555555;
    selection-background-color: #0078d7;
}

QTableWidget::item {
    padding: 5px;
    border: none;
}

QTableWidget::item:selected {
    background-color: #0078d7;
}

QHeaderView::section {
    background-color: #2b2b2b;
    color: #ffffff;
    padding: 8px;
    border: 1px solid #555555;
    font-weight: bold;
}

QHeaderView::section:hover {
    background-color: #555555;
}

/* Combo Box Styling */
QComboBox {
    border: 2px solid #555555;
    border-radius: 4px;
    padding: 5px 10px;
    background-color: #404040;
    color: #ffffff;
    font-size: 11px;
}

QComboBox:focus {
    border: 2px solid #00d4ff;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox::down-arrow {
    border: 2px solid #777777;
    border-radius: 2px;
    width: 6px;
    height: 6px;
    background-color: #777777;
}

QComboBox QAbstractItemView {
    background-color: #3a3a3a;
    color: #ffffff;
    border: 2px solid #555555;
    selection-background-color: #0078d7;
}

/* Spin Box Styling */
QSpinBox, QDoubleSpinBox {
    border: 2px solid #555555;
    border-radius: 4px;
    padding: 5px;
    background-color: #404040;
    color: #ffffff;
    font-size: 11px;
}

QSpinBox:focus, QDoubleSpinBox:focus {
    border: 2px solid #00d4ff;
}

QSpinBox::up-button, QDoubleSpinBox::up-button {
    background-color: #4a4a4a;
    border-top-right-radius: 4px;
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #555;
}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {
    background-color: #555555;
}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("gui/up_arrow.svg");
    width: 10px;
    height: 10px;
}

QSpinBox::down-button, QDoubleSpinBox::down-button {
    background-color: #4a4a4a;
    border-bottom-right-radius: 4px;
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border-left: 1px solid #555;
}

QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #555555;
}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("gui/down_arrow.svg");
    width: 10px;
    height: 10px;
}
"""

# Additional style variants
DARK_THEME_VARIANTS = {
    "green": {
        "primary": "#4CAF50",
        "primary_hover": "#45a049",
        "primary_pressed": "#3d8b40",
        "accent": "#00d4ff"
    },
    "blue": {
        "primary": "#2196F3",
        "primary_hover": "#1976D2",
        "primary_pressed": "#0d47a1",
        "accent": "#00bcd4"
    },
    "purple": {
        "primary": "#9C27B0",
        "primary_hover": "#7B1FA2",
        "primary_pressed": "#4A148C",
        "accent": "#e91e63"
    },
    "orange": {
        "primary": "#FF9800",
        "primary_hover": "#F57C00",
        "primary_pressed": "#E65100",
        "accent": "#ff5722"
    }
}

def get_themed_styles(theme_name: str = "green") -> str:
    """Get styles with specific color theme"""
    if theme_name not in DARK_THEME_VARIANTS:
        theme_name = "green"
    
    theme = DARK_THEME_VARIANTS[theme_name]
    
    # Replace color placeholders in base styles
    themed_styles = APP_STYLES.replace("#4CAF50", theme["primary"])
    themed_styles = themed_styles.replace("#45a049", theme["primary_hover"])
    themed_styles = themed_styles.replace("#3d8b40", theme["primary_pressed"])
    themed_styles = themed_styles.replace("#00d4ff", theme["accent"])
    
    return themed_styles

# Special styles for specific components
BUTTON_STYLES = {
    "success": """
        QPushButton {
            background-color: #4CAF50;
            color: white;
            border: none;
            padding: 10px 20px;
            font-weight: bold;
            border-radius: 5px;
        }
        QPushButton:hover {
            background-color: #45a049;
        }
        QPushButton:pressed {
            background-color: #3d8b40;
        }
    """,
    
    "danger": """
        QPushButton {
            background-color: #f44336;
            color: white;
            border: none;
            padding: 10px 20px;
            font-weight: bold;
            border-radius: 5px;
        }
        QPushButton:hover {
            background-color: #d32f2f;
        }
        QPushButton:pressed {
            background-color: #b71c1c;
        }
    """,
    
    "warning": """
        QPushButton {
            background-color: #ff9800;
            color: white;
            border: none;
            padding: 10px 20px;
            font-weight: bold;
            border-radius: 5px;
        }
        QPushButton:hover {
            background-color: #f57c00;
        }
        QPushButton:pressed {
            background-color: #e65100;
        }
    """,
    
    "info": """
        QPushButton {
            background-color: #2196f3;
            color: white;
            border: none;
            padding: 10px 20px;
            font-weight: bold;
            border-radius: 5px;
        }
        QPushButton:hover {
            background-color: #1976d2;
        }
        QPushButton:pressed {
            background-color: #0d47a1;
        }
    """
}

# Console/Log specific styles
CONSOLE_STYLES = {
    "terminal": """
        QTextEdit {
            background-color: #0a0a0a;
            color: #00ff00;
            font-family: 'Courier New', 'Consolas', monospace;
            font-size: 11px;
            border: 2px solid #333333;
            border-radius: 4px;
        }
    """,
    
    "ide": """
        QTextEdit {
            background-color: #1e1e1e;
            color: #d4d4d4;
            font-family: 'Consolas', 'Source Code Pro', monospace;
            font-size: 11px;
            border: 2px solid #555555;
            border-radius: 4px;
        }
    """,
    
    "matrix": """
        QTextEdit {
            background-color: #000000;
            color: #00ff41;
            font-family: 'Courier New', monospace;
            font-size: 10px;
            border: 2px solid #003300;
            border-radius: 4px;
        }
    """
}

def apply_button_style(button, style_type: str):
    """Apply specific button style"""
    if style_type in BUTTON_STYLES:
        button.setStyleSheet(BUTTON_STYLES[style_type])

def apply_console_style(text_widget, style_type: str):
    """Apply specific console style"""
    if style_type in CONSOLE_STYLES:
        text_widget.setStyleSheet(CONSOLE_STYLES[style_type])