"""Growth department executor seam; external channel/data tools are not connected."""


class GROWTH_UnconfiguredAdapter:
    def execute(self, context):
        raise RuntimeError('发行增长部门执行器尚未接入；请由发行增长部门负责人实现 adapter.py')


def create_adapter():
    return GROWTH_UnconfiguredAdapter()
