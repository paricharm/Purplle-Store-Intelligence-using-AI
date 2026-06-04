# PROMPT:
# Build tests for a heatmap endpoint that returns zone frequency, dwell, normalization,
# and low-confidence flags for small sample sizes.
#
# CHANGES MADE:
# Checked configured zones with no visits as well as observed zones so the heatmap is
# ready for a grid renderer even when traffic is sparse.

from pathlib import Path
from unittest import TestCase

from app.analytics import compute_heatmap
from tests.helpers import seed_events, workspace_tempdir


class HeatmapTests(TestCase):
    def test_heatmap_marks_low_confidence_for_small_windows(self) -> None:
        with workspace_tempdir() as tmp:
            db_path = tmp / "test.db"
            seed_events(db_path)

            heatmap = compute_heatmap("ST1008", db_path)
            by_zone = {zone["zone_id"]: zone for zone in heatmap["zones"]}

            self.assertEqual(heatmap["data_confidence"], "LOW")
            self.assertIn("SKINCARE", by_zone)
            self.assertEqual(by_zone["SKINCARE"]["normalized_score"], 100)
            self.assertIn("FRAGRANCE", by_zone)
