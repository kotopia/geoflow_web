# 제목: ui/presentation.py
# 기능: 아이콘/레이어/전체 업무폼 모드와 Dock 폭 조정
"""Dock presentation only: no authentication, field mapping or project mutation."""
from enum import IntEnum
from qgis.PyQt.QtCore import QObject, Qt, QTimer, QEvent
from qgis.PyQt.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QToolButton, QSizePolicy, QLayout, QMenu


class PanelMode(IntEnum):
    ICONS = 0
    LAYERS = 1
    FULL = 2


# Logical pixels. The original form is scroll-hosted when the screen is smaller.
WIDTHS = dict(icons=46, boundary=16, layers=200, form=400, selector=430, map_reserve=220)


class PanelPresentation(QObject):
    def __init__(self, engine, root):
        super().__init__(engine.dock)
        content = root.content
        self.engine, self.content = engine, content
        self.mode = PanelMode.LAYERS
        self.closed = False
        self.work = None
        self.root = root
        self.rail = root.rail
        self.rail.setFixedWidth(WIDTHS['icons'])
        root.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.buttons = {}
        def button(key, slot):
            b = getattr(root, 'GeoFlowRail_' + key)
            b.clicked.connect(slot)
            self.buttons[key] = b
        button('projects', engine.show_projects)
        button('select', lambda: self.invoke('set_select_map_tool'))
        button('save', lambda: self.invoke('save_current'))
        button('zoom', lambda: engine.zoom_workspace_layer())
        button('drafts', lambda: self.invoke('show_retained'))
        button('logout', engine.logout_requested)
        button('hide', engine.dock.hide)
        menu = QMenu(root.moreActionsButton)
        for title, method, tip in (
            ('연결 진단', 'show_reference_diagnostics', '필드·참조코드·작업자 연결 상태를 확인합니다.'),
            ('보존 입력', 'show_retained', '프로젝트나 객체 전환 중 보존된 폼 입력을 확인합니다. 미전송 큐와는 별개입니다.'),
        ):
            action = menu.addAction(title)
            action.setToolTip(tip)
            action.triggered.connect(lambda checked=False, method=method: self.invoke(method))
        menu.setToolTipsVisible(True)
        menu.aboutToShow.connect(self._update_business_menu)
        root.moreActionsButton.setMenu(menu)
        self.edge = root.panel_edge
        self.edge.clicked.connect(self.step)
        root.dock_layout.setStretch(root.dock_layout.indexOf(content), 1)
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        content.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        engine.stack.setMinimumWidth(0)
        engine.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        # Native title text/float controls otherwise impose a wider collapsed minimum.
        title = QWidget()
        title.setFixedHeight(0)
        engine.dock.setTitleBarWidget(title)
        engine.dock.setWidget(self.root)
        engine.iface.mainWindow().installEventFilter(self)

    def eventFilter(self, watched, event):
        if not self.closed and event.type() == QEvent.Type.Resize and hasattr(self, '_target'):
            QTimer.singleShot(0, self.resize_dock)
        return False

    def invoke(self, method):
        if self.engine.work is not None and self.engine.integration_state()['ready']:
            return getattr(self.engine.work, method)()

    def _update_business_menu(self):
        work = self.engine.work
        ready = work is not None and self.engine.integration_state()['ready']
        actions = self.root.moreActionsButton.menu().actions()
        actions[0].setEnabled(ready)
        actions[1].setEnabled(ready and bool(work.archives))

    def attach_work(self, work):
        self.work = work
        work.status.hide()
        if getattr(work, 'presentation_toolbar', None) is not None:
            work.presentation_toolbar.hide()
        self.buttons['drafts'].hide()
        work.verticalLayout.setContentsMargins(0, 0, 0, 0)
        work.verticalLayout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        work.setMinimumWidth(0)
        work.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        work.workspaceSplitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        work.layerListHost.setMinimumWidth(0)
        work.layerListHost.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        work.layerListLayout.setContentsMargins(0, 0, 0, 0)
        work.layerListLayout.setStretch(work.layerListLayout.count() - 1, 1)
        work.formStack.setMinimumWidth(0)
        work.formStack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        work.formPanel.setMinimumWidth(0)
        work.formPanel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.form_edge = self.engine._workspace_panel.form_edge
        work.workspaceSplitter.setChildrenCollapsible(False)

    def step(self):
        self.set_mode(PanelMode.LAYERS if self.mode == PanelMode.ICONS else PanelMode(self.mode - 1))

    def set_mode(self, mode, return_to_work=False):
        self.mode = PanelMode(mode)
        if return_to_work:
            self.engine.return_to_current_project()
        self.apply()

    def apply(self):
        if self.closed:
            return
        e = self.engine
        working = self.work is not None and e.stack.currentWidget() is self.work
        self.content.setVisible(not working or self.mode != PanelMode.ICONS)
        for key in ('select', 'save', 'zoom', 'drafts'):
            self.buttons[key].setEnabled(e.integration_state()['ready'])
        self.edge.setVisible(working)
        self.edge.setChecked(self.mode != PanelMode.ICONS)
        self.edge.setToolTip('레이어 펼치기' if self.mode == PanelMode.ICONS else '한 단계 접기')
        if self.work is not None:
            self.work.layerListHost.setVisible(self.mode != PanelMode.ICONS)
            self.form_edge.setVisible(self.mode != PanelMode.ICONS)
            self.form_edge.setChecked(self.mode == PanelMode.FULL)
            self.form_edge.setToolTip('속성폼 접기' if self.mode == PanelMode.FULL else '속성폼 펼치기')
            self.work.formPanel.setVisible(self.mode == PanelMode.FULL)
            self.work.formStack.setVisible(self.mode == PanelMode.FULL)
            if self.mode == PanelMode.FULL:
                self.work.workspaceSplitter.setSizes([WIDTHS['layers'], WIDTHS['form']])
        width = WIDTHS['icons'] + WIDTHS['selector'] if not working else WIDTHS['icons'] + WIDTHS['boundary']
        if working and self.mode >= PanelMode.LAYERS:
            width += WIDTHS['layers']
        if working and self.mode == PanelMode.FULL:
            width += WIDTHS['form']
        self._target = width
        self.resize_dock()
        QTimer.singleShot(0, self.resize_dock)

    def resize_dock(self):
        if self.closed:
            return
        e = self.engine
        limit = max(160, e.iface.mainWindow().width() - WIDTHS['map_reserve'])
        width = min(self._target, limit)
        e.dock.setMinimumWidth(min(width, WIDTHS['icons'] + WIDTHS['boundary']))
        e.dock.setMaximumWidth(width)
        e.dock.updateGeometry()
        if e.dock.isFloating():
            e.dock.resize(width, e.dock.height())
        else:
            e.iface.mainWindow().resizeDocks([e.dock], [width], Qt.Orientation.Horizontal)

    def close(self):
        self.closed = True
        self.engine.iface.mainWindow().removeEventFilter(self)
