"""Read-only status/change detection and sandbox probe CLI, not a dispatcher.

Native Hermes cron owns scheduling. Actual coding/review adapters and trusted
publishing/merge integration require a supervised activation follow-up.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = 'Sukhraj1000/closegraph'


def status() -> dict:
    return {
        'repo': REPO,
        'mode': 'paused-setup',
        'dispatch_available': False,
        'auto_merge': False,
        'blockers': [
            'Select and verify a real sandboxed coding/review adapter and trusted publishing path.',
            'Configure a distinct eligible GitHub reviewer identity.',
            'Private main branch protection returned HTTP 403; preserve private visibility.',
            'Verify per-task tests and one supervised loop before explicit user activation.',
        ],
    }


def gh_json(*args) -> Any:
    result = subprocess.run(['gh', *args], text=True, capture_output=True,
                            check=True, timeout=60)
    return json.loads(result.stdout)


def monitor() -> dict:
    """Stable read-only snapshot. Errors fail, rather than masquerading as idle."""
    issues = gh_json('issue', 'list', '--repo', REPO, '--state', 'open', '--limit', '1000',
                     '--json', 'number,title,labels,updatedAt')
    prs = gh_json('pr', 'list', '--repo', REPO, '--state', 'open', '--limit', '1000',
                 '--json', 'number,title,isDraft,headRefOid,baseRefName,reviewDecision,updatedAt')
    base = gh_json('api', f'repos/{REPO}/commits/main', '--jq', '{sha:.sha}')
    for issue in issues:
        issue['labels'] = sorted(issue.get('labels', []), key=lambda x: x['name'])
    # Do not silently truncate if the bounded query reaches its ceiling.
    if len(issues) >= 1000 or len(prs) >= 1000:
        raise RuntimeError('Snapshot limit reached; pagination required')
    return {**status(), 'base_sha': base['sha'],
            'issues': sorted(issues, key=lambda x: x['number']),
            'prs': sorted(prs, key=lambda x: x['number'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'monitor', 'sandbox-self-test'])
    args = parser.parse_args()
    if args.command == 'sandbox-self-test':
        from automation.closegraph_loop.sandbox import self_test
        result = self_test(ROOT, ROOT.parent / 'closegraph-sandboxes')
        print(json.dumps(result, indent=2))
        if not result['ok']:
            raise SystemExit(1)
    else:
        print(json.dumps(status() if args.command == 'status' else monitor(), sort_keys=True))


if __name__ == '__main__':
    main()
