import csv
import json
import tempfile
import unittest
from pathlib import Path

from momentum_screening_pure import ScreeningConfig
from portable_demo import run_portable_demo


class PortableDemoFinalValidationTest(unittest.TestCase):
    def test_final_validation_controls_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            manifest = run_portable_demo(path, ScreeningConfig())
            self.assertTrue(all(manifest["validation_checks"].values()))
            self.assertEqual(manifest["selection_summary"], {"US": 6, "JP": 6})
            self.assertEqual(manifest["regimes"]["JP"], "UNKNOWN")
            self.assertLess(manifest["advisory_exposure"], 1.0)
            for filename in ("quality_report.csv", "all_scores.csv", "selected_portfolio.csv", "review_required_orders.csv", "manifest.json"):
                self.assertTrue((path / filename).exists(), filename)
            with (path / "review_required_orders.csv").open() as order_file:
                orders = list(csv.DictReader(order_file))
            self.assertTrue(all(int(x["Shares"]) % 100 == 0 for x in orders if x["Region"] == "JP"))
            self.assertTrue(all(x["Status"] == "BLOCKED_FX_MISSING" for x in orders if x["Region"] == "US"))
            self.assertEqual(json.loads((path / "manifest.json").read_text())["quality_summary"]["rejected"], 4)


if __name__ == "__main__":
    unittest.main()
