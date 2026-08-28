# Carriers

Parent: [Extension system](README.md)

A carrier moves an existing or newly produced OBST byte stream through a
host-selected endpoint. It does not own manifests, recipes, logical streams or
application meaning. Carrier identities exist only in the local extension
registry and never enter container bytes.

## Table of contents

- [Carriers](#carriers)
	- [Table of contents](#table-of-contents)
	- [Extension and session contracts](#extension-and-session-contracts)
	- [Reader lifecycle](#reader-lifecycle)
	- [Writer and publisher semantics](#writer-and-publisher-semantics)
		- [Negative lifecycle cases](#negative-lifecycle-cases)
	- [Typed requests](#typed-requests)
	- [First-party carriers](#first-party-carriers)
	- [Third-party carriers](#third-party-carriers)

## Extension and session contracts

One carrier extension describes itself and implements any compatible subset of
the provider protocols:

```python
from obst.core import (
    CarrierPublisherProvider,
    CarrierReaderProvider,
    CarrierWriterProvider,
)
```

- `bind_reader(request)` returns a `BoundCarrierReader`.
- `bind_writer(request)` returns a `BoundCarrierWriter` for progressively
  visible output.
- `bind_publisher(request)` returns a `BoundCarrierPublisher` with commit and
  abort semantics.

The registry derives those capabilities from callable methods. An extension
does not repeat them as booleans. For one carrier ID, at most one provider may
own each capability; complementary reader, writer and publisher objects may
share the ID only when kind and descriptor agree.

The host selects an already activated carrier by ID. A manifest cannot select
a carrier, install a plugin or expand the operation's trust set.

## Reader lifecycle

```python
reader_session = provider.bind_reader(request)
source = reader_session.open()
try:
    inspection = inspect_container(source)
finally:
    reader_session.close()
```

`open()` returns the minimal blocking `BinaryReader` understood by the core.
`close()` releases carrier-owned state. A carrier may deliberately leave a
host-owned endpoint open, as the standard-input adapter does, but its bound
session still reaches a terminal state.

## Writer and publisher semantics

A writer and a publisher tell different truths:

```text
writer:     open -> incremental visibility -> finish -> close
publisher:  open -> unpublished bytes -> commit or abort
```

The first-party orchestration helpers are imported from the separately
installable defaults package:

```python
from obst_defaults.carriers import publish_package, write_package
```

`write_package(operation, writer)` may leave a visible prefix if writing
fails. It attempts to close the session and preserves the primary failure.

`publish_package(operation, publisher)` reports success only after `commit()`.
If opening, packaging, writing or committing fails, it attempts `abort()` and
adds an abort failure as an exception note without replacing the primary
error.

Returning successfully from `commit()` means publication is already complete.
Cleanup that fails after publication belongs in
`PublicationReceipt.cleanup_issues`; it must not turn a visible complete
target into a false commit failure.

### Negative lifecycle cases

| Failure point                                       | Required result                                                           |
| --------------------------------------------------- | ------------------------------------------------------------------------- |
| reader `open()` fails                               | no container operation starts; carrier failure remains primary            |
| writer fails after exposing bytes                   | partial output may remain; close is attempted                             |
| packaging fails through a publisher                 | no commit; abort is attempted                                             |
| publisher `commit()` fails before publish           | commit failure remains primary; abort failure becomes an exception note   |
| cleanup fails after publication                     | successful receipt with `cleanup_issues`                                  |
| invalid non-idempotent transition after termination | `CarrierStateError`; `close()` and pre-commit `abort()` may be idempotent |

This publisher is invalid:

```python
def commit(self) -> PublicationReceipt[str]:
    publish_complete_target()
    remove_temporary_state()  # raises after the target became visible
    return PublicationReceipt("target", ())
```

It can report failure after publication succeeded. A correct publisher enters
committed state when the complete target becomes visible and reports later
cleanup failures in the receipt.

## Typed requests

Requests belong to their carrier because unrelated transports do not share one
honest option dictionary:

```python
FilesystemReadRequest(path)
FilesystemPublishRequest(path, overwrite=False)
MemoryReadRequest(data)
MemoryPublishRequest()
StdinReadRequest(source)
```

The composition root may know the selected carrier ID and request type. It
resolves the provider from `ExtensionRegistry` and never constructs a concrete
session implementation directly.

Passing the wrong request type is a carrier contract failure. There is no
generic `**kwargs` fallback and no filename-shaped universal URI pretending to
model memory, databases and sockets equally well.

## First-party carriers

The `obst-defaults` distribution supplies these carriers through its ordinary
`obst.extensions` plugin contribution. They enter a runtime only when the host
explicitly activates or directly composes that plugin's objects.

| ID                  | Capabilities  | Endpoint                 | Detailed page                                |
| ------------------- | ------------- | ------------------------ | -------------------------------------------- |
| `obst.filesystem@1` | read, publish | Caller-selected path     | [Filesystem](carriers/filesystem.md)         |
| `obst.memory@1`     | read, publish | Immutable Python `bytes` | [Memory](carriers/memory.md)                 |
| `obst.stdin@1`      | read          | Host-owned binary input  | [Standard input](carriers/standard-input.md) |

Those pages own adapter-specific requests, guarantees and limitations. This
page owns the provider and session contracts shared by every carrier.

## Third-party carriers

A database carrier may return a row key. An object-store carrier may return an
object version. A socket carrier may expose bytes progressively and therefore
offer a writer rather than pretending it can roll them back.

Credentials, transactions, keys, retries, durability and cleanup belong to
the adapter. The core sees only a bounded `BinaryReader` or `BinaryWriter`.
Range reads and selective remote extraction remain separate
[roadmap](../../ROADMAP.md#later-directions) concerns because they
need indexing and resource policy, not a larger blocking stream interface.
