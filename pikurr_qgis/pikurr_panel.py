# -*- coding: utf-8 -*-
"""
round48, блок C1: панель вместо модального диалога — не блокирует карту,
остаётся открытой. Заменяет прежний `pikurr_dialog.py`/
`pikurr_dialog_base.ui` (QDialog, `exec_()`).
"""
import os

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'pikurr_panel_base.ui'))


class pikurrPanel(QtWidgets.QDockWidget, FORM_CLASS):
    def __init__(self, parent=None):
        super(pikurrPanel, self).__init__(parent)
        self.setupUi(self)
        self.serverGroupBox.setVisible(False)
        self.serverToggleButton.toggled.connect(self._on_server_toggle)

    def _on_server_toggle(self, checked):
        self.serverGroupBox.setVisible(checked)
        arrow = '▾' if checked else '▸'
        self.serverToggleButton.setText(f'{arrow} Настройки сервера')
