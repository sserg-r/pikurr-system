# -*- coding: utf-8 -*-
"""
round48, блок C1: панель вместо модального диалога — не блокирует карту,
остаётся открытой. Заменяет прежний `pikurr_dialog.py`/
`pikurr_dialog_base.ui` (QDialog, `exec_()`).
"""
import os

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets, QtCore

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'pikurr_panel_base.ui'))


class pikurrPanel(QtWidgets.QDockWidget, FORM_CLASS):
    def __init__(self, parent=None):
        super(pikurrPanel, self).__init__(parent)
        self.setupUi(self)
        self.serverGroupBox.setVisible(False)
        self.serverToggleButton.toggled.connect(self._on_server_toggle)
        self._make_searchable(self.districtCombo)
        self._make_searchable(self.userCombo)

    def _make_searchable(self, combo):
        """round49, A3: по умолчанию editable QComboBox ищет только по
        началу строки (стандартный QCompleter Qt) — набор подстроки из
        середины названия (не с начала) не находит пункт и не вызывает
        `activated` вовсе (проверено фактом, docs/round49-autonomous.md,
        блок A3). Совпадение ищется по МОДЕЛИ самого combo — работает
        после любого clear()/addItem(), не нужно перенастраивать при
        каждом обновлении списка."""
        completer = QtWidgets.QCompleter(combo.model(), combo)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        completer.setFilterMode(QtCore.Qt.MatchContains)
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        combo.setCompleter(completer)

    def _on_server_toggle(self, checked):
        self.serverGroupBox.setVisible(checked)
        arrow = '▾' if checked else '▸'
        self.serverToggleButton.setText(f'{arrow} Настройки сервера')
