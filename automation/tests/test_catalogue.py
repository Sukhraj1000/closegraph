import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation import publish_issues as publisher
from automation import build_catalogue as builder


class CatalogueTests(unittest.TestCase):
    def test_original_tasks_exactly_once_and_topological_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / builder.CHANGE / 'tasks.md'
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

    def test_archived_completed_tasks_preserve_all_original_ids_without_publishing(self):
        historical_source = builder.ROOT / "docs/engineering/issue-catalog.json"
        historical_bytes = historical_source.read_bytes()
        historical = json.loads(historical_bytes)
        original_ids = [task for issue in historical["issues"] for task in issue["spec_tasks"]]
        self.assertEqual(len(original_ids), 40)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "openspec/changes/archive/2026-09-05-verify-corrected-reporting-pack"
            archive.mkdir(parents=True)
            (archive / "tasks.md").write_text("\n".join(
                f"- [{'x' if index % 2 else 'X'}] {task} Completed fixture task {task}"
                for index, task in enumerate(original_ids)) + "\n")
            historical_path = root / "historical-catalog.json"
            historical_path.write_bytes(historical_bytes)
            with patch.object(builder, "ROOT", root), patch.object(publisher, "ROOT", root), \
                    patch.object(publisher, "gh", side_effect=AssertionError("No publishing is allowed")):
                _, ordered = publisher.load_catalog(historical_path)
                self.assertEqual(sorted(task for issue in ordered for task in issue["spec_tasks"]),
                                 sorted(original_ids))
                builder.build()
                generated = root / "docs/engineering/issue-catalog.json"
                _, rebuilt = publisher.load_catalog(generated)
                self.assertEqual(sorted(issue["key"] for issue in rebuilt),
                                 sorted(issue["key"] for issue in historical["issues"]))
                self.assertEqual(sorted(task for issue in rebuilt for task in issue["spec_tasks"]),
                                 sorted(original_ids))
                for issue in rebuilt:
                    if issue["spec_tasks"]:
                        self.assertIn(str(archive.relative_to(root)) + "/tasks.md", issue["body"])
                self.assertEqual(historical_path.read_bytes(), historical_bytes)
        self.assertEqual(historical_source.read_bytes(), historical_bytes)

    def test_source_resolution_prefers_active_and_only_accepts_the_exact_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            active = root / builder.CHANGE
            archived = root / "openspec/changes/archive/2026-09-05-verify-corrected-reporting-pack"
            for directory in (active, archived):
                directory.mkdir(parents=True)
                (directory / "tasks.md").write_text("- [x] 1.1 fixture\n")
            self.assertEqual(builder.resolve_change(root), active)
            (active / "tasks.md").unlink()
            self.assertEqual(builder.resolve_change(root), archived)
            (archived / "tasks.md").unlink()
            unrelated = root / "openspec/changes/archive/2026-09-06-other-change"
            unrelated.mkdir(parents=True)
            (unrelated / "tasks.md").write_text("- [x] 1.1 unrelated\n")
            with self.assertRaises(FileNotFoundError):
                builder.resolve_change(root)

    def test_direct_read_only_cli_runs_with_python_safe_path(self):
        source = builder.ROOT / "docs/engineering/issue-catalog.json"
        original = source.read_bytes()
        environment = dict(os.environ, PYTHONSAFEPATH="1")
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, str(Path(publisher.__file__).resolve()), "--catalog", str(source)],
                cwd=temp, env=environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertFalse(summary["applied"])
        self.assertEqual(summary["product_tasks"], 40)
        self.assertEqual(source.read_bytes(), original)

    def test_renderer_keeps_stable_marker_and_real_links(self):
        item = {'key':'T1.1','body':'Actual task scope','epic':'E1','depends_on':['A01']}
        rendered = publisher.render(item, {'E1':{'url':'https://github.com/example/repo/issues/1'},
                                         'A01':{'url':'https://github.com/example/repo/issues/2'}})
        self.assertIn('<!-- closegraph:catalog=T1.1 -->',rendered)
        self.assertIn('https://github.com/example/repo/issues/1',rendered)
        self.assertIn('Standing engineering authorization',rendered)
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
