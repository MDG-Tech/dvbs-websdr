"""Use an explicit Chromium, an installed cached shell, or Playwright's default."""
import os
from pathlib import Path

def browser_binary():
    if os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'):
        return os.environ['PLAYWRIGHT_CHROMIUM_EXECUTABLE']
    matches=sorted((Path.home()/'.cache/ms-playwright').glob(
        'chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell'))
    return str(matches[-1]) if matches else None
