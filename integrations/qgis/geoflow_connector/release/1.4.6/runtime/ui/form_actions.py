"""Compact Dynamic Form tab actions and extensible inline field actions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QSizePolicy, QToolButton, QWidget
from qgis.PyQt.uic import loadUi


class FormActionToolbar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        loadUi(
            str(Path(__file__).parent / "designer" / "form_actions.ui"), self
        )
        self.setFixedHeight(32)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.saveButton.setIcon(QIcon(":/geoflow/feather/save.svg"))
        self.previousButton.setIcon(QIcon(":/geoflow/tabler/history.svg"))
        self.nearbyButton.setIcon(QIcon(":/geoflow/tabler/location-search.svg"))
        self.layoutButton.setIcon(QIcon(":/geoflow/tabler/layout.svg"))
        self.referenceRefreshButton.setIcon(QIcon(":/geoflow/tabler/refresh.svg"))
        self.photoButton.setIcon(QIcon(":/geoflow/feather/camera.svg"))
        for button in (
            self.saveButton, self.previousButton, self.nearbyButton,
            self.layoutButton, self.referenceRefreshButton, self.photoButton,
        ):
            configure_field_action_button(button)
            button.setVisible(True)

    def set_layer_title(self, title):
        self.layerTitleLabel.setText(str(title or ""))

    def apply_preferences(self, settings_service, project_id=None):
        """Apply only optional actions; save/layout/reference/photo stay intact."""
        self.nearbyButton.setVisible(
            settings_service.show_nearby_button(project_id)
        )
        self.previousButton.setVisible(
            settings_service.show_previous_button(project_id)
        )


@dataclass(frozen=True)
class FieldActionSpec:
    storage_key: str
    standard_name: str
    icon: str
    tooltip: str
    callback_name: str


class FieldActionRegistry:
    def __init__(self):
        self._specs = {}

    def register(self, spec):
        self._specs.setdefault(spec.storage_key.casefold(), []).append(spec)

    def attach(self, page, layer, controller):
        standard = str(layer.customProperty(
            "geoflow/standard_name", ""
        ) or "").upper()
        attached = []
        for field in page.form.fields:
            storage = field.get("storage") or {}
            key = str(storage.get("key") or "").casefold()
            for spec in self._specs.get(key, ()):
                if standard != spec.standard_name:
                    continue
                button = QToolButton(page.form)
                button.setObjectName(spec.callback_name + "Button")
                configure_field_action_button(
                    button, icon=spec.icon, tooltip=spec.tooltip
                )
                button.clicked.connect(
                    lambda _checked=False, p=page, name=spec.callback_name:
                    getattr(controller, name)(p)
                )
                if page.form.add_field_action(field["id"], button):
                    attached.append(button)
        return attached


def configure_field_action_button(button, *, icon=None, tooltip=None):
    """Apply the one shared visual contract for inline form actions."""
    button.setProperty("fieldAction", "true")
    button.setAutoRaise(False)
    button.setText("")
    button.setFixedSize(28, 28)
    button.setIconSize(QSize(16, 16))
    if icon is not None:
        button.setIcon(QIcon(icon) if isinstance(icon, str) else icon)
    if tooltip is not None:
        button.setToolTip(str(tooltip))
    # These buttons can be created after the form stylesheet was polished.
    # Re-polish so the dynamic property selector is applied immediately.
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.update()
    return button


def default_field_action_registry():
    registry = FieldActionRegistry()
    registry.register(FieldActionSpec(
        storage_key="pip_dep",
        standard_name="WTL_PIPE_PS",
        icon=":/geoflow/tabler/calculator.svg",
        tooltip="심도 자동계산",
        callback_name="calculate_current_depth",
    ))
    return registry
