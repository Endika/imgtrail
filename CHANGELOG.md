# Changelog

## [0.1.2](https://github.com/Endika/imgtrail/compare/v0.1.1...v0.1.2) (2026-08-27)


### Bug Fixes

* only keep search hits that can actually be verified ([#5](https://github.com/Endika/imgtrail/issues/5)) ([62692bf](https://github.com/Endika/imgtrail/commit/62692bfffb9b9aaf6513ce48ba6a14945d82dbd7))

## [0.1.1](https://github.com/Endika/imgtrail/compare/v0.1.0...v0.1.1) (2026-08-27)


### Documentation

* add badges so the project reads at a glance ([6da6d2a](https://github.com/Endika/imgtrail/commit/6da6d2aed63a054506c212fdcc3f013136ba63ce))

## 0.1.0 (2026-08-27)


### Features

* reverse image search over an Instagram export with pHash verification ([d8111a0](https://github.com/Endika/imgtrail/commit/d8111a0e041bb6aa5efeb329266b3a3ed2241d0e))


### Bug Fixes

* ship the py.typed marker so installers get the type hints ([9d320df](https://github.com/Endika/imgtrail/commit/9d320dfaefd86310d27f54695ead3fc7e8d9279c))


### Documentation

* use the exact GitHub owner in project URLs ([aa96e2d](https://github.com/Endika/imgtrail/commit/aa96e2dab1e3f9484e37e96ea63076e5aed15189))

## 0.1.0

First release.

- Reads photos from an Instagram data export (`.zip`) or any folder of images.
- Collapses near-duplicates by perceptual hash so the same shot is never searched twice.
- Reverse image search through Google Cloud Vision `WEB_DETECTION`.
- Verifies every candidate by downloading it and comparing it against the original.
- Self-contained HTML report, plus JSON output.
