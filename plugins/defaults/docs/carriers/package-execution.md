# Package execution through Carriers

Parent: [obst-defaults Carriers](README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

The Defaults plugin supplies `write_package()` and `publish_package()` for
executing any prepared `PackageWriteOperation` through a bound Carrier session.
This page owns their finish, close, commit, abort and cleanup semantics.

## Write a visible stream

`write_package()` opens a `BoundCarrierWriter`, executes the prepared package
operation, calls `finish()` and closes the session. It returns
`WrittenPackage(package, completion)`, where `completion` is the result of
`finish()`. A failure may leave a visible prefix because a streaming writer
has no publication transaction.

The helper attempts to close the session without replacing the primary
failure. A close failure after otherwise successful packaging is reported as
the operation failure.

## Publish transactionally

`publish_package()` opens a `BoundCarrierPublisher`, executes the package
operation and calls `commit()` only after packaging succeeds. A failure during
opening, packaging or commit triggers `abort()`. An abort failure is attached as a note to
the primary exception rather than replacing it.

The generic [Carrier lifecycle](../../../../docs/toolchain/extension-api/carriers.md#writer-and-publisher-semantics)
defines the provider contract. This helper supplies the Defaults orchestration
around that contract.

## Results and cleanup

Successful publication returns the provider's `PublicationReceipt` together
with the completed package result. Cleanup failures that occur after the final
target became visible are reported through `cleanup_issues`; they do not turn
a successful commit into a false failure.
