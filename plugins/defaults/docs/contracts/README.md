# obst-defaults contracts

Parent: [obst-defaults documentation](../README.md)

These are the normative, language-neutral contracts for wire-visible
Extensions implemented by `obst-defaults`. They define how another
implementation recovers logical bytes and interprets metadata or parameters;
they do not require use of the Python providers shipped here.

## Stage contracts

See the [Stage contract index](stages/README.md) for RAW, Delta8 and both zlib
contracts.

## Stream contracts

See the [stream contract index](streams/README.md) for the portable file
profile.

## Related documentation

The OBST runtime owns the generic [Stage](../../../../docs/extensions/stages.md)
and [stream-profile](../../../../docs/extensions/profiles.md) protocols. The
[format specification](../../../../docs/format.md) defines how Extension IDs
and specification URLs enter a container.
