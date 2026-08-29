# imgtrail

[![PyPI](https://img.shields.io/pypi/v/imgtrail)](https://pypi.org/project/imgtrail/)
[![Python](https://img.shields.io/pypi/pyversions/imgtrail)](https://pypi.org/project/imgtrail/)
[![CI](https://github.com/Endika/imgtrail/actions/workflows/ci.yml/badge.svg)](https://github.com/Endika/imgtrail/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/pypi/l/imgtrail)](LICENSE)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-2a6db2)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Find out where else on the web your own photos show up.

Point it at your Instagram data export. It hashes every photo, collapses the near-duplicates
so you never pay to search the same picture twice, runs each unique one through reverse image
search, and then **downloads every candidate and compares it against your original** before
putting it in the report. What you get back is a list you can trust, not a pile of URLs.

```
imgtrail scan ~/Downloads/instagram-export.zip --dry-run
imgtrail scan ~/Downloads/instagram-export.zip
imgtrail report --open
```

## What it finds, and what it doesn't

It finds your photos on **blogs, news sites, forums, marketplaces, scraper mirrors and shops
that lifted your pictures**, and on **public Facebook posts and groups**, which is where a
photograph of somewhere recognisable tends to end up.

It will **not** find a repost on another Instagram account. Instagram serves its images to
nobody — every candidate it offers is a login wall — so a copy there can never be checked
against your original, and an unverifiable claim is not a finding. Telegram, WhatsApp and
private accounts are invisible to it too. If your question is "is someone reposting me inside
Instagram", this is the wrong tool and there isn't a good one.

What it cannot prove, it says so. A candidate the search named and the site would not serve —
TikTok, Facebook's lookaside — is listed apart under **"found, but not verified"**: a place to
go and look, not a claim. Pages named with no image at all are dropped: measured against the
page-level claims that could be checked, 9.6% held.

Your own Facebook page is not filtered out — from a group post there is no telling whose it
is. If you cross-post everything from Instagram, `--ignore-domain facebook.com`.

## Install

```
pip install imgtrail
```

## Getting your photos

Instagram → Settings → Accounts Centre → Your information and permissions → **Download your
information**. Ask for JSON, high quality. You'll get a ZIP; hand it straight to `imgtrail scan`.
No scraping, nothing against the terms of service, no rate limits.

A plain folder of images works just as well.

## Getting an API key

**Vision** is the default and the only one you need. Create a project at
[console.cloud.google.com](https://console.cloud.google.com), enable the **Cloud Vision API**,
then Credentials → Create credentials → API key.

```
export IMGTRAIL_API_KEY=AIza...
```

**Lens** is optional, through [SerpApi](https://serpapi.com/manage-api-key).

```
export SERPAPI_KEY=...
```

| | Vision | Lens |
|---|---|---|
| Free each month | 1,000 searches | 250 searches |
| After that | $3.50 per 1,000 | about $15 per 1,000 |

A typical profile costs nothing on Vision. Lens is four times the price, and the free 250 a
month are enough for the way it earns its keep — see below.

Run `--dry-run` with either and it will tell you exactly how many searches it would make and
what they would cost before spending anything. It prices against what that engine has already
billed *this calendar month*, because that is when the free tier resets.

## Two engines, and when to pay for the second

Reverse image search is not one thing. Cloud Vision's `WEB_DETECTION` and the Google Lens you
get by dragging a photo into the search box are different indexes, and they disagree.

Forty-seven photographs put through both, judged the same way — downloaded and compared
against the original:

| | Vision | Lens |
|---|---|---|
| Verified copies the other engine missed | 0 | **9** |

On those forty-seven Vision found nothing at all. What Lens turned up was on Walmart, Etsy,
two clothing shops and a veterinary practice — places a photograph drifts to that Vision's
index does not reach. Pinterest is the clearest case: it comes back from Lens and never from
Vision, in any field of its answer.

Neither is more accurate. Five of fifty-nine Lens candidates survived verification, which is
Vision's hit rate too. They simply look in different places.

So run Vision over everything, and spend Lens where the cheap engine came back empty:

```
imgtrail scan EXPORT --engine lens --only-blank --limit 200
```

A photo searched by one engine is still new to the other, so that spends two hundred searches
on two hundred uncovered photos, inside the free plan, and `--only-blank` keeps them off the
photos something has already been found on. Results from both land in the same report and are
verified the same way.

## How the verification works

Reverse image search returns a lot of near-misses. For every candidate, imgtrail downloads the
image and compares perceptual hashes against your original:

| Hamming distance | Verdict | Meaning |
|---|---|---|
| ≤ 8 | `confirmed` | The same image, possibly recompressed |
| ≤ 16 | `likely` | Cropped, filtered or heavily edited |
| > 16 | `rejected` | Not your photo |

Only `confirmed` and `likely` reach the report. `visuallySimilarImages` is dropped entirely —
it means "semantically alike", not "this is your photo", and it drowns the report in noise.

A photo with nothing in it is never searched. A blank frame has no fingerprint worth the name:
it sits at distance zero from every other blank frame on the internet, and one of them once
put 118 false `confirmed` in a report.

## Commands

```
imgtrail --data-dir DIR CMD   where the database lives (default ./imgtrail-data)
                              — note it goes before the command, not after

imgtrail scan SOURCE          index, dedupe, search and verify — resumable
  --engine vision|lens        which index to search (default vision)
  --only-blank                only photos nothing has been found on yet
  --dry-run                   count the searches and their cost, call nothing
  --limit N                   search at most N unique photos
  --threshold N               pHash distance for "same photo" (default 6)
  --ignore-domain DOMAIN      exclude a domain from results (repeatable)
  --again                     search everything again, paying for it again
  --no-verify                 skip the download-and-compare pass
  --workers N                 parallel downloads while verifying (default 8)
imgtrail reparse              re-read the stored answers under today's filters
  --ignore-domain DOMAIN      exclude a domain from results (repeatable)
  --no-verify                 skip the download-and-compare pass
  --workers N                 parallel downloads while verifying (default 8)
imgtrail trace PHOTO          everything the engines said about one photo, and its fate
imgtrail report --open        build the HTML report and open it
  --json FILE                 also write the findings as JSON
imgtrail status               what's in the database so far
```

Everything is idempotent: re-running `scan` searches only what it hasn't searched before, so
an interrupted run costs nothing to resume. A scan stays inside the source you point it at —
the database may hold other folders, and they are not what you asked to search.

`trace` answers "why is my photo not in the report" without reading the source: it prints what
each engine said about that one photo and what every filter did with it.

Every answer an engine gives is kept, word for word. Filtering is a pile of judgement calls —
which platforms are yours, which candidates are worth downloading — and at least one of them
is wrong. `reparse` re-reads what you already paid for under today's rules, calling nothing,
so correcting a filter costs nothing. Both of those read the archive, so both are free.

## Privacy

Your photos are sent to whichever engine you run: Google Cloud Vision by default, and SerpApi
as well if you pass `--engine lens`. Both receive the picture itself. Lens photos are uploaded
rather than linked — a tool for finding where your pictures leaked has no business publishing
them to a public URL first — and the upload is temporary.

Nothing goes to any server of mine; there isn't one. The database, the extracted export and
the report all stay on your machine, and no photograph is sent anywhere without a search you
asked for and could have priced first with `--dry-run`.

## Architecture

Ports and adapters, sized to the problem: the rules sit in the middle and know nothing about
Google, SQLite or HTTP.

```
domain.py     fingerprints, grouping, verdicts, what counts as "your own platform"
              — pure; no I/O, no SQL, no network
ports.py      the boundaries: PhotoSource, ImageLoader, SearchEngine, ImageFetcher,
              PhotoRepository, MatchRepository, ResponseArchive, ReportWriter
services.py   the use cases: index, plan, search, verify, reparse, report
adapters/     the details: sqlite_repository, vision, serpapi, http_fetcher,
              local_files, html_report
cli.py        the composition root — the one module that knows every layer
```

Adding a third engine means writing one `SearchEngine` and wiring it in `cli.py`. That is not
a claim, it is what happened: Lens arrived as `adapters/serpapi.py` without a line of
`domain.py` changing.

## Development

```bash
uv sync --all-groups
uv run pytest             # 130 tests, no network, no mocks
uv run ruff check .
uv run ruff format .
uv run mypy               # strict, and it passes on the tests too
```

The test doubles are real implementations, not mocks: an in-memory `DictPhotoSource`, a
`FakeSearchEngine` that records what it was asked, and — where the wire itself is what needs
testing — a real local HTTP server speaking Vision's and SerpApi's JSON.

## Licence

MIT
