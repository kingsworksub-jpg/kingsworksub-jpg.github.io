#!/usr/bin/env python3
"""Generate radar charts for products that lack them.

Scans content/posts and looks for missing radar chart SVG references.
Generates placeholder radar charts for each missing file.
"""

import os
import re
import sys
from pathlib import Path

# Radar chart SVG template (5-axis)
TEMPLATE = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 460" font-family="'Hiragino Sans','Noto Sans JP',sans-serif">
<rect x="0" y="0" width="500" height="460" rx="18" fill="#F8F6F1"/>
<text x="250" y="32" text-anchor="middle" font-size="21" font-weight="700" fill="#3A362E">{title}</text>
<!-- Grid rings -->
<polygon points="250.0,222.0 276.6,241.3 266.5,272.7 233.5,272.7 223.4,241.3 " fill="none" stroke="#DDD9CF" stroke-width="1"/>
<polygon points="250.0,194.0 303.3,232.7 282.9,295.3 217.1,295.3 196.7,232.7 " fill="none" stroke="#DDD9CF" stroke-width="1"/>
<polygon points="250.0,166.0 329.9,224.0 299.4,318.0 200.6,318.0 170.1,224.0 " fill="none" stroke="#DDD9CF" stroke-width="1"/>
<polygon points="250.0,138.0 356.5,215.4 315.8,340.6 184.2,340.6 143.5,215.4 " fill="none" stroke="#DDD9CF" stroke-width="1"/>
<polygon points="250.0,110.0 383.2,206.7 332.3,363.3 167.7,363.3 116.8,206.7 " fill="none" stroke="#B9B4A8" stroke-width="1"/>
<!-- Radii -->
<line x1="250" y1="250" x2="250" y2="110" stroke="#CFCABD" stroke-width="1"/>
<line x1="250" y1="250" x2="383.154" y2="206.74" stroke="#CFCABD" stroke-width="1"/>
<line x1="250" y1="250" x2="332.292" y2="363.26" stroke="#CFCABD" stroke-width="1"/>
<line x1="250" y1="250" x2="167.708" y2="363.26" stroke="#CFCABD" stroke-width="1"/>
<line x1="250" y1="250" x2="116.846" y2="206.74" stroke="#CFCABD" stroke-width="1"/>
<!-- Axis labels -->
<text x="250" y="62" text-anchor="middle" font-size="15" font-weight="600" fill="#4A4636">{ax0}</text>
<text x="429.296" y="192.998" text-anchor="start" font-size="15" font-weight="600" fill="#4A4636">{ax1}</text>
<text x="364.628" y="410.002" text-anchor="start" font-size="15" font-weight="600" fill="#4A4636">{ax2}</text>
<text x="135.372" y="410.002" text-anchor="end" font-size="15" font-weight="600" fill="#4A4636">{ax3}</text>
<text x="70.7042" y="192.998" text-anchor="end" font-size="15" font-weight="600" fill="#4A4636">{ax4}</text>
<!-- Data polygon with moderate values (3/5) -->
<polygon points="{points}" fill="#F76707" fill-opacity="0.28" stroke="#F76707" stroke-width="2.5" stroke-linejoin="round"/>
<!-- Data points -->
<circle cx="250" cy="138" r="4.5" fill="#F76707" stroke="#F8F6F1" stroke-width="1.5"/>
<circle cx="356.523" cy="215.392" r="4.5" fill="#F76707" stroke="#F8F6F1" stroke-width="1.5"/>
<circle cx="332.292" cy="363.26" r="4.5" fill="#F76707" stroke="#F8F6F1" stroke-width="1.5"/>
<circle cx="200.625" cy="317.956" r="4.5" fill="#F76707" stroke="#F8F6F1" stroke-width="1.5"/>
<circle cx="143.477" cy="215.392" r="4.5" fill="#F76707" stroke="#F8F6F1" stroke-width="1.5"/>
</svg>
'''

PLACEHOLDER_POINTS = "250.0,138.0 356.5,215.4 332.3,363.3 200.6,318.0 143.5,215.4"

def generate_radar(title, axes):
    """Generate a simple radar chart SVG."""
    if len(axes) != 5:
        raise ValueError(f"Expected 5 axes, got {len(axes)}")
    return TEMPLATE.format(
        title=title,
        ax0=axes[0], ax1=axes[1], ax2=axes[2], ax3=axes[3], ax4=axes[4],
        points=PLACEHOLDER_POINTS
    )

def find_missing_radars():
    """Find radar chart references that lack corresponding SVG files."""
    posts_dir = Path("content/posts")
    radar_dir = Path("static/images/radar")

    missing = {}

    for post in posts_dir.glob("*.md"):
        content = post.read_text(encoding="utf-8")
        # Find radar chart references
        for match in re.finditer(r'!\[[^\]]*レーダーチャート[^\]]*\]\((/images/radar/[^)]+\.svg)\)', content):
            path = match.group(1).lstrip("/")
            if not Path(path).exists():
                # Extract title context (2 lines before the reference)
                lines = content[:match.start()].split('\n')
                context = '\n'.join(lines[-3:])
                missing[path] = {
                    "post": post.name,
                    "context": context,
                }

    return missing

def create_placeholder_charts(missing):
    """Create placeholder radar chart files."""
    count = 0
    for path in missing:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        # Extract product name from filename
        title = p.stem.replace("-", " ").title()

        # Placeholder axes (5 common evaluation criteria)
        axes = [
            "セットアップ", "操作性", "立ち上げ", "拡張性", "耐久性"
        ]

        svg = generate_radar(title, axes)
        p.write_text(svg, encoding="utf-8")
        print(f"Created: {path}")
        count += 1

    return count

if __name__ == "__main__":
    missing = find_missing_radars()
    if missing:
        print(f"Found {len(missing)} missing radar chart(s):")
        for path, info in missing.items():
            print(f"  - {path} (in {info['post']})")
        count = create_placeholder_charts(missing)
        print(f"\nCreated {count} placeholder radar chart(s).")
        sys.exit(0)
    else:
        print("No missing radar charts found.")
        sys.exit(0)
