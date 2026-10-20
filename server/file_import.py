"""DOCX需求读取；不解压到磁盘，不执行文档内容。"""
import base64
import binascii
import hashlib
import io
import zipfile
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def parse_docx(name, encoded):
    if not isinstance(name, str) or not name.lower().endswith('.docx'):
        raise ValueError('此入口需要 DOCX 文件')
    if not isinstance(encoded, str):
        raise ValueError('文件数据不合法')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('文件编码不合法') from None
    if not raw or len(raw) > 700000:
        raise ValueError('DOCX 文件不得超过700KB')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 16000000:
                raise ValueError('DOCX解压后过大')
            xml = archive.read('word/document.xml')
            if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                raise ValueError('不支持带实体定义的文档')
            document = ET.fromstring(xml)
            body = document.find(W + 'body')
            if body is None:
                raise ValueError('DOCX缺少正文')
            gaps, segments = [], []
            def text(element):
                return ''.join(node.text or '' if node.tag == W + 't' else '\t' if node.tag == W + 'tab' else '\n'
                               for node in element.iter() if node.tag in (W + 't', W + 'tab', W + 'br'))
            for index, block in enumerate(body, 1):
                if block.tag == W + 'p':
                    value = text(block)
                elif block.tag == W + 'tbl':
                    value = '\n'.join(' | '.join(text(cell) for cell in row.findall(W + 'tc'))
                                      for row in block.findall(W + 'tr'))
                elif block.tag == W + 'sectPr':
                    continue
                else:
                    gaps.append(f'正文块{index}未解析：{block.tag.split("}")[-1]}')
                    continue
                if value.strip():
                    segments.append({'location': f'word/document.xml/body/{index}', 'text': value})
            for tag, label in [('drawing', '图片或绘图'), ('pict', '图片'), ('object', '嵌入对象'),
                               ('ins', '修订新增'), ('del', '修订删除'), ('footnoteReference', '脚注'), ('endnoteReference', '尾注')]:
                if document.find('.//' + W + tag) is not None:
                    gaps.append('未完整解析：' + label)
            if any(item.filename.startswith(('word/header', 'word/footer')) for item in archive.infolist()):
                gaps.append('页眉页脚未读取')
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError, OSError):
        raise ValueError('DOCX结构不合法或不支持加密文件') from None
    content = '\n\n'.join(f'[{s["location"]}]\n{s["text"]}' for s in segments)
    if not content.strip():
        raise ValueError('DOCX没有可读取的文字，未导入')
    return content, {'kind': 'docx', 'original_sha256': hashlib.sha256(raw).hexdigest(),
                     'segments': segments, 'source_gaps': gaps,
                     'scope': '正文段落及表格文字；不代表已解析图片和版式'}


S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def parse_xlsx(name, encoded):
    """读取 OOXML 单元格及定位，不运行公式，不加载外部链接。"""
    import posixpath
    if not isinstance(name, str) or not name.lower().endswith('.xlsx') or not isinstance(encoded, str):
        raise ValueError('需要 XLSX 文件及合法编码')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('文件编码不合法') from None
    if not raw or len(raw) > 700000:
        raise ValueError('XLSX 文件不得超过700KB')
    segments, gaps, sheets = [], [], []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(i.file_size for i in entries) > 16000000:
                raise ValueError('XLSX 解压后过大')
            if len({i.filename for i in entries}) != len(entries):
                raise ValueError('XLSX 包含重复部件')
            def xml(path):
                data = archive.read(path)
                if b'<!DOCTYPE' in data or b'<!ENTITY' in data:
                    raise ValueError('不支持实体定义')
                return ET.fromstring(data)
            def text(node):
                return ''.join(t.text or '' for t in node.iter(S+'t'))
            strings = [text(si) for si in xml('xl/sharedStrings.xml').findall(S+'si')] if 'xl/sharedStrings.xml' in archive.namelist() else []
            relationships = {e.get('Id'): e for e in xml('xl/_rels/workbook.xml.rels')}
            workbook = xml('xl/workbook.xml')
            count = 0
            for sheet in workbook.findall(S+'sheets/'+S+'sheet'):
                title = sheet.get('name', '')
                rel = relationships.get(sheet.get(R+'id'))
                if rel is None or rel.get('TargetMode') == 'External':
                    raise ValueError('工作表关系无效')
                target = rel.get('Target', '')
                path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
                if not path.startswith('xl/') or '\\' in path:
                    raise ValueError('工作表路径无效')
                root = xml(path)
                state = sheet.get('state', 'visible')
                sheets.append({'name': title, 'state': state, 'part': path})
                if state != 'visible':
                    gaps.append('已读取隐藏工作表，需确认是否属于需求：'+title)
                for row in root.findall(S+'sheetData/'+S+'row'):
                    cells = []
                    for cell in row.findall(S+'c'):
                        count += 1
                        if count > 20000:
                            raise ValueError('单元格超过20000个，未导入截断内容')
                        ref = cell.get('r')
                        if not ref:
                            raise ValueError('单元格缺少位置')
                        location = title+'!'+ref
                        if cell.get('s'):
                            gaps.append('未还原单元格显示格式（日期/百分比等需核对）：'+location)
                        value_node = cell.find(S+'v')
                        value = value_node.text or '' if value_node is not None else ''
                        kind = cell.get('t')
                        if kind == 's':
                            index = int(value)
                            if not 0 <= index < len(strings):
                                raise ValueError('共享字符串索引无效')
                            value = strings[index]
                        elif kind == 'inlineStr':
                            value = text(cell)
                        if cell.find(S+'f') is not None:
                            formula = cell.find(S+'f').text or ''
                            gaps.append('公式未重新计算，缓存可能过期：'+location)
                            value = '公式：'+formula+'；缓存值：'+(value or '缺失')
                        elif kind == 'e':
                            gaps.append('单元格错误：'+location)
                        elif kind == 'b':
                            value = 'TRUE' if value == '1' else 'FALSE'
                        if value.strip():
                            cells.append('['+location+'] '+value)
                            segments.append({'location': location, 'text': value})
                    if row.get('hidden') == '1' and cells:
                        gaps.append('已读取隐藏行：'+title+'!'+str(row.get('r')))
                if root.find(S+'mergeCells') is not None:
                    gaps.append('合并单元格只读取左上角原值，未展开：'+title)
                if root.find(S+'cols') is not None and any(c.get('hidden') == '1' for c in root.find(S+'cols')):
                    gaps.append('已读取隐藏列：'+title)
            names = archive.namelist()
            for prefix, label in [('xl/drawings/', '图片/绘图'), ('xl/charts/', '图表'),
                                  ('xl/comments', '批注'), ('xl/externalLinks/', '外部引用'),
                                  ('xl/embeddings/', '嵌入对象')]:
                if any(n.startswith(prefix) for n in names):
                    gaps.append('未完整读取：'+label)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError, OSError, IndexError):
        raise ValueError('XLSX 结构无效或不支持加密文件') from None
    content = '\n'.join('['+s['location']+'] '+s['text'] for s in segments)
    if not content.strip():
        raise ValueError('XLSX 没有可读取的单元格文字')
    if len(content.encode()) > 800000:
        raise ValueError('提取的需求文字超过800KB')
    return content, {'kind':'xlsx', 'original_sha256':hashlib.sha256(raw).hexdigest(),
                     'segments':segments, 'sheets':sheets, 'source_gaps':list(dict.fromkeys(gaps)),
                     'scope':'单元格原值与公式缓存；不重算公式，不解析图片和显示格式'}


def parse_file(name, encoded):
    if isinstance(name, str) and name.lower().endswith('.xlsx'):
        return parse_xlsx(name, encoded)
    return parse_docx(name, encoded)
