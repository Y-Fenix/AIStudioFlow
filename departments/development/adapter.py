"""Development department executor seam; code changes remain manual by default."""


class DEV_UnconfiguredAdapter:
    def execute(self, context):
        raise RuntimeError('开发部门执行器尚未接入；请由开发部门负责人实现 adapter.py')


def create_adapter():
    return DEV_UnconfiguredAdapter()
