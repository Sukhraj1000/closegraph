from concurrent.futures import ThreadPoolExecutor

import pytest
from closegraph.contracts import Scope
from closegraph.storage.blobs import BlobIntegrityError, BlobNotFound, LocalBlobStore

S = Scope(tenant_id="t", fund_id="f", pack_id="p")


def test_immutable_scoped_roundtrip_and_dedupe(tmp_path):
    store = LocalBlobStore(tmp_path)
    a = store.put(S, b"original bytes")
    assert store.put(S, b"original bytes") == a
    b = store.put(S, b"revised bytes")
    assert a != b and store.read(S, a) == b"original bytes"
    with pytest.raises(BlobNotFound): store.read(S.model_copy(update={"fund_id":"other"}), a)
    with pytest.raises(ValueError): store.read(S, "../../outside")
    assert store.read(S, b) == b"revised bytes"


def test_concurrent_put_and_integrity(tmp_path):
    store = LocalBlobStore(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _: store.put(S, b"same bytes"), range(24)))
    assert len(set(keys)) == 1
    path = next(p for p in tmp_path.rglob(keys[0]) if p.is_file())
    path.chmod(0o600); path.write_bytes(b"corrupt")
    with pytest.raises(BlobIntegrityError): store.read(S, keys[0])
    with pytest.raises(BlobIntegrityError): store.put(S, b"same bytes")


def test_bounded_size_and_symlinks(tmp_path):
    store = LocalBlobStore(tmp_path/"blobs", max_bytes=4)
    with pytest.raises(ValueError): store.put(S, b"12345")
    digest = store.put(S, b"1234")
    path = next((tmp_path/"blobs").rglob(digest))
    path.chmod(0o600); path.unlink()
    target = tmp_path/"outside"; target.write_bytes(b"1234")
    path.symlink_to(target)
    with pytest.raises(BlobIntegrityError): store.read(S, digest)
