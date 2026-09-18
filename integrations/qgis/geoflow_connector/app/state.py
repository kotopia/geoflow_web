# 제목: app/state.py
# 기능: 화면 상태 전이와 인증·프로젝트 복구 상태 관리
"""One UI state and one engine-owned project context; no credential copies."""
from enum import Enum
from qgis.PyQt.QtCore import QObject, pyqtSignal


# ============================================================
# 로그인·프로젝트 화면 상태 정의와 전이
# ============================================================
class State(str, Enum):
    LOGGED_OUT = 'LOGGED_OUT'
    LOGGED_IN_NO_PROJECT = 'LOGGED_IN_NO_PROJECT'
    PROJECT_LOADING = 'PROJECT_LOADING'
    PROJECT_READY = 'PROJECT_READY'
    PROJECT_SWITCHING = 'PROJECT_SWITCHING'
    ERROR = 'ERROR'


class StateManager(QObject):
    changed = pyqtSignal()

    def __init__(self, engine):
        super().__init__(engine.iface.mainWindow())
        self.engine = engine
        self.state = State.LOGGED_OUT
        self.recovery = State.LOGGED_OUT
        self.error_kind = ''
        self.message = ''

    @property
    def context(self):
        return self.engine.active_context  # The existing engine owns the only context.

    @property
    def authenticated(self):
        return self.engine.dialog is not None and self.engine.dialog.client is not None

    def set(self, state, message=''):
        if state != State.LOGGED_OUT and not self.authenticated:
            state = State.LOGGED_OUT
        if state == State.PROJECT_READY and not self.context:
            raise RuntimeError('Ready requires a project context')
        self.state, self.message = state, message
        if state != State.ERROR:
            self.error_kind = ''
        self.changed.emit()

    def fail(self, kind, message, recovery):
        self.error_kind, self.recovery = kind, recovery
        self.set(State.ERROR, message)
