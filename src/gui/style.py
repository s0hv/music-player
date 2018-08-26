from PyQt5.QtWidgets import QProxyStyle, QStyle


class ProxyStyle(QProxyStyle):
    def __init__(self, *args):
        super().__init__(*args)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PM_SmallIconSize:
            return 25
        else:
            return super().pixelMetric(metric, option, widget)