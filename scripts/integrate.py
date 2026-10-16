#!/usr/bin/env python3
"""Apply additive Backend/Portal modules with conflict detection and reversible backups."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

SOURCE = Path(__file__).resolve().parents[1]
STATE_NAME = '.meeting-integration-state.json'


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def changes(repo: Path) -> dict[str, bytes]:
    proposed: dict[str, bytes] = {}
    for component, target in [('backend','nodeskclaw-backend'),('portal','nodeskclaw-portal')]:
        for file in sorted((SOURCE/'integration'/component).rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts:
                proposed[str(Path(target)/file.relative_to(SOURCE/'integration'/component))] = file.read_bytes()
    backend = 'nodeskclaw-backend/app/api/router.py'
    portal = 'nodeskclaw-portal/src/router/index.ts'
    for name in (backend, portal):
        if not (repo/name).is_file():
            raise RuntimeError(f'Missing baseline file: {name}')
    text = (repo/backend).read_text(encoding='utf-8')
    marker = '# nodeskclaw-meeting integration v1'
    if marker not in text:
        if 'api_router = APIRouter(' not in text and 'api_router=APIRouter(' not in text:
            raise RuntimeError('Backend router shape changed; inspect and integrate manually')
        text += '\n\n'+marker+'\nfrom app.api.meeting_identity import router as meeting_identity_router\napi_router.include_router(meeting_identity_router)\n'
    proposed[backend] = text.encode()
    text = (repo/portal).read_text(encoding='utf-8')
    if '// nodeskclaw-meeting integration v1' not in text:
        needle = 'const ceRoutes: RouteRecordRaw[] = ['
        if needle not in text:
            raise RuntimeError('Portal router shape changed; inspect and integrate manually')
        text = "// nodeskclaw-meeting integration v1\nimport meetingRoutes from '@/features/meeting/routes'\n"+text
        text = text.replace(needle, needle+'\n  ...meetingRoutes,', 1)
    proposed[portal] = text.encode()
    return proposed


def apply(repo: Path, *, dry_run: bool = True):
    repo = repo.resolve()
    state_path = repo/STATE_NAME
    proposed = changes(repo)
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    changed = []
    for name, content in proposed.items():
        path = repo/name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != repo.parent):
            raise RuntimeError(f'Symlink target refused: {name}')
        old = path.read_bytes() if path.exists() else None
        if old == content:
            continue
        if name in previous and old is not None and sha(old) != previous[name]['installed_sha256']:
            raise RuntimeError(f'Locally modified integrated file: {name}')
        if name not in previous and old is not None and name not in {
            'nodeskclaw-backend/app/api/router.py','nodeskclaw-portal/src/router/index.ts'}:
            raise RuntimeError(f'Refusing to overwrite existing module: {name}')
        changed.append((name, content, old))
    if dry_run:
        return [name for name, _, _ in changed]
    backup = repo/'.meeting-integration-backup'
    for name, content, old in changed:
        path = repo/name
        if name not in previous:
            previous[name] = {'existed':old is not None}
            if old is not None:
                copy = backup/name; copy.parent.mkdir(parents=True, exist_ok=True); copy.write_bytes(old)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        previous[name]['installed_sha256'] = sha(content)
    state_path.write_text(json.dumps(previous, indent=2), encoding='utf-8')
    return [name for name, _, _ in changed]


def rollback(repo: Path):
    repo = repo.resolve(); state_path = repo/STATE_NAME
    if not state_path.exists():
        return []
    state = json.loads(state_path.read_text())
    for name, item in state.items():
        path = repo/name
        if path.is_symlink() or not path.is_file() or sha(path.read_bytes()) != item['installed_sha256']:
            raise RuntimeError(f'Refusing to roll back modified file: {name}')
    for name, item in state.items():
        path = repo/name
        if item['existed']:
            shutil.copyfile(repo/'.meeting-integration-backup'/name, path)
        else:
            path.unlink()
    state_path.unlink()
    return list(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        result = rollback(args.repo) if args.rollback else apply(args.repo, dry_run=not args.apply)
    except (RuntimeError, OSError, ValueError) as exc:
        parser.exit(1, str(exc)+'\n')
    print(('APPLIED' if args.apply else 'ROLLED BACK' if args.rollback else 'DRY RUN')+': '+str(len(result))+' files')
    print('\n'.join(result))


if __name__ == '__main__':
    main()
