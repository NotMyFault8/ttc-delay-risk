"""Measure local HTTP latency; results are environment-specific, not an SLA."""
import argparse
import concurrent.futures
import json
import time
import urllib.request

p=argparse.ArgumentParser()
p.add_argument('--url',default='http://127.0.0.1:8000/risk-ranking?date=2025-07-01')
p.add_argument('--requests',type=int,default=200)
p.add_argument('--workers',type=int,default=4)
a=p.parse_args()

def request(_):
    start=time.perf_counter()
    with urllib.request.urlopen(a.url,timeout=10) as r:
        data=json.load(r)
        if not data.get('items'):raise ValueError('Benchmark requires a populated batch')
    return (time.perf_counter()-start)*1000

with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
    durations=sorted(pool.map(request,range(a.requests)))
print(json.dumps({'requests':a.requests,'concurrency':a.workers,'p50_ms':durations[len(durations)//2],
                  'p95_ms':durations[int(len(durations)*.95)-1],'max_ms':max(durations),
                  'scope':'Local Docker PostgreSQL API, 12 synthetic prediction rows; not a production SLA'},indent=2))
