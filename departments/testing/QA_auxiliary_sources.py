"""Pin serialized binary level data separately from the legacy text baseline."""
import hashlib
from pathlib import Path


def QA_auxiliary_fingerprint(root, check_cancelled):
    root=Path(root).resolve()
    digest=hashlib.sha256()
    count=0
    for folder in ('Assets','Packages','ProjectSettings'):
        for path in sorted((root/folder).rglob('*')):
            if path.suffix.lower() not in ('.bytes','.bin') or not path.is_file():
                continue
            relative=path.relative_to(root)
            if any((root/Path(*relative.parts[:i])).is_symlink() for i in range(1,len(relative.parts)+1)):
                continue
            check_cancelled()
            before=path.stat()
            digest.update(relative.as_posix().encode()+b'\0')
            digest.update(before.st_size.to_bytes(8,'big'))
            with path.open('rb') as stream:
                while chunk:=stream.read(262144):
                    digest.update(chunk)
                    check_cancelled()
            after=path.stat()
            if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise ValueError('读取期间二进制配置变化，请重试')
            count+=1
    return {'sha256':digest.hexdigest(),'files':count,'scope':'Assets/Packages/ProjectSettings中.bytes和.bin；只固定内容，不代表解码正确或美术资源已验收'}
