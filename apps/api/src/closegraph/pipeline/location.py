"""Configured Dagster code location; settings are required at process startup."""
from closegraph.runtime import build_services,data_dir
from closegraph.pipeline.definitions import build_definitions

defs=build_definitions(build_services(),str(data_dir()/'dagster-io'))
