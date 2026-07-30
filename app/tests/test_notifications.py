# tests/test_notifications.py — Windows toast notification logic
#
# win11toast is Windows-only and typically unavailable in the test environment,
# so WIN11TOAST_AVAILABLE and _notify are patched directly per-test.

from unittest.mock import patch

import ui.notifications as notifications


@patch.object(notifications, "WIN11TOAST_AVAILABLE", True)
@patch.object(notifications, "_notify", create=True)
def test_notify_track_skips_excluded_track(mock_notify):
    notifications.notify_track({"title": "Song", "artist": "Artist", "excluded": True})
    mock_notify.assert_not_called()


@patch.object(notifications, "WIN11TOAST_AVAILABLE", True)
@patch.object(notifications, "_notify", create=True)
def test_notify_track_fires_for_non_excluded_track(mock_notify):
    notifications.notify_track({"title": "Song", "artist": "Artist"})
    mock_notify.assert_called_once()
