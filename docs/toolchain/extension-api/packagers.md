# Packager extensions

Parent: [Extension system](../extensions.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

A packager turns declared logical sources into one valid OBST container under
a provider-defined policy. Sources may already declare Recipes and chunk
boundaries, or a Packager may derive different declarations. A Packager never
owns the destination.
Packager IDs are local runtime capabilities and never appear in container
bytes.

## Table of contents

- [Packager extensions](#packager-extensions)
	- [Table of contents](#table-of-contents)
	- [Provider contract](#provider-contract)
	- [What a packager owns](#what-a-packager-owns)
	- [What a packager does not own](#what-a-packager-does-not-own)
	- [Concrete packagers](#concrete-packagers)
	- [Third-party policies](#third-party-policies)

## Provider contract

One self-describing Extension with `ExtensionKind.PACKAGER` implements
`PackagerProvider[Request]`:

```python
from obst.core import PackageWriteOperation, PackagerProvider

operation = provider.prepare_package(request)
```

The request is provider-owned and typed. The returned
`PackageWriteOperation.write_to()` accepts only a `BinaryWriter` and returns a
carrier-neutral `PackageResult`. Registry lookup proves that the selected ID
has a callable packager provider; invoking the provider remains the caller's
trusted-code boundary.

## What a packager owns

- how source declarations become the final manifest;
- how stream and recipe IDs are assigned;
- whether supplied recipe and chunk choices are preserved or replaced;
- encoder preflight and manifest construction policy;
- fixed, tuned, incremental or repacking strategy; and
- the resource policy passed through the operation.

The [core packaging contracts](../internals/packaging.md) define logical sources,
prepared operations and results without selecting any one policy.

## What a packager does not own

A packager does not choose a path, object key, network connection or
publication transaction. The caller separately selects a
[carrier](carriers.md), opens its writer or publisher, then executes the
prepared operation against that binary endpoint.

Packager identity is not needed for decoding. The produced manifest records
only the stream-type and stage contracts needed to understand and recover its
logical bytes.

## Concrete packagers

The separately installable `obst-defaults` plugin documents its
[`obst.fixed@1` policy](../../../plugins/defaults/docs/packagers/fixed.md). It
enters the registry through the same provider path as every other Packager.

## Third-party policies

A tuner may benchmark several recipes. A repackager may preserve logical bytes
while changing their representation. An incremental packager may reuse prior
work. These policies can implement the same provider boundary without changing
the OBST wire format or teaching a carrier how packaging works.

Unimplemented production policies remain [roadmap](../../../ROADMAP.md) work; the
extension point does not imply that the reference implementation already ships
them.
