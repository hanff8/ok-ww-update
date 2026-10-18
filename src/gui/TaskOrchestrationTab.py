import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)
from qfluentwidgets import (BodyLabel, CheckBox, FluentIcon, MessageBox, MessageBoxBase, PrimaryPushButton,
                            SingleDirectionScrollArea, TitleLabel)
from ok.gui.widget.CustomTab import CustomTab

from src.task.TaskOrchestrationTask import PLAN_PATH


class _OrchestrationTable(QTableWidget):
    """Table whose row drag moves the whole row, counts included.

    QTableWidget's built-in InternalMove only reorders model items, so the
    QSpinBox cell widgets stay behind, and Qt deletes the dragged row as soon
    as the drag reports a move. Handling the drop here and rebuilding the table
    ourselves keeps every task name paired with its own count.
    """

    def __init__(self, rows, columns, parent=None):
        super().__init__(rows, columns, parent)
        self.row_moved = None

    def dropEvent(self, event):
        callback = self.row_moved
        source = self.currentRow()
        if callback is None or source < 0:
            event.ignore()
            return
        y = event.position().toPoint().y()
        target = self.rowAt(y)
        if target < 0:
            target = self.rowCount()
        elif y > self.rowViewportPosition(target) + self.rowHeight(target) // 2:
            target += 1
        # Never accept the drop: accepting it is what makes Qt delete the source row.
        event.setDropAction(Qt.IgnoreAction)
        event.ignore()
        callback(source, target)


class _AddTaskDialog(MessageBoxBase):
    """Pick which built-in tasks to append, instead of appending them blind."""

    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self.tasks = list(tasks)
        self.checkboxes = []
        self.setWindowTitle('添加子任务')
        self.yesButton.setText('添加')
        self.cancelButton.setText('取消')
        self.viewLayout.addWidget(TitleLabel('添加子任务', self.widget))
        self.viewLayout.addWidget(BodyLabel('勾选要参与编排的内置任务：', self.widget))

        self.list_area = SingleDirectionScrollArea(self.widget)
        container = QWidget(self.list_area)
        box_layout = QVBoxLayout(container)
        box_layout.setContentsMargins(0, 0, 8, 0)
        box_layout.setSpacing(4)
        box_layout.setAlignment(Qt.AlignTop)
        for task in self.tasks:
            checkbox = CheckBox(task.name, container)
            checkbox.stateChanged.connect(self._sync_yes_button)
            self.checkboxes.append(checkbox)
            box_layout.addWidget(checkbox, 0, Qt.AlignTop)
        self.list_area.setWidget(container)
        self.list_area.setWidgetResizable(True)
        self.list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_area.setFixedHeight(min(34 * len(self.tasks) + 8, 320))
        self.viewLayout.addWidget(self.list_area)
        self._sync_yes_button()

    def _sync_yes_button(self):
        self.yesButton.setEnabled(any(box.isChecked() for box in self.checkboxes))

    def checked_tasks(self):
        return [task for task, box in zip(self.tasks, self.checkboxes) if box.isChecked()]


class TaskOrchestrationTab(CustomTab):
    @property
    def name(self):
        return '任务编排'

    @property
    def icon(self):
        return FluentIcon.MENU

    def __init__(self):
        super().__init__()
        self.loaded_plan = []
        self.add_widget(BodyLabel('任务编排：拖动行调整执行顺序，并为每个子任务设置执行次数。'))
        self.table = _OrchestrationTable(0, 2, self.view)
        self.table.row_moved = self._move_row
        self.table.setHorizontalHeaderLabels(['子任务', '执行次数'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setDragDropMode(QAbstractItemView.InternalMove)
        self.table.setDefaultDropAction(Qt.MoveAction)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.add_widget(self.table, 1)
        buttons = QHBoxLayout()
        self.add_button = QPushButton('添加子任务')
        self.remove_button = QPushButton('移除选中')
        self.save_button = PrimaryPushButton('保存编排')
        self.add_button.clicked.connect(self._add_task)
        self.remove_button.clicked.connect(self._remove_task)
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        self.addLayout(buttons)

    def showEvent(self, event):
        super().showEvent(event)
        # Reload the saved plan on every visit, unless the user has unsaved edits on screen.
        if not self._is_dirty():
            self._populate()

    def _available_tasks(self):
        if self.executor is None:
            return []
        from src.task.TaskOrchestrationTask import TaskOrchestrationTask
        return [task for task in getattr(self.executor, 'onetime_tasks', [])
                if not isinstance(task, TaskOrchestrationTask)]

    def _rows(self):
        """The table as [(class_name, display_name, count)], skipping incomplete rows."""
        rows = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            spin = self.table.cellWidget(row, 1)
            if item is None or spin is None:
                continue
            rows.append((item.data(Qt.UserRole), item.text(), spin.value()))
        return rows

    def _current_plan(self):
        return [{'class': class_name, 'count': count} for class_name, _, count in self._rows()]

    def _is_dirty(self):
        return self._current_plan() != self.loaded_plan

    def _fill(self, rows):
        self.table.setRowCount(0)
        for class_name, display_name, count in rows:
            self._append(class_name, display_name, count)

    def _populate(self):
        try:
            plan = json.loads(PLAN_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            plan = []
        available = {task.__class__.__name__: task for task in self._available_tasks()}
        rows = []
        for entry in plan:
            task = available.get(entry.get('class'))
            if task is not None:
                rows.append((task.__class__.__name__, task.name, entry.get('count', 1)))
        self._fill(rows)
        self.loaded_plan = self._current_plan()

    def _append(self, class_name, display_name, count=1):
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(display_name)
        name.setData(Qt.UserRole, class_name)
        name.setFlags(name.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 0, name)
        spin = QSpinBox(self.table)
        spin.setRange(1, 99)
        spin.setValue(max(1, min(99, int(count))))
        self.table.setCellWidget(row, 1, spin)

    def _move_row(self, source, target):
        rows = self._rows()
        if not 0 <= source < len(rows):
            return
        row = rows.pop(source)
        if target > source:
            target -= 1
        rows.insert(max(0, min(target, len(rows))), row)
        self._fill(rows)

    def _add_task(self):
        added = {class_name for class_name, _, _ in self._rows()}
        remaining = [task for task in self._available_tasks() if task.__class__.__name__ not in added]
        if not remaining:
            MessageBox('任务编排', '所有内置任务都已添加。', self.window()).exec()
            return
        dialog = _AddTaskDialog(remaining, self.window())
        if not dialog.exec():
            return
        for task in dialog.checked_tasks():
            self._append(task.__class__.__name__, task.name)

    def _remove_task(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def _save(self):
        plan = self._current_plan()
        PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        self.loaded_plan = plan
        MessageBox('任务编排', '已保存。点击“Task Orchestration”任务即可执行。', self.window()).exec()
