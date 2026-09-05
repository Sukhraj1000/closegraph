import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation import publish_issues as publisher


class CatalogueTests(unittest.TestCase):
    def test_original_tasks_exactly_once_and_topological_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'openspec/changes/verify-corrected-reporting-pack/tasks.md'
            source.parent.mkdir(parents=True)
            source.write_text('- [ ] 1.1 first\n- [ ] 1.2 second\n')
            entries = [
                {'key':'T1.2','kind':'task','epic':'E1','spec_tasks':['1.2'],'depends_on':['T1.1']},
                {'key':'E1','kind':'epic','epic':None,'spec_tasks':[],'depends_on':[]},
                {'key':'T1.1','kind':'task','epic':'E1','spec_tasks':['1.1'],'depends_on':[]},
            ]
            path = root / 'catalog.json'
            path.write_text(json.dumps({'repo':publisher.REPO,'issues':entries}))
            with patch.object(publisher,'ROOT',root):
                _, ordered = publisher.load_catalog(path)
                self.assertEqual([x['key'] for x in ordered], ['E1','T1.1','T1.2'])
                entries[0]['depends_on'] = ['T1.2']
                path.write_text(json.dumps({'repo':publisher.REPO,'issues':entries}))
                with self.assertRaisesRegex(ValueError,'Cyclic'):
                    publisher.load_catalog(path)
                entries[0]['spec_tasks'] = ['1.1']
                path.write_text(json.dumps({'repo':publisher.REPO,'issues':entries}))
                with self.assertRaisesRegex(ValueError,'exactly once'):
                    publisher.load_catalog(path)

    def test_renderer_keeps_stable_marker_and_real_links(self):
        item = {'key':'T1.1','body':'Actual task scope','epic':'E1','depends_on':['A01']}
        rendered = publisher.render(item, {'E1':{'url':'https://github.com/example/repo/issues/1'},
                                         'A01':{'url':'https://github.com/example/repo/issues/2'}})
        self.assertIn('<!-- closegraph:catalog=T1.1 -->',rendered)
        self.assertIn('https://github.com/example/repo/issues/1',rendered)
        self.assertIn('Automation is paused',rendered)
        self.assertNotIn('loop:ready',rendered)

    def test_resumed_task_verification_rejects_body_and_label_drift(self):
        item = {'key':'T1.1', 'title':'Scoped task'}
        body = '<!-- closegraph:catalog=T1.1 -->\nRequired scope'
        observed = {'title':item['title'], 'body':body,
                    'labels':[{'name':'task'}, {'name':'loop:backlog'}]}
        wanted = ['task','loop:backlog']
        publisher.verify_issue(item, observed, body, wanted)
        observed['body'] = body + '\nUnapproved changed acceptance'
        with self.assertRaisesRegex(RuntimeError, 'content/label'):
            publisher.verify_issue(item, observed, body, wanted)
        observed['body'] = body
        observed['labels'] = [{'name':'task'}, {'name':'loop:ready'}]
        with self.assertRaisesRegex(RuntimeError, 'content/label'):
            publisher.verify_issue(item, observed, body, wanted)

    def test_index_atomic_and_explicit_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'index.json'
            publisher.save_index(path, {'E0':{'key':'E0','number':1}})
            self.assertFalse(json.loads(path.read_text())['complete'])
            publisher.save_index(path, {'E0':{'key':'E0','number':1}},complete=True,native=True)
            result=json.loads(path.read_text())
            self.assertTrue(result['complete'])
            self.assertTrue(result['native_subissues_verified'])
            self.assertFalse(path.with_suffix('.tmp').exists())


if __name__ == '__main__':
    unittest.main()
