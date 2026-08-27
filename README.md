# imgtrail

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

It searches Google's index, so it finds your photos on **blogs, news sites, Pinterest, Tumblr,
forums, scraper mirrors and shops that lifted your pictures**.

It will **not** find a repost on another Instagram account. Instagram blocks crawling of post
images, so they aren't in anyone's index — the only way such a repost surfaces here is
indirectly, via one of the many "Instagram viewer" mirror sites that *are* indexed. Telegram,
WhatsApp, TikTok, Facebook and private accounts are invisible to it too. If your question is
"is someone reposting me inside Instagram", this is the wrong tool and there isn't a good one.

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

imgtrail uses Google Cloud Vision's `WEB_DETECTION`. Create a project at
[console.cloud.google.com](https://console.cloud.google.com), enable the **Cloud Vision API**,
then Credentials → Create credentials → API key.

```
export IMGTRAIL_API_KEY=AIza...
```

**The first 1,000 images each month are free**, then $3.50 per 1,000. A typical profile costs
nothing. Run `--dry-run` first and it will tell you exactly how many searches it would make and
what they would cost before spending anything.

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
  --dry-run                   count the searches and their cost, call nothing
  --limit N                   search at most N unique photos
  --threshold N               pHash distance for "same photo" (default 6)
  --ignore-domain DOMAIN      exclude a domain from results (repeatable)
  --no-verify                 skip the download-and-compare pass
imgtrail report --open        build the HTML report and open it
imgtrail status               what's in the database so far
```

State lives in `./imgtrail-data`. Everything is idempotent: re-running `scan` searches only
what it hasn't searched before, so an interrupted run costs nothing to resume.

## Privacy

Your photos are sent to Google Cloud Vision, and nowhere else. Nothing is uploaded to any
server of mine — there isn't one. The database, the extracted export and the report all stay
on your machine.

## Licence

MIT
