"""Run: uv run --project apps/api python fixtures/synthetic/build.py"""
from pathlib import Path
from closegraph.fixtures import build_fixture
if __name__=='__main__':
    build_fixture(Path(__file__).parent)
