"""Local build check for the GitHub Pages destination.

Delegates to distribution.py, which filters out articles whose `platforms` front matter does not
include "github". Use this instead of raw `hugo --minify` when checking what would be deployed.
Raw Hugo is still used by the cross-post renderers, which need HTML for every local article.

    python scripts/hugo_build.py [--destination public] [--baseURL URL]
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import distribution  # noqa: E402

if __name__ == "__main__":
    sys.exit(distribution.build_site(
        destination=os.environ.get("HUGO_DESTINATION", "public"),
        base_url=os.environ.get("HUGO_BASE_URL"),
    ))
