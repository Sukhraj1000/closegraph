"""Install under the active profile's scripts/closegraph/monitor.py."""
import subprocess

subprocess.run(
    ['/Users/sukhrajkalon/.local/bin/python3.12', '-m', 'automation.cron_tools', 'monitor'],
    cwd='/Users/sukhrajkalon/projects/closegraph',
    check=True,
    timeout=210,
)
