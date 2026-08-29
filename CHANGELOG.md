# Changelog

## [0.5.2](https://github.com/Endika/imgtrail/compare/v0.5.1...v0.5.2) (2026-08-29)


### Bug Fixes

* accept --data-dir on either side of the command ([ce1e3c2](https://github.com/Endika/imgtrail/commit/ce1e3c2ab9c2ddf04e4eae41a92b191cc40dc558))

## [0.5.1](https://github.com/Endika/imgtrail/compare/v0.5.0...v0.5.1) (2026-08-29)


### Documentation

* bring the readme up to what the tool now does ([26e56e1](https://github.com/Endika/imgtrail/commit/26e56e13709e63a0ebf1f9fa9013c1f8e7f5838c))
* rewrite the readme so it reads in order and says each thing once ([7839e89](https://github.com/Endika/imgtrail/commit/7839e8988c20b13fe2b8a92a454d3b739416788c))

## [0.5.0](https://github.com/Endika/imgtrail/compare/v0.4.1...v0.5.0) (2026-08-29)


### Features

* spend the expensive engine only where the cheap one came back empty ([5b85ca2](https://github.com/Endika/imgtrail/commit/5b85ca2da0b1a8e2ac17072318a107bcdc473af8))

## [0.4.1](https://github.com/Endika/imgtrail/compare/v0.4.0...v0.4.1) (2026-08-29)


### Bug Fixes

* never let one unrequestable url end a verification run ([a1cdc53](https://github.com/Endika/imgtrail/commit/a1cdc539b37a7e3eb1095b013a0871f2b48af6fe))

## [0.4.0](https://github.com/Endika/imgtrail/compare/v0.3.0...v0.4.0) (2026-08-29)


### Features

* search Google Lens as a second engine, since one index is not the web ([0d67318](https://github.com/Endika/imgtrail/commit/0d673181b0d05145302e8e05a2f95fd8d7ae15af))

## [0.3.0](https://github.com/Endika/imgtrail/compare/v0.2.0...v0.3.0) (2026-08-29)


### Features

* fold the report so it opens as an index, not a scroll ([6231a58](https://github.com/Endika/imgtrail/commit/6231a588049a989b9a914f18645dcd24afbf071e))

## [0.2.0](https://github.com/Endika/imgtrail/compare/v0.1.2...v0.2.0) (2026-08-29)


### Features

* account for every picture the source passed over ([4db7730](https://github.com/Endika/imgtrail/commit/4db773035bbf928eea53f3195953146d996915c5))
* add --again to scan, and price a run by what this month has cost ([38ad61b](https://github.com/Endika/imgtrail/commit/38ad61b10fdb78d32d74a53c25727acccbe36d92))
* add trace, so the report can be asked why ([4136c3b](https://github.com/Endika/imgtrail/commit/4136c3b57ff57f021f80ba80f2a739fe93894459))
* keep every search answer so correcting a filter costs nothing ([ec2518d](https://github.com/Endika/imgtrail/commit/ec2518d697ba6d78c968f67042fdeb5ecda1ee8e))
* report the candidates the web refused to hand over ([2aeab31](https://github.com/Endika/imgtrail/commit/2aeab310dd8eaa3eebb3d25be045bafe649e7865))


### Bug Fixes

* keep a scan inside the folder it was pointed at ([de6faa3](https://github.com/Endika/imgtrail/commit/de6faa3cf39dc3fb32db24004a78279aa61981e1))
* keep flat frames out of the search and out of the report ([c7b9f9b](https://github.com/Endika/imgtrail/commit/c7b9f9bbcf1d6de8019f90c5a87065a945a4d234))
* recover the candidates dropped before they could be verified ([37a59b2](https://github.com/Endika/imgtrail/commit/37a59b275295c64c03668d838a67557ea6c74f24))
* stop dropping photos the source should have handed over ([bb9b0d5](https://github.com/Endika/imgtrail/commit/bb9b0d517ac31a688e1ec88c9893ab818d9529ec))
* treat a Facebook repost as the finding it is ([c506a02](https://github.com/Endika/imgtrail/commit/c506a0221bad099304e2e92799e0e0b90afc468b))

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
