"""HTML stripping is deterministic and offline-testable; the network calls are not
exercised here (they hit the live SEC API and are covered by ingest)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edgar


def test_html_to_text_strips_tags_and_scripts():
    raw = (
        "<html><head><style>.x{color:red}</style><script>var a=1;</script></head>"
        "<body><p>Risk factors matter.</p><div>Rates &amp; inflation</div></body></html>"
    )
    text = edgar.html_to_text(raw)
    assert "Risk factors matter." in text
    assert "Rates & inflation" in text
    assert "color:red" not in text  # style content dropped
    assert "var a=1" not in text  # script content dropped
    assert "<" not in text  # no tags survive


def test_html_to_text_collapses_whitespace():
    raw = "<p>a</p>\n\n\n\n<p>b</p>        c"
    text = edgar.html_to_text(raw)
    assert "\n\n\n" not in text
    assert "        " not in text
