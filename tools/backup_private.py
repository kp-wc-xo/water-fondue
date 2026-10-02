"""Private report backup. Stop writes before running; keep output outside public Git."""
import argparse,gzip,json,sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from water_fondue.storage import SupabaseStore
from water_fondue.http import request
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
root=Path(a.output)
if root.exists():raise SystemExit('Choose a NEW output directory to avoid mixing backups')
root.mkdir(parents=True);(root/'photos').mkdir();store=SupabaseStore();counts={}
try:
 with gzip.open(root/'private.jsonl.gz','wt',encoding='utf-8') as f:
  for table in ('reports','line_events','state'):
   offset=0;counts[table]=0;order='key' if table=='state' else 'id'
   while True:
    q=urlencode({'select':'*','order':order,'limit':500,'offset':offset})
    rows=request(store.url+'/rest/v1/'+table+'?'+q,headers=store.headers,retry=True)
    for row in rows:
     f.write(json.dumps({'table':table,'row':row},ensure_ascii=False)+'\n');counts[table]+=1
     if table=='reports' and row.get('photo_path'):
      name=row['photo_path']
      if name!=Path(name).name:raise ValueError('Unexpected photo key')
      with urlopen(Request(store.url+'/storage/v1/object/authenticated/report-photos/'+name,headers=store.headers),timeout=30) as r:
       (root/'photos'/name).write_bytes(r.read())
    if len(rows)<500:break
    offset+=len(rows)
 (root/'COMPLETE.json').write_text(json.dumps(counts),encoding='utf-8');print('Backup complete:',counts)
except Exception:
 print('Backup INCOMPLETE. Keep originals and retry into a new folder.');raise SystemExit(1)
