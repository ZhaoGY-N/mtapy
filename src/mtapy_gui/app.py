"""Entry point for the mtapy GUI receiver."""

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("mtapy")
    app.setOrganizationName("mtapy")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())