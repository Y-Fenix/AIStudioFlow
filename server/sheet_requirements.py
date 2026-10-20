"""飞书表格只读需求来源：逐单元格保留地址，拒绝截断及跨版本混读。"""
import json


def column_name(index):
    result = ''
    while index:
        index, digit = divmod(index-1, 26)
        result = chr(65+digit)+result
    return result


def read_sheet_requirement(client, url):
    workbook = client._read(['sheets', '+workbook-info', '--url', url])
    token, sheets, revision = workbook.get('token'), workbook.get('sheets'), workbook.get('revision')
    if not isinstance(token, str) or not token or not isinstance(sheets, list) or not sheets or revision is None:
        raise ValueError('电子表格结构不支持，未导入')
    total = 0
    seen = set()
    for sheet in sheets:
        identifier = sheet.get('sheet_id')
        rows, cols = sheet.get('row_count'), sheet.get('column_count')
        if (not isinstance(identifier, str) or not identifier or identifier in seen
                or type(rows) is not int or type(cols) is not int or rows < 1 or cols < 1):
            raise ValueError('电子表格工作表标识或尺寸无效')
        seen.add(identifier)
        total += rows*cols
    if total > 20000:
        raise ValueError('电子表格超过20000个网格单元格，请明确缩小需求范围；未截断导入')
    lines = ['电子表格：'+str(workbook.get('title') or token)]
    gaps = ['未读取完整显示样式、行列隐藏及合并布局；单元格地址保留，隐藏工作表不跳过']
    cell_count = 0
    for sheet in sheets:
        identifier = sheet['sheet_id']; cols = sheet['column_count']
        lines.append('\n工作表：'+str(sheet.get('sheet_name') or identifier)+' ['+identifier+']')
        if sheet.get('is_hidden'):
            gaps.append('工作表隐藏：'+identifier+'，内容已读但需核对是否属于当前需求')
        if any(sheet.get(key) for key in ('chart_count', 'float_image_count', 'pivot_table_count')):
            gaps.append('未读取图表/浮动图片/透视对象：'+identifier)
        for start in range(1, sheet['row_count']+1, 100):
            end = min(start+99, sheet['row_count'])
            area = 'A'+str(start)+':'+column_name(cols)+str(end)
            data = client._read(['sheets', '+cells-get', '--spreadsheet-token', token,
                '--sheet-id', identifier, '--range', area,
                '--include', 'value,formula,comment,data_validation', '--max-chars', '500000'])
            ranges = data.get('ranges')
            if (data.get('has_more') is not False or data.get('revision') != revision
                    or not isinstance(ranges, list) or len(ranges) != 1
                    or ranges[0].get('actual_range') != area):
                raise ValueError('表格读取被截断、范围不一致或版本变化，未导入')
            matrix = ranges[0].get('cells')
            if (not isinstance(matrix, list) or len(matrix) != end-start+1
                    or any(not isinstance(row, list) or len(row) != cols for row in matrix)):
                raise ValueError('单元格矩阵不完整，未导入')
            if data.get('warning_message'):
                gaps.append('表格读取警告：'+str(data['warning_message']))
            for row_number, row in enumerate(matrix, start):
                for col_number, cell in enumerate(row, 1):
                    if not isinstance(cell, dict):
                        raise ValueError('单元格格式不支持，未导入')
                    if not cell:
                        continue
                    address = identifier+'!'+column_name(col_number)+str(row_number)
                    lines.append(address+'：'+json.dumps(cell, ensure_ascii=False, sort_keys=True))
                    cell_count += 1
                    if cell.get('formula'):
                        gaps.append('公式未重新计算，仅保存当前返回值和公式：'+address)
                    if isinstance(cell.get('value'), (dict, list)):
                        gaps.append('复杂单元格值未展开图片或外部资源：'+address)
    after = client._read(['sheets', '+workbook-info', '--url', url])
    if after != workbook:
        raise ValueError('表格读取期间结构或版本变化，未导入')
    if not cell_count:
        raise ValueError('电子表格内容为空，未导入')
    content = '\n'.join(lines)
    if len(content.encode()) > 700000:
        raise ValueError('电子表格内容超过700KB，未截断导入')
    return content, {'kind': 'feishu_sheet', 'document_id': token, 'revision_id': revision,
                     'source_gaps': list(dict.fromkeys(gaps)), 'sheet_catalog': sheets,
                     'read_grid_cell_count': total, 'nonempty_cell_count': cell_count,
                     'resources': [], 'scope': '完整网格逐单元格读取；不执行公式或推断图片内容'}
