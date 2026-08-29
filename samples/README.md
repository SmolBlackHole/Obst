# OBST samples

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

This directory contains three inspectable OBST image containers, one nested
archive and the JPEG files from which they were built.

| Container         | Decoded source                                     | Recipe                 |
| ----------------- | -------------------------------------------------- | ---------------------- |
| `apple.obst`      | `images/an_vision-gDPaDDy6_WE-unsplash.jpg`        | `obst.zlib@1`, level 9 |
| `pineapple.obst`  | `images/fernando-andrade-nAOZCYcLND8-unsplash.jpg` | `obst.zlib@1`, level 9 |
| `fruit-bowl.obst` | `images/jo-sonn-zeFy-oCUhV8-unsplash.jpg`          | `obst.zlib@1`, level 9 |

`all-fruit.obst` stores those three `.obst` containers as ordinary
`obst.file@1` members. Decoding it reproduces each inner container byte for
byte; recursion remains explicit.

Each image container holds one `obst.file@1` stream split into 64 KiB logical
chunks. The stream metadata preserves the source basename, and decoding stream
`0` reproduces the corresponding JPEG byte for byte. For example:

```bash
obst unpack apple.obst -o restored
```

This creates `restored/an_vision-gDPaDDy6_WE-unsplash.jpg`.

[`manifest.json`](manifest.json) records the original Unsplash page, creator,
file size and SHA-256 digest for every image. It also records the generated
container digest and chunk count where a sample container exists. The source
images remain subject to the [Unsplash License](https://unsplash.com/license);
that does not select a license for the OBST project itself.

Rebuild the containers and manifest from the repository root after installing
the package:

```bash
python plugins/defaults/scripts/build_samples.py
```

The rebuild must recover the same logical files, but its encoded container bytes
need not match the checked-in samples. The `obst.zlib@1` contract permits
different conforming zlib backends to produce different representations. Exact
portable format vectors live in the packaged
[`obst.conformance` corpus](../src/obst/conformance/corpus/).
