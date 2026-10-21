"""One replaceable, non-blocking message per Dynamic Form."""
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QLabel


class InlineMessage(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def display(self, text, level='warning'):
        self.timer.stop()
        color = {'success': '#287a3e', 'warning': '#a65e00', 'error': '#b83232'}[level]
        self.setStyleSheet(f'QLabel {{ color: {color}; padding: 6px; }}')
        self.setText(text)
        self.show()
        self.timer.start(2800)


def depth_feedback(result, radius_m):
    if result.get('skipped'):
        return '기존 심도값을 유지했습니다.', 'success'
    if result.get('ok'):
        text = f"✓ 심도값 {result['depth']:.3f}m를 계산했습니다."
        if result.get('requires_review'):
            return text + ' 음수 결과를 확인하세요.', 'warning'
        return text, 'success'
    reason = result.get('reason')
    if reason == 'no_nearby_survey':
        return f'⚠ 반경 {radius_m:.1f}m 이내에 심도 계산에 사용할 측량점이 없습니다.', 'warning'
    if reason in {'no_height_candidate', 'no_nearby_h', 'out_of_radius'}:
        return f'⚠ 반경 {radius_m:.1f}m 이내에 표고 기준점(H)을 찾지 못했습니다.', 'warning'
    if reason in {'invalid_source_z', 'source_z_missing'}:
        return '⚠ 측량점의 Z값을 사용할 수 없습니다.', 'error'
    if reason == 'h_z_missing':
        return '⚠ 표고 기준점(H)의 Z값을 사용할 수 없습니다.', 'error'
    return '⚠ 심도값을 계산하지 못했습니다.', 'error'


def show_depth_feedback(page, result, radius_m):
    message = getattr(page, 'depth_message', None)
    if message is None:
        page.depth_message = message = InlineMessage(page.form)
        page.form.add_behavior_widget(message)
        page.form.valuesLoaded.connect(message.hide)
    message.display(*depth_feedback(result, radius_m))
