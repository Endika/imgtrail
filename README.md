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

## Two engines, because one index is not the web

Reverse image search is not one thing. Cloud Vision's `WEB_DETECTION` and the Google Lens you
get by dragging a photo into the search box are different indexes, and they disagree.

Forty-seven photographs put through both, and judged the same way — downloaded and compared
against the original:

| | Vision | Lens |
|---|---|---|
| Verified copies the other engine missed | 0 | **9** |
| Cost | $3.50 / 1,000, first 1,000 free monthly | ~$15 / 1,000, first 250 free monthly |

On those forty-seven Vision found nothing at all. What Lens turned up was on Walmart, Etsy,
two clothing shops, a veterinary practice — places a photograph drifts to that Vision's index
does not reach.

One photograph tells the same story from the other side. A drone shot of a castle: Vision
found it on nine Facebook pages and never mentioned Pinterest in any field of its answer;
Lens found three Pinterest boards, and a Facebook group Vision had missed.

Neither is more accurate — five of fifty-nine Lens candidates survived verification, which is
Vision's hit rate too. They simply look in different places, so both are here:

```
imgtrail scan EXPORT                    # vision: cheap and wide, the default
imgtrail scan EXPORT --engine lens      # lens: a different index, for the photos you care about
```

A photo already searched by one engine is still new to the other, so `--engine lens --limit 20`
spends twenty searches on the twenty you have not covered yet. Results from both land in the
same report and are verified the same way.

Lens costs four times what Vision does, so spend it where the cheap engine came back empty:

```
imgtrail scan EXPORT --engine lens --only-blank --limit 200
```

Two hundred a month fits inside the free plan, and `--only-blank` keeps them off the photos
something has already been found on.

## What it finds, and what it doesn't

It finds your photos on **blogs, news sites, forums, marketplaces, scraper mirrors and shops
that lifted your pictures**, and on **public Facebook posts and groups**, which is where a
photograph of somewhere recognisable tends to end up. **Pinterest** comes back from Lens and
never from Vision, which is most of the argument for running both.

It will **not** find a repost on another Instagram account. Instagram blocks crawling of post
images, so they aren't in anyone's index — the only way such a repost surfaces here is
indirectly, via one of the many "Instagram viewer" mirror sites that *are* indexed. Telegram,
WhatsApp, TikTok and private accounts are invisible to it too. If your question is "is someone
reposting me inside Instagram", this is the wrong tool and there isn't a good one.

What it cannot prove, it says so. A candidate the search named and the site would not serve
— TikTok, Facebook's lookaside — is listed apart under **"found, but not verified"**: a place
to go and look, not a claim. Pages named with no image at all are not kept: of the page-level
claims that could be checked against the original, 9.6% held.

Your own Facebook page is not filtered out: from a group post there is no telling whose it is.
If you cross-post everything from Instagram, `--ignore-domain facebook.com`.

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

**Vision**, the default. Create a project at
[console.cloud.google.com](https://console.cloud.google.com), enable the **Cloud Vision API**,
then Credentials → Create credentials → API key.

```
export IMGTRAIL_API_KEY=AIza...
```

**The first 1,000 images each month are free**, then $3.50 per 1,000. A typical profile costs
nothing.

**Lens**, optional, through [SerpApi](https://serpapi.com/manage-api-key).

```
export SERPAPI_KEY=...
```

250 searches a month on the free plan, which is enough for the way it is meant to be used:
a second opinion on the photos you care about, not a second pass over everything. Beyond that
it is a subscription, around $15 per 1,000 — four times Vision. Your photos are uploaded, never
published to a URL.

Run `--dry-run` first with either one and it will tell you exactly how many searches it would
make and what they would cost before spending anything.

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

## Commands

```
imgtrail scan SOURCE          index, dedupe, search and verify — resumable
  --engine vision|lens        which index to search (default vision)
  --only-blank                only photos nothing has been found on yet
  --dry-run                   count the searches and their cost, call nothing
  --limit N                   search at most N unique photos
  --threshold N               pHash distance for "same photo" (default 6)
  --ignore-domain DOMAIN      exclude a domain from results (repeatable)
  --again                     search everything again, paying for it again
  --no-verify                 skip the download-and-compare pass
imgtrail reparse              re-read the stored answers under today's filters
  --ignore-domain DOMAIN      exclude a domain from results (repeatable)
imgtrail trace PHOTO          everything the engine said about one photo, and its fate
imgtrail report --open        build the HTML report and open it
imgtrail status               what's in the database so far
```

State lives in `./imgtrail-data`. Everything is idempotent: re-running `scan` searches only
what it hasn't searched before, so an interrupted run costs nothing to resume. A scan stays
inside the source you point it at — the database may hold other folders, and they are not
what you asked to search.

`trace` answers "why is my photo not in the report" without reading the source: it prints
what the engine said about that one photo and what each filter did with it. It reads the
archive, so it costs nothing.

Every answer a search engine gives is kept verbatim. Filtering is a pile of judgement calls —
which platforms are yours, which candidates are worth downloading — and at least one of them
is wrong. `reparse` re-reads what you already paid for under the current rules, without
calling anything, so correcting a filter costs nothing.

## Privacy

Your photos are sent to whichever engine you run: Google Cloud Vision by default, and SerpApi
as well if you pass `--engine lens`. Both receive the picture itself. Lens photos are uploaded
rather than linked — a tool for finding where your pictures leaked has no business publishing
them to a public URL first — and the upload is temporary.

Nothing is uploaded to any server of mine; there isn't one. The database, the extracted export
and the report all stay on your machine, and no photograph is ever sent anywhere without a
search you asked for and priced first with `--dry-run`.

## Architecture

Ports and adapters, sized to the problem: the rules sit in the middle and know nothing
about Google, SQLite or HTTP, so swapping a search backend touches exactly one file.

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
