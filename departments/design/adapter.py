"""Design department executor seam; kept manual until the design lead connects tools."""


class DESIGN_UnconfiguredAdapter:
    def execute(self, context):
        raise RuntimeError('设计部门执行器尚未接入；请由设计部门负责人实现 adapter.py')


def create_adapter():
    return DESIGN_UnconfiguredAdapter()
