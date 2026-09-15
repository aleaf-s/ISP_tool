"""One compact, shared navigation contract for every workspace."""
from .action_menu import ActionMenu


class ToolSelector(ActionMenu):
    LABELS = {'isp': 'RAW ISP', 'yuv': 'YUV 预览', 'grading': '手动调色'}

    def __init__(self, parent, variable, command):
        super().__init__(parent, '工具', style='Primary.TButton')
        self.variable = variable
        for value, label in self.LABELS.items():
            self.add_radiobutton(label, variable, value,
                                 lambda key=value: command(key))
        self._trace = variable.trace_add('write', self._update_label)
        self._update_label()

    def _update_label(self, *_):
        self.set_text('工具：' + self.LABELS.get(self.variable.get(), 'RAW ISP'))

    def destroy(self):
        self.variable.trace_remove('write', self._trace)
        super().destroy()
