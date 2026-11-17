"""Completed model text must be one unambiguous, strict JSON object."""
import unittest


class ModelOutputTests(unittest.TestCase):
    def test_single_fence_and_bom_are_formatting_only(self):
        from server.model_output import parse_object
        self.assertEqual(parse_object('\ufeff ```json\n{"ok":true}\n``` '), {'ok': True})

    def test_malformed_ambiguous_and_non_object_outputs_are_typed_private_errors(self):
        from server.model_output import parse_object, ModelOutputError
        for raw in ('{"private":"secret",}', '[]', 'prefix {}', '{} {}',
                    '{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ModelOutputError) as failure:
                parse_object(raw)
            self.assertEqual(failure.exception.raw_text, raw)
            self.assertNotIn('secret', str(failure.exception))
            self.assertNotIn('secret', repr(failure.exception))

