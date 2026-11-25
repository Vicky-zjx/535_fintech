"""Offline guards for one-way research dependencies; never invoke a workflow."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkflowIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.production = (ROOT/'.github/workflows/nightly_orders.yaml').read_text()
        cls.research = (ROOT/'.github/workflows/investment-thesis.yaml').read_text()

    def test_production_keeps_its_schedule_and_existing_processing(self):
        self.assertIn("cron: '0 22 * * *'", self.production)
        self.assertIn('timezone: America/New_York', self.production)
        for command in ('python -m final_project.run --mode course',
                        'python -m final_project.historical',
                        'python -m final_project.lifecycle',
                        'python -m final_project.validate_publication'):
            self.assertIn(command, self.production)
        for key in ('LSEG_APP_KEY', 'LSEG_USERNAME', 'LSEG_PASSWORD'):
            self.assertIn('${{ secrets.'+key+' }}', self.production)
        self.assertIn('open_orders.json', self.production)
        self.assertIn('pages/builds', self.production)
        self.assertNotRegex(self.production, r'(?i)investment[_-]thesis|THESIS_|needs:|workflow_run:')

    def test_research_is_downstream_and_cannot_cancel_the_production_job(self):
        self.assertIn("workflows: ['Nightly risk-managed Wheel']", self.research)
        self.assertIn('types: [completed]', self.research)
        self.assertNotRegex(self.research, re.compile(r'^  (push|schedule):', re.MULTILINE))
        groups = [re.search(r'^  group: (.+)$', w, re.MULTILINE).group(1)
                  for w in (self.production, self.research)]
        self.assertNotEqual(*groups)
        self.assertIn('cancel-in-progress: false', self.research)
        self.assertNotRegex(self.research, r'secrets\.|final_project\.run|gh workflow|repository_dispatch')

    def test_publication_gate_is_after_computation_and_only_stages_aggregates(self):
        compute = self.research.index('run: python -m investment_thesis.refresh')
        permission = self.research.index('run: python -m investment_thesis.publication --require-approval')
        self.assertLess(compute, permission)
        self.assertNotIn('THESIS_PUBLICATION_APPROVED', self.production)
        staged = re.findall(r'^\s+git add -- (.+)$', self.research, re.MULTILINE)
        self.assertEqual(staged, ['investment-thesis/data/public_tracker.json investment-thesis/data/refresh_status.json'])
        self.assertNotIn('upload-artifact', self.research)
        self.assertNotIn('THESIS_PRIVATE_HISTORY', self.research)

    def test_production_modules_never_import_thesis_code(self):
        for directory in ('final_project', 'lseg_chart'):
            for path in (ROOT/directory).glob('*.py'):
                for node in ast.walk(ast.parse(path.read_text())):
                    names = ([x.name for x in node.names] if isinstance(node, ast.Import)
                             else [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                    self.assertFalse(any(n.startswith('investment_thesis') for n in names), str(path))

    def test_thesis_edits_cannot_trigger_the_live_chart_query(self):
        workflow = (ROOT/'.github/workflows/lseg-plot.yml').read_text()
        push_paths = re.findall(r"^      - '([^']+)'$", workflow, re.MULTILINE)
        self.assertTrue(push_paths)
        self.assertTrue(all(not p.startswith(('investment_thesis/', 'investment-thesis/'))
                            and p != '.github/workflows/investment-thesis.yaml'
                            for p in push_paths))


if __name__ == '__main__':
    unittest.main()
