# PROMPT:
# Generate tests for a session-based retail funnel. Verify that re-entry events do not
# double-count a visitor and that purchase counts come from POS correlation.
#
# CHANGES MADE:
# Seeded a visitor with ENTRY, EXIT, and REENTRY under the same visitor_id to ensure the
# funnel unit remains the session/visitor token rather than raw event count.

from pathlib import Path
from unittest import TestCase

from app.analytics import compute_funnel
from tests.helpers import seed_events, workspace_tempdir


class FunnelTests(TestCase):
    def test_reentry_does_not_double_count_entry_stage(self) -> None:
        with workspace_tempdir() as tmp:
            db_path = tmp / "test.db"
            seed_events(db_path)

            funnel = compute_funnel("ST1008", db_path)
            counts = {stage["stage"]: stage["count"] for stage in funnel["stages"]}

            self.assertEqual(counts["Entry"], 3)
            self.assertEqual(counts["Billing Queue"], 2)
            self.assertEqual(counts["Purchase"], 1)
