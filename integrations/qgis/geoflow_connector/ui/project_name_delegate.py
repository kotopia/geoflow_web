# 제목: 프로젝트 목록 표시
# 기능: 선택 강조, 코드 축소, 이름 표시와 포커스 테두리 제거
from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QFont, QFontMetrics, QPalette
from qgis.PyQt.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication


class ProjectNameDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.state &= ~QStyle.StateFlag.State_HasFocus
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        opt.font.setBold(selected)
        data = index.data(Qt.ItemDataRole.UserRole) or {}
        code = '[' + str(data.get('code') or '') + '] '
        name = str(data.get('name') or '')
        opt.text = ''
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        rect = opt.rect.adjusted(8, 4, -8, -4)
        small = QFont(opt.font)
        if small.pointSizeF() > 0:
            small.setPointSizeF(max(1, small.pointSizeF() - 1))
        else:
            small.setPixelSize(max(1, small.pixelSize() - 1))
        metrics = QFontMetrics(opt.font)
        code_width = QFontMetrics(small).horizontalAdvance(code)
        baseline = rect.y() + (rect.height() - metrics.height()) // 2 + metrics.ascent()
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(opt.palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text))
        painter.setFont(small)
        painter.drawText(rect.x(), baseline, code)
        painter.setFont(opt.font)
        painter.drawText(rect.x() + code_width, baseline, metrics.elidedText(name, Qt.TextElideMode.ElideRight, max(0, rect.width() - code_width)))
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), QFontMetrics(option.font).height() + 16))
