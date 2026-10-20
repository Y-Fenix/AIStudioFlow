"""Product department executor seam.

This placeholder is intentionally not loaded while manifest.execution.adapter is
``manual``. The product lead can replace it with a reviewed adapter without
changing the public shell or persistence contract.
"""


class PRODUCT_UnconfiguredAdapter:
    def execute(self, context):
        raise RuntimeError('产品部门执行器尚未接入；请由产品部门负责人实现 adapter.py')


def create_adapter():
    return PRODUCT_UnconfiguredAdapter()
