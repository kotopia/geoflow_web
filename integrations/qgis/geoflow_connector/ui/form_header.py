# 제목: 속성폼 공통 Header
# 기능: Designer 기반 작업자·작업일·저장·참조코드 새로고침 영역을 로드
"""Shared attribute-form header defined in Qt Designer."""
from pathlib import Path

from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.uic import loadUi


class FormHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        loadUi(str(Path(__file__).parent / 'designer' / 'form_header.ui'), self)
