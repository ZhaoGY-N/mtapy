"""Modern, adaptive theme (light/dark) for the mtapy GUI."""

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

# --------------------------------------------------------------------------
# Color palettes (light / dark)
# --------------------------------------------------------------------------

LIGHT = {
    "window": "#ffffff",
    "card": "#f8fafc",
    "border": "#e2e8f0",
    "text": "#0f172a",
    "text_dim": "#64748b",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "success": "#16a34a",
    "error": "#dc2626",
    "row_alt": "#f1f5f9",
}

DARK = {
    "window": "#0f1115",
    "card": "#1a1d23",
    "border": "#2a2e37",
    "text": "#e5e7eb",
    "text_dim": "#9ca3af",
    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
    "success": "#4ade80",
    "error": "#f87171",
    "row_alt": "#1e222a",
}


def is_dark_mode() -> bool:
    """Detect whether the system is currently in dark mode."""
    app = QApplication.instance()
    if app is None:
        return False
    window_color = app.palette().color(QPalette.ColorRole.Window)
    return window_color.lightness() < 128


def _accent_button_qss(c: dict) -> str:
    """Primary (filled) button style."""
    return f"""
    QPushButton#primary {{
        background-color: {c["accent"]};
        color: #ffffff;
        border: none;
        border-radius: 8px;
        padding: 8px 18px;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background-color: {c["accent_hover"]}; }}
    QPushButton#primary:disabled {{ background-color: {c["border"]}; color: {c["text_dim"]}; }}
    """


def build_stylesheet(dark: bool) -> str:
    """Build the application-wide stylesheet for light or dark mode."""
    c = DARK if dark else LIGHT
    return f"""
    * {{ font-family: "Noto Sans", "Segoe UI", "Ubuntu", sans-serif; }}
    QMainWindow, QWidget#central {{ background-color: {c["window"]}; }}

    QLabel {{ color: {c["text"]}; }}
    QLabel#dim {{ color: {c["text_dim"]}; font-size: 12px; }}

    QGroupBox {{
        background-color: {c["card"]};
        border: 1px solid {c["border"]};
        border-radius: 10px;
        margin-top: 14px;
        padding: 12px 14px;
        font-weight: 600;
        color: {c["text"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        background-color: {c["card"]};
        border-radius: 4px;
    }}

    QPushButton {{
        background-color: transparent;
        color: {c["text"]};
        border: 1px solid {c["border"]};
        border-radius: 8px;
        padding: 7px 16px;
    }}
    QPushButton:hover {{ background-color: {c["row_alt"]}; }}
    QPushButton:disabled {{ color: {c["text_dim"]}; }}

    {_accent_button_qss(c)}

    QLineEdit {{
        background-color: {c["window"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        border-radius: 8px;
        padding: 6px 10px;
    }}
    QLineEdit:focus {{ border-color: {c["accent"]}; }}

    QCheckBox {{ color: {c["text"]}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border-radius: 4px;
        border: 1px solid {c["border"]};
        background-color: {c["window"]};
    }}
    QCheckBox::indicator:checked {{
        background-color: {c["accent"]};
        border-color: {c["accent"]};
    }}

    QTableWidget {{
        background-color: {c["window"]};
        alternate-background-color: {c["row_alt"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        border-radius: 10px;
        gridline-color: transparent;
        selection-background-color: {c["accent"]};
        selection-color: #ffffff;
    }}
    QHeaderView::section {{
        background-color: {c["card"]};
        color: {c["text_dim"]};
        border: none;
        border-bottom: 1px solid {c["border"]};
        padding: 6px 8px;
        font-weight: 600;
    }}
    QTableWidget::item {{ padding: 4px; }}

    QProgressBar {{
        background-color: {c["card"]};
        border: 1px solid {c["border"]};
        border-radius: 6px;
        text-align: center;
        color: {c["text"]};
        height: 18px;
    }}
    QProgressBar::chunk {{
        background-color: {c["accent"]};
        border-radius: 5px;
    }}

    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {c["border"]}; border-radius: 5px; min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c["text_dim"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def apply_theme(app: QApplication) -> bool:
    """Apply the adaptive theme to the app. Returns True if dark mode."""
    dark = is_dark_mode()
    app.setStyleSheet(build_stylesheet(dark))
    return dark
