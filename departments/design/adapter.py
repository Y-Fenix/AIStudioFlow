"""Model-backed text deliverables; external tool work remains explicitly unperformed."""
from server.core.integrations import generate_document
from departments.design.DESIGN_contracts import DESIGN_CONTRACTS


class DESIGN_DocumentAdapter:
    def execute(self, context):
        if context.node_id not in {'design:' + str(index) for index in range(4)}:
            raise ValueError('只支持本部门四个固定节点；自定义节点需独立执行契约')
        contract = DESIGN_CONTRACTS[int(context.node_id.split(':')[1])]
        return generate_document(context, contract)


def create_adapter():
    return DESIGN_DocumentAdapter()
