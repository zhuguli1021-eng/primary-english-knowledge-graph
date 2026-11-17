import importlib.util,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('intake',Path(__file__).parents[1]/'scripts/import_sources.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class IntakeTests(unittest.TestCase):
 def test_grade_boundaries(self):
  self.assertEqual(m.scope('英语人教三年级.pdf'),('primary',3));self.assertEqual(m.scope('7上期中.pdf'),('secondary',7));self.assertEqual(m.scope('2026年河南中考英语.pdf'),('secondary',9));self.assertEqual(m.scope('FCE词汇.pdf'),('advanced',None));self.assertEqual(m.scope('小升初.pdf'),('primary',7))
 def test_missing_drive_does_not_replace_catalog(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'data').mkdir();target=root/'data/source_catalog.json';target.write_text('keep')
   args=SimpleNamespace(source=root/'not-mounted',ocr_bin=None,workers=1,scan=False,retry_empty=False)
   with patch.object(m,'ROOT',root):
    with self.assertRaises(FileNotFoundError):m.run(args)
   self.assertEqual(target.read_text(),'keep')
 def test_idempotence_dedup_modified_and_removed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'data').mkdir();(root/'data/topics.json').write_text(json.dumps([{'id':'te.past_simple','grade':6,'signals':['yesterday']}]))
   src=root/'sources';src.mkdir();(src/'六年级.txt').write_text('1. Yesterday I ___ a very interesting book.');(src/'重复六年级.txt').write_bytes((src/'六年级.txt').read_bytes());(src/'._ignored.txt').write_text('ignored')
   args=SimpleNamespace(source=src,ocr_bin=None,workers=1,scan=False,retry_empty=False)
   with patch.object(m,'ROOT',root):
    m.run(args);a=json.loads((root/'data/source_catalog.json').read_text());self.assertEqual(a['counts']['duplicate'],1);self.assertEqual(a['counts']['extracted_pending_review'],1)
    ref=json.loads((root/'data/exam_references.json').read_text());self.assertEqual(len(ref['topics']['te.past_simple']),1)
    m.run(args);self.assertEqual(json.loads((root/'data/source_catalog.json').read_text())['counts'],a['counts'])
    (src/'重复六年级.txt').unlink();(src/'六年级.txt').write_text('1. Yesterday we ___ football at our school.');m.run(args)
    b=json.loads((root/'data/source_catalog.json').read_text());self.assertEqual(len(b['files']),1);self.assertNotEqual(b['files'][0]['sha256'],a['files'][0]['sha256'])
    ref=json.loads((root/'data/exam_references.json').read_text());self.assertIn('football',ref['topics']['te.past_simple'][0]['text']);self.assertNotIn('book',ref['topics']['te.past_simple'][0]['text'])
if __name__=='__main__':unittest.main()
