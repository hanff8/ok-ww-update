import json
from pathlib import Path

from qfluentwidgets import FluentIcon

from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask


PLAN_PATH = Path('configs') / 'task_orchestration.json'


class TaskOrchestrationTask(WWOneTimeTask, BaseWWTask):
    """Run selected built-in one-time tasks in a user-defined order."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = 'Task Orchestration'
        self.description = 'Run selected tasks in a custom order and repeat each task.'
        self.group_name = 'Daily'
        self.group_icon = FluentIcon.CALENDAR
        self.icon = FluentIcon.MENU
        self.support_schedule_task = True

    def run(self):
        WWOneTimeTask.run(self)
        try:
            plan = json.loads(PLAN_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            plan = []

        tasks = list(getattr(self.executor, 'onetime_tasks', []))
        by_class_name = {task.__class__.__name__: task for task in tasks
                         if task is not self and task.__class__ is not TaskOrchestrationTask}
        for item in plan:
            task = by_class_name.get(item.get('class'))
            if task is None:
                continue
            try:
                count = max(0, min(99, int(item.get('count', 1))))
            except (TypeError, ValueError):
                count = 1
            for _ in range(count):
                self.run_task_by_class(task.__class__)
