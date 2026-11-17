#!/usr/bin/env python3
"""Read-only project document/link inventory. Does not fetch remote content."""
import argparse
import html
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zipfile

TEXT={'.md','.markdown','.txt','.csv','.tsv','.json','.yaml','.yml','.html','.htm','.url','.webloc','.rst'}
OFFICE={'.docx','.xlsx'}
OTHER={'.pdf','.doc','.xls','.ppt','.pptx','.png','.jpg','.jpeg','.webp'}
EXCLUDE={'.git','.codex','.agents','.idea','.vscode','node_modules','Library','Temp','Obj','obj','bin',
         'Logs','Build','Builds','__pycache__','.venv','venv','DerivedData','PackageCache'}
LINK=re.compile(r'https?://[^\s<>"\[\]{}]+',re.I)
DOC_PATH=re.compile(r'^/(?:docx|docs|wiki|sheets|base)/[^/\s]+',re.I)
DOC_WORDS=re.compile(r'需求|测试|用例|文档|链接|requirement|spec|test|qa|doc|link',re.I)

def feishu_url(raw):
    url=html.unescape(raw).rstrip('.,;，。；')
    # Parentheses can belong to query/fragment values; remove only unmatched closing delimiters.
    while url.endswith(')') and url.count(')')>url.count('('):url=url[:-1]
    try:
        parsed=urlsplit(url);host=(parsed.hostname or '').lower()
    except ValueError:return None
    trusted=any(host==d or host.endswith('.'+d) for d in ('feishu.cn','larksuite.com','doubao.com'))
    return url if trusted and DOC_PATH.match(parsed.path) else None

def extract(text,locator):
    rows=[]
    for line_no,line in enumerate(text.splitlines(),1):
        for match in LINK.finditer(line):
            url=feishu_url(match.group())
            if url:rows.append(dict(url=url,location=f'{locator}:{line_no}',context=line.strip()[:240]))
    return rows

def decode(raw):
    if raw.startswith((b'\xff\xfe',b'\xfe\xff')):return raw.decode('utf-16')
    for encoding in ('utf-8-sig','gb18030'):
        try:return raw.decode(encoding)
        except UnicodeDecodeError:pass
    raise ValueError('文本编码无法识别')

def read_links(path,limit):
    if path.stat().st_size>limit:raise ValueError('文件超过扫描大小限制')
    if path.suffix.lower()=='.webloc':
        value=plistlib.loads(path.read_bytes())
        return extract(str(value.get('URL','')),'plist.URL')
    if path.suffix.lower() in TEXT:return extract(decode(path.read_bytes()),'line')
    rows=[]
    with zipfile.ZipFile(path) as archive:
        members=[m for m in archive.infolist() if m.filename.endswith(('.xml','.rels')) and
                 m.filename.startswith(('word/','xl/'))]
        if sum(m.file_size for m in members)>32*1024*1024:raise ValueError('Office XML展开超过32MiB限制')
        for member in members:
            root=ET.fromstring(archive.read(member))
            text='\n'.join(''.join(n.itertext()) for n in root.iter() if n.tag.rsplit('}',1)[-1] in {'p','si','is','f','instrText'})
            rows.extend(extract(text,member.filename))
            for node in root.iter():
                for attr in ('Target','href'):
                    url=feishu_url(node.attrib.get(attr,''))
                    if url:rows.append(dict(url=url,location=member.filename,context='hyperlink relationship'))
    return rows

def enumerate_paths(project,search_dirs,include_ignored):
    if not shutil.which('rg'):raise RuntimeError('需要rg；请按项目约定使用可用文件枚举工具回退，不假报扫描成功')
    argv=['rg','--files','--hidden']
    if include_ignored:argv.append('--no-ignore')
    for folder in sorted(EXCLUDE):argv+=['-g',f'!**/{folder}/**']
    argv+=['-g','!**/QA/results/**','-g','!**/outputs/**','-g','!**/竞品解包/**']
    argv+=['--',*[str(p) for p in search_dirs]]
    result=subprocess.run(argv,cwd=project,capture_output=True,text=True)
    if result.returncode not in (0,1):raise RuntimeError(result.stderr.strip())
    for line in sorted(set(result.stdout.splitlines())):
        path=Path(line)
        if not path.is_absolute():path=project/path
        # rg does not follow directory symlinks; also refuse individual outside-file links.
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(project):continue
        if path.suffix.lower() in TEXT|OFFICE|OTHER:yield path

def discover(project,search_dirs=None,include_ignored=False,max_bytes=8*1024*1024):
    project=Path(project).resolve()
    if not project.is_dir():raise ValueError('项目目录不存在')
    dirs=[(project/Path(p)).resolve() for p in (search_dirs or ['.'])]
    if any(not p.is_dir() or not p.is_relative_to(project) for p in dirs):raise ValueError('search-dir必须是项目内现存目录')
    links=[];local=[];uninspected=[]
    for path in enumerate_paths(project,dirs,include_ignored):
        relative=str(path.relative_to(project));suffix=path.suffix.lower()
        document_candidate=bool(DOC_WORDS.search(relative)) or suffix in OFFICE|{'.pdf','.doc','.xls','.ppt','.pptx'}
        if document_candidate:
            kind='测试资料' if re.search(r'测试|用例|test|(?:^|/)qa(?:/|$)',relative,re.I) else '需求候选' if re.search(r'需求|requirement|spec',relative,re.I) else '参考文档'
            local.append(dict(name=path.name,path=relative,kind=kind))
        if suffix in OTHER:
            if document_candidate:uninspected.append(dict(path=relative,reason='需专用文档/图像工具检查链接与内容'))
            continue
        try:found=read_links(path,max_bytes)
        except (ValueError,OSError,ET.ParseError,zipfile.BadZipFile,RuntimeError) as err:
            uninspected.append(dict(path=relative,reason=str(err)));continue
        unique={}
        for row in found:
            item=unique.setdefault(row['url'],dict(url=row['url'],locations=[],context=row['context']))
            if row['location'] not in item['locations']:item['locations'].append(row['location'])
        if unique:links.append(dict(name=path.name,path=relative,link_count=len(unique),links=list(unique.values())))
    return dict(project=str(project),scope=dict(search_dirs=[str(p.relative_to(project)) for p in dirs],
        ignored_included=include_ignored,excluded=sorted(EXCLUDE)+['QA/results','outputs','竞品解包'],
        note='链接发现不是需求全文阅读；非支持格式、忽略目录和超限文件需定向补查'),
        link_files=links,local_documents=local,uninspected=uninspected)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True,type=Path)
    parser.add_argument('--search-dir',action='append')
    parser.add_argument('--include-ignored',action='store_true')
    parser.add_argument('--max-file-mib',type=int,default=8)
    args=parser.parse_args()
    if args.max_file_mib<=0:parser.error('--max-file-mib必须大于0')
    try:result=discover(args.project,args.search_dir,args.include_ignored,args.max_file_mib*1024*1024)
    except (RuntimeError,ValueError,OSError) as err:
        print(json.dumps(dict(error=str(err)),ensure_ascii=False),file=sys.stderr);return 1
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
