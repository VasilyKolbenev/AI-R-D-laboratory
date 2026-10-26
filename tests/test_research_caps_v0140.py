"""Mechanical limits for LAB-014 additions, without reformatting historical files."""
from pathlib import Path
import unittest

CAPPED = {
    'tests/test_dark_label_height_v0152.py': 800,
    'laboratory/channel_layout.py': 800,
    'tests/test_channel_layout_v0151.py': 800,
    'tests/test_channel_layout_integration_v0151.py': 800,
    'laboratory/research_continuation.py': 800,
    'laboratory/checkpoint_runtime.py': 800,
    'laboratory/compact_editor.py': 800,
    'tests/test_checkpoint_v0150.py': 800,
    'tests/test_checkpoint_runtime_v0150.py': 800,
    'tests/test_checkpoint_integration_v0150.py': 800,
    'tests/test_checkpoint_delivery_v0150.py': 800,
    'tests/test_compact_editor_v0150.py': 800,
    'laboratory/research_failure.py': 800,
    'tests/test_cycle_integration_v0141.py': 800,
    'tests/test_web_budget_v0141.py': 800,
    'laboratory/evidence_archive.py': 800,
    'laboratory/evidence_validation.py': 800,
    'laboratory/grounded_protocol.py': 800,
    'laboratory/research_api.py': 800,
    'laboratory/research_assets.py': 800,
    'laboratory/research_evaluation.py': 800,
    'laboratory/research_experiments.py': 800,
    'laboratory/research_public.py': 800,
    'laboratory/research_views.py': 800,
    'laboratory/research_workbench.py': 800,
    'laboratory/web/research.js': 800,
    'laboratory/web/research.css': 800,
    'tests/test_evidence_archive_v0140.py': 800,
    'tests/test_evidence_validation_v0140.py': 800,
    'tests/test_grounded_flow_v0140.py': 800,
    'tests/test_research_assets_v0140.py': 800,
    'tests/test_research_caps_v0140.py': 800,
    'tests/test_research_evaluation_v0140.py': 800,
    'tests/test_research_experiments_v0140.py': 800,
    'tests/test_research_http_v0140.py': 800,
    'tests/test_research_public_v0140.py': 800,
    'tests/test_research_views_v0140.py': 800,
    'tests/test_research_visual_v0140.py': 800,
    'tests/test_research_workbench_v0140.py': 800,
}


class ResearchFileLimits(unittest.TestCase):
    def test_new_files_have_bounded_lines_and_canonical_text_encoding(self):
        root = Path(__file__).resolve().parents[1]
        for name, limit in CAPPED.items():
            with self.subTest(file=name):
                raw = (root / name).read_bytes()
                self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
                self.assertNotIn(b'\r', raw)
                text = raw.decode('utf-8', errors='strict')
                self.assertTrue(text.endswith('\n'))
                self.assertFalse(text.endswith('\n\n'))
                self.assertLessEqual(len(text.splitlines()), limit)
                self.assertFalse(any(len(line) > 100 for line in text.splitlines()))
                self.assertFalse(any(line.rstrip() != line for line in text.splitlines()))


if __name__ == '__main__':
    unittest.main()
