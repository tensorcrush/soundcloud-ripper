# soundcloud-ripper v2

[![Python](https://img.shields.io/badge/Python-3.10+-yellow)]()

Bruteforce random SoundCloud shortlinks (`on.soundcloud.com/XXXXX`) to surface private tracks.

**How it works:** SoundCloud shortlinks redirect (302) to the real track URL. Private tracks carry a secret token (`/s-XXXXXXXXXXX`) in that URL — public ones don't. This tool fires hundreds of random probes per second and catches those tokens.

---

> Educational purposes only. Use at your own risk.

---

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
# default — 200 concurrent workers
python ripper.py

# crank it up
python ripper.py -c 500

# show public tracks too
python ripper.py -c 300 -v

# show everything (public + misses)
python ripper.py -c 300 -vv
```

Results are saved live to `output.json` as private tracks are found.

## Options

| Flag | Description |
|------|-------------|
| `-c N` | Concurrent requests (default: 200) |
| `-v` | Show public tracks as they're hit |
| `-vv` | Show all misses too |
