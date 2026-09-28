# 제목: 속성폼 공통 Header
# 기능: Designer 기반 작업자·작업일·저장·참조코드 새로고침 영역을 로드
"""Shared attribute-form header defined in Qt Designer."""
from pathlib import Path

from qgis.PyQt.QtWidgets import QPushButton, QToolButton, QWidget
from qgis.PyQt.uic import loadUi


class FormHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        loadUi(str(Path(__file__).parent / 'designer' / 'form_header.ui'), self)
        self.layerNameLabel = self.titleLabel
        self.layerNameLabel.setObjectName('layerNameLabel')
        index = self.actionsLayout.indexOf(self.layerNameLabel)
        self.layoutButton = QPushButton('폼 배치', self)
        self.layoutButton.setObjectName('layoutButton')
        self.layoutButton.setToolTip('현재 레이어의 폼 배치를 편집합니다.')
        self.actionsLayout.insertWidget(index + 1, self.layoutButton)
        save_index = self.actionsLayout.indexOf(self.pushButtonUpdate)
        self.photoButton = QToolButton(self)
        self.photoButton.setObjectName('photoButton')
        self.photoButton.setText('사진')
        self.photoButton.setToolTip('현재 객체의 다음 사진을 추가합니다.')
        self.photoButton.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.photoButton.setEnabled(False)
        self.photoButton.setVisible(False)
        self.actionsLayout.insertWidget(save_index, self.photoButton)
        self.dateEdit.setEnabled(True)
        self.dateEdit.setReadOnly(True)
        self.dateEdit.setCalendarPopup(False)
        self.lineEditWorker.setEnabled(True)
        self.lineEditWorker.setReadOnly(True)
