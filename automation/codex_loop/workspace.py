"""Trusted data transfer and commands through the existing Seatbelt boundary."""
from __future__ import annotations
import contextlib
import fcntl
import json
import shutil
import sys
from pathlib import Path, PurePosixPath
import uuid

from automation.closegraph_loop.sandbox import create_workspace, _workspace
from .broker import run_owned


# This literal runs INSIDE Seatbelt. Never import a worker's Python modules on host.
OPERATIONS = r"""
import base64,errno,hashlib,json,os,pathlib,stat,subprocess,sys
payload=json.loads(pathlib.Path(sys.argv[1]).read_text())
os.environ['GIT_NO_REPLACE_OBJECTS']='1'
def git(*args):
 p=subprocess.run(['/usr/bin/git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-c','core.autocrlf=false',*args],capture_output=True,check=True)
 return p.stdout
def safe(name):
 p=pathlib.PurePosixPath(name)
 if p.is_absolute() or '..' in p.parts or '.git' in p.parts or not p.parts: raise ValueError('Unsafe path')
 q=pathlib.Path(name)
 if any(x.is_symlink() for x in (q,*q.parents)): raise ValueError('Symlink path')
 return q
def physical_tree_matches():
 for entry in git('ls-tree','-r','-z','HEAD').split(b'\0'):
  if not entry:continue
  metadata,name=entry.split(b'\t',1)
  mode,kind,expected=metadata.decode().split()
  if kind!='blob' or mode not in ('100644','100755'):return False
  try:
   path=safe(name.decode())
   info=path.lstat()
   if not stat.S_ISREG(info.st_mode):return False
   data=path.read_bytes()
   observed=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
   if observed!=expected or bool(info.st_mode & 0o111)!=(mode=='100755'):return False
  except OSError:return False
 return True
op=payload['op']
if op=='sync':
 dirty=bool(git('status','--porcelain','--untracked-files=no').strip())
 if not dirty and git('rev-parse','HEAD^{tree}').decode().strip()==payload['snapshot']['tree']:
  print(json.dumps({'local':git('rev-parse','HEAD').decode().strip(),'tree':payload['snapshot']['tree']}));sys.exit(0)
 if dirty and not payload.get('allow_dirty'):raise ValueError('Dirty workspace retained; refusing snapshot overwrite')
 tracked={name for name in git('ls-files','-z').decode().split('\0') if name}
 files=[]
 names=set()
 # Validate collisions before removing any tracked bytes. Ignored files count
 # as untracked content too; no recursive deletion of worker environments.
 for f in payload['snapshot']['files']:
  p=safe(f['path'])
  if str(p)!=f['path'] or f['path'] in names or f['mode'] not in ('100644','100755'):
   raise ValueError('Invalid snapshot file')
  names.add(f['path'])
  content=base64.b64decode(f['content'],validate=True)
  for parent in p.parents:
   if parent.exists() and not parent.is_dir() and str(parent) not in tracked:
    raise ValueError('Untracked content blocks snapshot: '+str(parent))
  if p.is_dir():
   for child in p.rglob('*'):
    if (child.is_symlink() or not child.is_dir()) and str(child) not in tracked:
     raise ValueError('Untracked content blocks snapshot: '+str(child))
  elif p.exists() and str(p) not in tracked:
   # An interrupted import may have written this exact new file before
   # staging it. Reuse only matching regular bytes under explicit recovery.
   if not payload.get('allow_dirty') or not p.is_file() or p.read_bytes()!=content:
    raise ValueError('Untracked content blocks snapshot: '+str(p))
  files.append((p,content,f['mode']))
 directories=set()
 for name in tracked:
  p=safe(name)
  if p.exists() and not (p.is_file() or p.is_dir()):raise ValueError('Tracked path is not a regular file: '+name)
  directories.update(parent for parent in p.parents if parent!=pathlib.Path('.'))
 for name in tracked:
  p=safe(name)
  # A partially imported file-to-directory transition may already have
  # made this a directory. Retain it and any untracked content within it.
  if p.is_file():p.unlink()
 for directory in sorted(directories,key=lambda p:len(p.parts),reverse=True):
  try:directory.rmdir()
  except OSError as exc:
   if exc.errno not in (errno.ENOENT,errno.ENOTDIR,errno.ENOTEMPTY,errno.EEXIST):raise
 for p,content,mode in files:
  p.parent.mkdir(parents=True,exist_ok=True)
  p.write_bytes(content);p.chmod(0o755 if mode=='100755' else 0o644)
 # Stage tracked deletions and explicit snapshot files only, never unrelated
 # untracked content that survived materialization.
 git('add','-u')
 for p,_,_ in files:git('add','-f','--',str(p))
 git('commit','--allow-empty','-m','Snapshot '+payload['snapshot']['sha'])
 result={'local':git('rev-parse','HEAD').decode().strip(),'tree':git('rev-parse','HEAD^{tree}').decode().strip()}
elif op=='capture':
 git('add','-A')
 if git('diff','--cached','--name-only').strip():git('commit','-m',payload['message'])
 head=git('rev-parse','HEAD').decode().strip()
 # Workers may create any number of commits. Preserve their original history,
 # then form one complete task delta with the declared base as its parent.
 git('branch','-f','preserved-before-capture-'+head[:12],head)
 tree=git('rev-parse','HEAD^{tree}').decode().strip()
 head=git('commit-tree',tree,'-p',payload['base'],'-m',payload['message']).decode().strip()
 git('reset','--hard',head)
 if not physical_tree_matches():raise ValueError('Physical tracked bytes or modes differ from candidate Git tree')
 changes=[]
 # The publisher consumes additions/deletions, never Git rename records.
 # Explicitly retain old-path deletions even when diff.renames is enabled.
 for raw in git('diff','--no-renames','--name-only','-z',payload['base'],head).decode().split('\0'):
  if not raw:continue
  safe(raw)
  entry=git('ls-tree','-z',head,'--',raw)
  if not entry:
   changes.append({'path':raw,'mode':'100644','content':None});continue
  metadata,name=entry[:-1].split(b'\t',1)
  mode,kind,sha=metadata.decode().split()
  if kind!='blob' or mode not in ('100644','100755'):raise ValueError('Only regular files may be published')
  content=git('cat-file','blob',sha)
  changes.append({'path':raw,'mode':mode,'content':base64.b64encode(content).decode()})
 result={'local':head,'tree':git('rev-parse','HEAD^{tree}').decode().strip(),'changes':changes}
elif op=='inspect':
 result={'local':git('rev-parse','HEAD').decode().strip(),'tree':git('rev-parse','HEAD^{tree}').decode().strip(),
 'dirty':bool(git('status','--porcelain').strip()),'physical_match':physical_tree_matches()}
elif op=='checkout':
 if git('status','--porcelain').strip():raise ValueError('Dirty workspace preserved before rebase')
 git('branch','-f',payload['checkpoint'],payload['candidate'])
 git('checkout','-B','controller-main',payload['base'])
 result={'ok':True}
elif op=='rebase':
 # The old implementation remains reachable before any replay. Conflicts stay in place for repair.
 git('branch','-f',payload['checkpoint'],payload['candidate'])
 p=subprocess.run(['/usr/bin/git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',
 'cherry-pick',payload['candidate']],capture_output=True,text=True)
 result={'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
else:raise ValueError('Unknown operation')
print(json.dumps(result))
"""


def validate_paths(paths):
    for name in paths:
        p = PurePosixPath(name)
        if not isinstance(name, str) or not name or name != str(p) or p.is_absolute() or any(c in (".git", "..") for c in p.parts):
            raise ValueError("Paths must be normalized relative files/directories without .git or traversal")
    return paths


def validate_changes(changes, owned):
    validate_paths(owned)
    names = set()
    for item in changes:
        name = item["path"]
        validate_paths([name])
        if name in names or not any(name == p or name.startswith(p.rstrip("/") + "/") for p in owned):
            raise ValueError("Duplicate or unowned changed file: " + name)
        names.add(name)
        if item["mode"] not in ("100644", "100755"):
            raise ValueError("Only regular files may be published")
        if item["content"] is not None:
            import base64
            base64.b64decode(item["content"], validate=True)
    if not changes:
        raise ValueError("No implementation changes; cannot claim issue completion")


class Sandbox:
    def __init__(self, base_repo, sandbox_root, timeout=1200, ports=(), dependency_seeds=None):
        self.base_repo, self.root, self.timeout, self.ports = base_repo, sandbox_root, timeout, ports
        self.dependency_seeds = dependency_seeds or {}
        allowed = {".venv", "apps/api/.venv", "node_modules", "apps/web/node_modules"}
        if set(self.dependency_seeds) - allowed:
            raise ValueError("Dependency seeds must target known untracked environment directories")
        for source in self.dependency_seeds.values():
            path = Path(source)
            if not path.is_absolute() or path.is_symlink() or not path.is_dir() or path.resolve() != path:
                raise ValueError("Dependency seeds must be trusted absolute directories without symlink ancestors")
            if path.is_relative_to(Path(sandbox_root)):
                raise ValueError("A worker cannot supply another worker's trusted dependency seed")
            for item in path.rglob("*"):
                if item.is_symlink():
                    target = item.resolve()
                    if not target.is_relative_to(path) and target != Path(sys.executable).resolve():
                        raise ValueError("Dependency seed has an external symlink: " + str(item))
                elif not item.is_dir() and not item.is_file():
                    raise ValueError("Dependency seed contains a special file")

    def allocate(self, key, role):
        workspace = str(create_workspace(self.base_repo, self.root, "codex-" + key.replace(".", "-") + "-" + role + "-" + uuid.uuid4().hex[:10]))
        for destination, source in self.dependency_seeds.items():
            tracked = self.run(workspace, ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "ls-files", "--", destination])
            if tracked["returncode"] or tracked["stdout"].strip():
                raise ValueError("Dependency seed would overwrite tracked repository files")
            target = Path(workspace) / destination
            if target.exists() or any(p.is_symlink() for p in (target, *target.parents)):
                raise ValueError("Dependency seed target already exists or traverses a symlink")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, symlinks=True)
        return workspace

    @contextlib.contextmanager
    def locked(self, workspace):
        _, worker, control = _workspace(workspace)
        with (control / ("codex-broker-" + worker.name + ".lock")).open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Workspace is still owned by a broker, bounded command supervisor or controller") from exc
            # Closing, rather than LOCK_UN, preserves the supervisor's
            # inherited flock when a caller exits or is cancelled.
            yield lock.fileno()

    def run(self, workspace, argv, timeout=None):
        with self.locked(workspace) as lock_fd:
            return run_owned(argv, workspace, self.timeout if timeout is None else timeout, self.ports, lock_fd)

    def operation(self, workspace, payload):
        with self.locked(workspace) as lock_fd:
            result = run_owned(["python3.12", "-I", "-c", OPERATIONS], workspace,
                               self.timeout, self.ports, lock_fd, payload=payload)
            if result["returncode"] or result.get("timed_out"):
                raise RuntimeError("Sandbox operation failed: " + result["stderr"][-6000:])
            return json.loads(result["stdout"])

    def sync(self, workspace, snapshot, allow_dirty=False):
        result = self.operation(workspace, {"op": "sync", "snapshot": snapshot, "allow_dirty": allow_dirty})
        if result["tree"] != snapshot["tree"]:
            raise RuntimeError("Materialized tree differs from GitHub snapshot")
        return result["local"]

    def capture(self, workspace, base, title, owned):
        result = self.operation(workspace, {"op": "capture", "base": base, "message": title})
        validate_changes(result["changes"], owned)
        return result

    def inspect(self, workspace):
        return self.operation(workspace, {"op": "inspect"})

    def verify(self, workspace, commands):
        if not commands:
            raise ValueError("At least one explicit validation command is required")
        results = []
        for argv in commands:
            execution = self.run(workspace, argv)
            results.append({"argv": argv, **execution})
            if execution["returncode"] != 0 or execution.get("timed_out"):
                return {"passed": False, "commands": results}
        return {"passed": True, "commands": results}
