"""Python 3.10+; standard library only. See README_TH.md before use."""
import argparse, csv, hashlib, json, sqlite3, statistics, time
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

LATEST = 'https://api-v3.thaiwater.net/api/v1/thaiwater30/provinces/waterlevel'
MASTER = 'https://raw.githubusercontent.com/kongvut/thai-province-data/refs/heads/master/api/latest/'
ICT = timezone(timedelta(hours=7))

def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'Accept':'application/json','User-Agent':'ThaiWaterResearch/1.0'}), timeout=45) as r:
                return json.load(r)
        except HTTPError as e:
            if e.code not in (429,500,502,503,504) or attempt == 2: 
                raise
        except (URLError, TimeoutError):
            if attempt == 2: 
                raise
        time.sleep(2 ** (attempt+1))

def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

#Select records for JSON
def rows_of(payload, path='data'):
    obj=payload
    for key in path.split('.') if path else []: obj=obj[key]
    if not isinstance(obj,list) or any(not isinstance(r,dict) for r in obj):
        raise ValueError('Expected list of objects; inspect saved raw JSON and specify --rows-path')
    return obj

#Nested JSON to Flat JSON
def flatten(obj, prefix=''):
    result={}
    for key,value in obj.items():
        key=prefix+key
        if isinstance(value,dict): result.update(flatten(value,key+'.'))
        elif isinstance(value,list): result[key]=json.dumps(value,ensure_ascii=False)
        else: result[key]=value
    return result

#แก้ก่อนใช้จริง ถ้ารอบใหม่ไม่มีข้อมูล ฟังก์ชันจะไม่เขียนอะไร ทำให้ latest.csv เก่ายังค้างอยู่ และอาจถูกเข้าใจผิดว่าเป็นข้อมูลใหม่
def csvwrite(path, rows):
    if not rows: return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    tmp=path.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
    tmp.replace(path)

def stamp(value):
    dt=datetime.fromisoformat(str(value).replace('/', '-').replace('Z','+00:00'))
    return dt.replace(tzinfo=ICT) if dt.tzinfo is None else dt

##
def database(out):
    db=sqlite3.connect(out/'waterlevel.sqlite',timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS observations (station TEXT, observed_at TEXT, first_seen TEXT, last_seen TEXT, payload TEXT, PRIMARY KEY(station,observed_at))')
    return db

def collect(args,out):
    now=datetime.now(timezone.utc).isoformat()
    payload=fetch(args.url)
    raw=out/'raw';raw.mkdir(exist_ok=True)
    dump(raw/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json'),payload)
    if isinstance(payload,dict) and payload.get('result') not in (None,'OK'): raise ValueError('API result is not OK')
    rows=[flatten(x) for x in rows_of(payload,args.rows_path)]
    if args.province:
        rows=[r for r in rows if str(r.get('geocode.province_code',''))==args.province]
    for r in rows:
        pc=str(r.get('geocode.province_code','')); 
        ac=str(r.get('geocode.amphoe_code',''))
        r['district_code']=pc+ac if len(pc)==2 and len(ac)==2 and pc.isdigit() and ac.isdigit() else None
    csvwrite(out/'latest.csv',rows)
    accepted=0
    with database(out) as db:
        for row in rows:
            # Never use top-level observation id as a stable station id.
            station=row.get(args.station_field) if args.station_field else next((row.get(k) for k in ('station.id','tele_station.id','waterlevel_station.id') if row.get(k) is not None),None)
            observed=row.get(args.time_field)
            if station is None or not observed: continue
            ts=stamp(observed).isoformat()
            key=str(row.get('agency.id',''))+':'+str(station)
            db.execute('INSERT INTO observations VALUES (?,?,?,?,?) ON CONFLICT(station,observed_at) DO UPDATE SET last_seen=excluded.last_seen,payload=excluded.payload',(key,ts,now,now,json.dumps(row,ensure_ascii=False)))
            accepted+=1
    print(f'Rows={len(rows)}; stored={accepted}; output={out}')
    if rows and not accepted: print('Inspect latest.csv; set --station-field to a stable station identifier. Raw and CSV were saved.')

def report(out):
    groups={}
    with database(out) as db:
        for station,ts in db.execute('SELECT station,observed_at FROM observations'):
            groups.setdefault(station,[]).append(stamp(ts))
    result=[]
    for station,values in groups.items():
        values=sorted(set(values)); gaps=[(b-a).total_seconds()/60 for a,b in zip(values,values[1:])]
        result.append(dict(station=station,samples=len(values),earliest=values[0].isoformat(),latest=values[-1].isoformat(),min_gap_minutes=min(gaps) if gaps else None,median_gap_minutes=statistics.median(gaps) if gaps else None,max_gap_minutes=max(gaps) if gaps else None))
    csvwrite(out/'cadence.csv',result)
    print('cadence.csv:',len(result),'stations. Observed gaps are not a guaranteed source update schedule.')

def master(out):
    provinces=fetch(MASTER+'province.json'); districts=fetch(MASTER+'district.json')
    dump(out/'source_province.json',provinces);dump(out/'source_district.json',districts)
    pmap={p['id']:p for p in provinces if not p.get('deleted_at')}
    result=[]; seen=set(); pcodes={}
    for d in districts:
        if d.get('deleted_at'): continue
        code=str(d['id']);p=pmap[d['province_id']]
        if not(code.isdigit() and len(code)==4) or code in seen: raise ValueError('Unexpected/duplicate district code')
        seen.add(code);pcodes.setdefault(p['id'],set()).add(code[:2])
        result.append(dict(province_code=code[:2],province_name_th=p['name_th'],province_name_en=p['name_en'],district_code=code,district_name_th=d['name_th'],district_name_en=d['name_en'],source_province_id=p['id']))
    if len(pmap)!=77 or set(pcodes)!=set(pmap) or any(len(v)!=1 for v in pcodes.values()): raise ValueError('Province coverage/prefix validation failed')
    csvwrite(out/'master_province_district.csv',sorted(result,key=lambda x:x['district_code']))
    csvwrite(out/'master_province.csv',[dict(province_code=next(iter(pcodes[p['id']])),province_name_th=p['name_th'],province_name_en=p['name_en'],source_province_id=p['id']) for p in pmap.values()])
    dump(out/'master_provenance.json',dict(retrieved_at=datetime.now(timezone.utc).isoformat(),source=MASTER,provinces=len(pmap),districts=len(result),note='Community dataset; province_code derived from district code prefix. Not yet cross-validated against ThaiWater master.'))
    print('Master:',len(pmap),'provinces;',len(result),'districts')

def history(args,out):
    # Native endpoint verified in the website JavaScript.
    if args.station:
        args.url_template=('https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph?station_type=tele_waterlevel&station_id='+str(args.station)+'&start_date={date}&end_date={date}'+('&table=manual' if args.manual else ''))
        args.rows_path='data.graph_data';args.time_field='datetime'
    if not args.url_template or '{date}' not in args.url_template: raise ValueError('Provide confirmed history --url-template containing {date}; latest endpoint cannot backfill')
    start=date.fromisoformat(args.start);end=date.fromisoformat(args.end)
    if start>end: raise ValueError('start must not exceed end')
    audit=[];seen=set()
    while start<=end:
        payload=fetch(args.url_template.replace('{date}',start.isoformat()).replace('{next_date}',(start+timedelta(days=1)).isoformat()))
        dump(out/('history_'+start.isoformat()+'.json'),payload)
        rows=[flatten(r) for r in rows_of(payload,args.rows_path)]
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        times=[stamp(r[args.time_field]) for r in rows if r.get(args.time_field)]
        matches=[t for t in times if t.astimezone(ICT).date()==start]
        audit.append(dict(requested_date=start.isoformat(),rows=len(rows),non_null_values=sum(r.get('value') is not None for r in rows),dated_rows=len(times),rows_on_requested_date=len(matches),earliest=min(times).isoformat() if times else None,latest=max(times).isoformat() if times else None,repeated_payload=digest in seen))
        seen.add(digest);csvwrite(out/('history_'+start.isoformat()+'.csv'),rows)
        start+=timedelta(days=1);time.sleep(1)
    csvwrite(out/'history_audit.csv',audit)
    print('Review history_audit.csv. Empty dates do not prove retention limits; repeated/out-of-range data can indicate ignored parameters.')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['latest','report','master','history'])
    p.add_argument('--out',default='data');p.add_argument('--url',default=LATEST)
    p.add_argument('--province',help='e.g. 64 Sukhothai, 30 Nakhon Ratchasima');p.add_argument('--rows-path',default='data');p.add_argument('--station-field')
    p.add_argument('--time-field',default='waterlevel_datetime')
    p.add_argument('--station',type=int);p.add_argument('--manual',action='store_true');p.add_argument('--url-template');p.add_argument('--start');p.add_argument('--end')
    a=p.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    if a.command=='latest':collect(a,out)
    elif a.command=='report':report(out)
    elif a.command=='master':master(out)
    else:history(a,out)

if __name__=='__main__':main()
