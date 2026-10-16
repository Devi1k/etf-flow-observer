class ObserverError(Exception):
    """采集、校验或试验门禁拒绝继续时抛出。"""


class SimNotReady(ObserverError):
    """模拟账本拒绝写入。当前阶段应一直走这条路径。"""
