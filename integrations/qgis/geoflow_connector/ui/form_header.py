"""Shared attribute-form header defined in Qt Designer."""
from pathlib import Path

from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.uic import loadUi


class FormHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        loadUi(str(Path(__file__).parent / 'designer' / 'form_header.ui'), self)
