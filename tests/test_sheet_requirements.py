import unittest
from unittest.mock import Mock
from server.sheet_requirements import read_sheet_requirement, column_name


class SheetRequirementTests(unittest.TestCase):
    def workbook(self):
        return {'token':'sheetToken','revision':1,'sheets':[{'sheet_id':'tab','sheet_name':'名称',
                 'row_count':3,'column_count':2,'is_hidden':False}]}

    def cells(self):
        return {'revision':1,'has_more':False,'ranges':[{'actual_range':'A1:B3','cells':[
            [{'value':'标题'},{}],[{},{}],[{'value':0},{'value':False}]]}]}

    def test_reads_after_blank_rows_and_keeps_zero_false_addresses(self):
        client=Mock();client._read.side_effect=[self.workbook(),self.cells(),self.workbook()]
        content,meta=read_sheet_requirement(client,'https://example.feishu.cn/sheets/token')
        self.assertIn('tab!A3：{"value": 0}',content)
        self.assertIn('tab!B3：{"value": false}',content)
        self.assertEqual(meta['read_grid_cell_count'],6)
        self.assertEqual(meta['nonempty_cell_count'],3)
        self.assertEqual(column_name(27),'AA')

    def test_truncation_mixed_revisions_and_missing_cells_rejected(self):
        for bad in [{**self.cells(),'has_more':True},{**self.cells(),'revision':2},
                    {**self.cells(),'ranges':[{'actual_range':'A1:B3','cells':[[{}]]}]}]:
            client=Mock();client._read.side_effect=[self.workbook(),bad]
            with self.assertRaises(ValueError):read_sheet_requirement(client,'url')
        client=Mock();client._read.side_effect=[self.workbook(),self.cells(),{**self.workbook(),'revision':2}]
        with self.assertRaises(ValueError):read_sheet_requirement(client,'url')

    def test_grid_limit_rejects_before_reading_cells(self):
        workbook=self.workbook();workbook['sheets'][0]['row_count']=20000
        client=Mock();client._read.return_value=workbook
        with self.assertRaisesRegex(ValueError,'20000'):read_sheet_requirement(client,'url')
        self.assertEqual(client._read.call_count,1)
