"""Runtime service bindings and durable per-run JSON stage storage."""
import hashlib
import json
import os
from pathlib import Path
import secrets

from dagster import IOManager, resource


def services_resource(services):
    @resource
    def configured_services(_context):
        return services
    return configured_services


class RunScopedJSONIOManager(IOManager):
    """Stage results cannot be loaded from another run's unpartitioned asset.

    Dagster's default filesystem asset manager keys unpartitioned assets only by
    asset name. Every path here pins run, step, output and dynamic mapping key.
    Atomic replacement supports a retry of the same step; PostgreSQL owns the
    immutable business effects, while this manager stores computational artifacts.
    """
    def __init__(self, base_dir):
        self.base = Path(base_dir).absolute()
        self.base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def identity(context):
        identity = [context.run_id, context.step_key, context.name, context.mapping_key]
        if any(not isinstance(value,str) or not value for value in identity[:3]):
            raise ValueError("A concrete run, step and output identity is required")
        return identity

    def path_for(self, context):
        identity = self.identity(context)
        encoded=json.dumps(identity,separators=(",",":")).encode()
        return self.base / (hashlib.sha256(encoded).hexdigest()+".json")

    def handle_output(self, context, obj):
        payload=json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
        envelope={"identity":self.identity(context),"sha256":hashlib.sha256(payload).hexdigest(),
                  "payload":json.loads(payload)}
        encoded=json.dumps(envelope,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
        destination=self.path_for(context)
        temporary=self.base/(".stage-"+secrets.token_hex(16))
        descriptor=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        try:
            with os.fdopen(descriptor,"wb") as stream:
                stream.write(encoded);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,destination)
            directory=os.open(self.base,os.O_RDONLY|os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def load_input(self, context):
        upstream=context.upstream_output
        if upstream is None:
            raise ValueError("An upstream run output is required")
        envelope=json.loads(self.path_for(upstream).read_bytes())
        if envelope["identity"]!=self.identity(upstream):
            raise ValueError("Stage identity mismatch")
        payload=json.dumps(envelope["payload"],sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
        if hashlib.sha256(payload).hexdigest()!=envelope["sha256"]:
            raise ValueError("Stage result integrity mismatch")
        return envelope["payload"]
