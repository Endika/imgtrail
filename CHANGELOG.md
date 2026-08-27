# Changelog

## 0.1.0

First release.

- Reads photos from an Instagram data export (`.zip`) or any folder of images.
- Collapses near-duplicates by perceptual hash so the same shot is never searched twice.
- Reverse image search through Google Cloud Vision `WEB_DETECTION`.
- Verifies every candidate by downloading it and comparing it against the original.
- Self-contained HTML report, plus JSON output.
