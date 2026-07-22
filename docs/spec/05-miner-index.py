#!/usr/bin/env python3
# @package automation-mining
# @description Automation Miner Registry builder
# @provides miner-index, automation-mining
# @requires-python 3.8+

"""
miner-index.py — Build and update the Automation Miner Registry (registry.json)
Rebuilds cross-indices from partitioned AM-XXX opps.

Usage:
  python3 scripts/miner-index.py [--path obsidian/automation-mining]
"""

import os, sys, json, re, argparse
from pathlib import Path
from datetime import datetime

def parse_yaml_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter from markdown file (simple parser)."""
    result = {}
    m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not m:
        return result
    for line in m.group(1).split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' in line:
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # Handle arrays
            if val.startswith('[') and val.endswith(']'):
                val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(',') if v.strip()]
            result[key] = val
    return result  # always dict

SLUG_LABEL = {
    'german-healthcare': 'German Healthcare System',
    'real-estate-smart-building': 'Real Estate + Smart Building Management',
    'carrier-bidding-eshop': 'Carrier Bidding & Negotiation (eShop Perspective)',
    'precision-irrigation': 'Precision Irrigation (Agriculture Sensors & Weather)',
    'greenhouse-climate': 'Greenhouse Climate Control & Automation',
    'wine-cellar-inventory': 'Wine Cellar Inventory & Maturation Tracking',
}

def build_registry(base_path: str) -> dict:
    base = Path(base_path)
    opps_dir = base / 'opps'

    entries = []
    domains_seen = {}

    if opps_dir.exists():
        for domain_dir in sorted(opps_dir.iterdir()):
            if not domain_dir.is_dir():
                continue
            slug = domain_dir.name
            label = SLUG_LABEL.get(slug, slug.replace('-', ' ').title())
            domain_opps = []
            for f in sorted(domain_dir.glob('AM-*.md')):
                text = f.read_text(encoding='utf-8')
                meta = parse_yaml_frontmatter(text)
                # Build compact entry
                entry = {
                    'i': meta.get('am-id', ''),
                    't': meta.get('title', f.stem),
                    'l': meta.get('layer', 'unknown'),
                    'ice': int(meta.get('ice-score', 0)),
                    'd': slug,
                    's': meta.get('status', 'identified'),
                    'f': str(f),
                }
                # Add ICE components if available (use distinct chars)
                imap = {'impact': 'im', 'confidence': 'co', 'ease': 'ea'}
                for k, short in imap.items():
                    v = meta.get(k.lower(), meta.get(k, ''))
                    if v:
                        try:
                            entry[short] = int(v)
                        except (ValueError, TypeError):
                            pass
                entries.append(entry)
                domain_opps.append(entry['i'])

            if domain_opps:
                top = max(domain_opps, key=lambda x: next(
                    (e['ice'] for e in entries[-len(domain_opps):] if e['i'] == x), 0))
                top_ice = next(
                    (e['ice'] for e in entries[-len(domain_opps):] if e['i'] == top), 0)
                domains_seen[slug] = {
                    'id': slug,
                    'title': label,
                    'slug': slug,
                    'total': len(domain_opps),
                    'top_ice': top_ice,
                    'top_opp': top,
                }

    # Build cross-indices
    by_layer = {'document': [], 'communication': [], 'decision': [],
                'monitoring': [], 'knowledge': []}
    by_ice_range = {'vision_80plus': [], 'high_60_79': [],
                    'medium_40_59': [], 'low_under_40': []}
    by_status = {'identified': [], 'validating': [], 'designing': [],
                 'building': [], 'live': [], 'deprecated': []}

    for e in entries:
        layer = e['l']
        if layer in by_layer:
            by_layer[layer].append(e['i'])

        ice = e['ice']
        if ice >= 80:
            by_ice_range['vision_80plus'].append(e['i'])
        elif ice >= 60:
            by_ice_range['high_60_79'].append(e['i'])
        elif ice >= 40:
            by_ice_range['medium_40_59'].append(e['i'])
        else:
            by_ice_range['low_under_40'].append(e['i'])

        status = e['s']
        if status in by_status:
            by_status[status].append(e['i'])
        else:
            by_status['identified'].append(e['i'])

    # Summary stats
    total = len(entries)
    ices = [e['ice'] for e in entries]
    avg_ice = round(sum(ices) / len(ices), 1) if ices else 0
    top = max(entries, key=lambda e: e['ice']) if entries else {}
    bottom = min(entries, key=lambda e: e['ice']) if entries else {}

    registry = {
        'v': 2,
        'ts': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'stats': {
            'runs': len(domains_seen),
            'opps': total,
            'avg_ice': avg_ice,
            'top_ice': top.get('ice', 0),
            'top_id': top.get('i', ''),
            'top_title': top.get('t', ''),
            'bot_ice': bottom.get('ice', 0),
            'layers': {k: len(v) for k, v in by_layer.items()},
            'statuses': {k: len(v) for k, v in by_status.items()},
        },
        'domains': sorted(domains_seen.values(), key=lambda x: x['id']),
        'by_layer': by_layer,
        'by_ice_range': by_ice_range,
        'by_status': by_status,
        'entries': sorted(entries, key=lambda e: e['ice'], reverse=True),
    }

    return registry


def main():
    parser = argparse.ArgumentParser(description='Build Automation Miner Registry')
    parser.add_argument('--path', default='obsidian/automation-mining',
                        help='Path to automation-mining directory')
    args = parser.parse_args()

    base_path = args.path
    if not os.path.isdir(base_path):
        print(f'❌ Directory not found: {base_path}')
        sys.exit(1)

    registry = build_registry(base_path)
    output_file = os.path.join(base_path, 'registry.json')

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    s = registry['stats']
    print(f'✅ Registry written: {output_file}')
    print(f'   Runs: {s["runs"]} | Opps: {s["opps"]}')
    print(f'   Avg ICE: {s["avg_ice"]} | Top: {s["top_id"]} ({s["top_ice"]}) | Bottom: {s["bot_ice"]}')
    print(f'   Layers: {s["layers"]}')
    print(f'   Statuses: {s["statuses"]}')
    print(f'   Domains: {len(registry["domains"])}')


if __name__ == '__main__':
    main()
