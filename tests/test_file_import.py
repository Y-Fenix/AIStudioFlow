import base64
import io
import unittest
import zipfile
from server.file_import import parse_docx


def encoded(xml):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('word/document.xml',xml)
    return base64.b64encode(output.getvalue()).decode()


class DocxTests(unittest.TestCase):
    def test_paragraph_table_order_and_image_gap(self):
        xml='''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>前段</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>单元格A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>单元格B</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>后段</w:t><w:drawing/></w:r></w:p></w:body></w:document>'''
        content,metadata=parse_docx('需求.docx',encoded(xml))
        self.assertLess(content.index('前段'),content.index('单元格A'))
        self.assertLess(content.index('单元格B'),content.index('后段'))
        self.assertEqual(len(metadata['segments']),3)
        self.assertIn('未完整解析：图片或绘图',metadata['source_gaps'])
        self.assertEqual(metadata['segments'][1]['location'],'word/document.xml/body/2')

    def test_invalid_and_empty_files_never_import(self):
        for data in ('invalid',base64.b64encode(b'not zip').decode(),encoded('<empty/>')):
            with self.assertRaises(ValueError):parse_docx('需求.docx',data)


class XlsxTests(unittest.TestCase):
    def package(self, sheet):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="需求" sheetId="1" r:id="rId1" state="hidden"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr('xl/sharedStrings.xml','<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>奖励需求</t></si></sst>')
            z.writestr('xl/worksheets/sheet1.xml',sheet)
            z.writestr('xl/drawings/drawing1.xml','<drawing/>')
        return base64.b64encode(stream.getvalue()).decode()

    def test_cells_order_locations_formula_and_visual_gaps(self):
        from server.file_import import parse_xlsx
        sheet='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>领取一次</t></is></c></row><row r="2" hidden="1"><c r="A2"><f>1+1</f><v>2</v></c></row></sheetData><mergeCells><mergeCell ref="A1:A2"/></mergeCells></worksheet>'
        content,metadata=parse_xlsx('需求.xlsx',self.package(sheet))
        self.assertIn('[需求!A1] 奖励需求',content)
        self.assertIn('[需求!B1] 领取一次',content)
        self.assertIn('缓存值：2',content)
        self.assertEqual([s['location'] for s in metadata['segments']],['需求!A1','需求!B1','需求!A2'])
        self.assertTrue(any('公式' in g for g in metadata['source_gaps']))
        self.assertTrue(any('图片' in g for g in metadata['source_gaps']))
        self.assertTrue(any('隐藏工作表' in g for g in metadata['source_gaps']))
        self.assertTrue(any('合并单元格' in g for g in metadata['source_gaps']))

    def test_empty_and_invalid_shared_string_rejected(self):
        from server.file_import import parse_xlsx
        for body in ['', '<row><c r="A1" t="s"><v>99</v></c></row>']:
            sheet='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+body+'</sheetData></worksheet>'
            with self.assertRaises(ValueError):parse_xlsx('需求.xlsx',self.package(sheet))
