# 제목: ui/layer_name_delegate.py
# 기능: 레이어 이름 옆 객체 수 표시용 Qt delegate
"""Paint a small feature count without placing interactive widgets over the row."""
from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QFont, QFontMetrics, QPalette
from qgis.PyQt.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QStyledItemDelegate

COUNT_ROLE = int(Qt.ItemDataRole.UserRole) + 1
COUNT_FONT_RATIO = 0.8

class LayerNameDelegate(QStyledItemDelegate):
    @staticmethod
    def count_font(font):
        small = QFont(font)
        if font.pointSizeF() > 0:
            small.setPointSizeF(font.pointSizeF() * COUNT_FONT_RATIO)
        else:
            small.setPixelSize(max(1, round(font.pixelSize() * COUNT_FONT_RATIO)))
        return small

    def paint(self, painter, option, index):
        count = index.data(COUNT_ROLE)
        if count is None:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        label, opt.text = opt.text, ''
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget).adjusted(2, 0, -2, 0)
        small = self.count_font(opt.font)
        normal_metrics, small_metrics = QFontMetrics(opt.font), QFontMetrics(small)
        suffix = f' ({count})'
        label = normal_metrics.elidedText(label, Qt.TextElideMode.ElideRight,
            max(0, rect.width() - small_metrics.horizontalAdvance(suffix)))
        baseline = rect.y() + (rect.height() - normal_metrics.height()) // 2 + normal_metrics.ascent()
        painter.save()
        painter.setClipRect(option.rect)
        role = QPalette.ColorRole.HighlightedText if opt.state & QStyle.StateFlag.State_Selected else QPalette.ColorRole.Text
        painter.setPen(opt.palette.color(role))
        painter.setFont(opt.font)
        painter.drawText(rect.x(), baseline, label)
        painter.setFont(small)
        painter.drawText(rect.x() + normal_metrics.horizontalAdvance(label), baseline, suffix)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        count = index.data(COUNT_ROLE)
        if count is not None:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            width = QFontMetrics(opt.font).horizontalAdvance(opt.text)
            width += QFontMetrics(self.count_font(opt.font)).horizontalAdvance(f' ({count})') + 8
            return QSize(max(size.width(), width), size.height())
        return size
