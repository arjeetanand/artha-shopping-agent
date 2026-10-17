import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.service_logger import append_service_log


IST = timezone(timedelta(hours=5, minutes=30))


class ServiceLoggerTests(unittest.TestCase):
    def test_appends_redacted_events_and_resets_on_ist_day_change(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "flipkart" / "logger.txt"
            first = datetime(2026, 10, 17, 10, tzinfo=IST)
            append_service_log(path, service="flipkart", run_id="sync-test", step="page_scan", status="warning",
                               details={"card_count": 0, "body_chars": 420, "order_id": "private-order-id"}, now=first)
            append_service_log(path, service="flipkart", run_id="sync-test", step="login_detected", status="info",
                               details={"auth_detected": True}, now=first + timedelta(hours=5))
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["card_count"], 0)
            self.assertNotIn("private-order-id", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

            prior_day = datetime(2026, 10, 16, 23, 59, tzinfo=IST)
            os.utime(path, (prior_day.timestamp(), prior_day.timestamp()))
            append_service_log(path, service="flipkart", run_id="sync-next", step="sync_started", status="info", now=first)
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["run_id"], "sync-next")


if __name__ == "__main__":
    unittest.main()
