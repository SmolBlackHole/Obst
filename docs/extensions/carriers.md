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
	- [Concrete carriers](#concrete-carriers)
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

A host composes a prepared package operation with one of these sessions. A
streaming writer may leave a visible prefix after failure. A transactional
publisher commits only after the package operation succeeds and otherwise
aborts. Concrete orchestration helpers, result values and failure types belong
to the distribution that supplies them.

Returning successfully from `commit()` means publication is already complete.
A provider must not report a commit failure after making the complete target
visible.

### Negative lifecycle cases

| Failure point                             | Required result                                                            |
| ----------------------------------------- | -------------------------------------------------------------------------- |
| reader `open()` fails                     | no container operation starts; carrier failure remains primary             |
| writer fails after exposing bytes         | partial output may remain; close is attempted                              |
| packaging fails through a publisher       | no commit; abort is attempted                                              |
| publisher `commit()` fails before publish | commit failure remains primary; abort failure becomes an exception note    |
| cleanup fails after publication           | provider reports successful publication plus its owned cleanup result      |
| invalid transition after termination      | provider-owned state failure; documented idempotent cleanup may still work |

## Typed requests

Requests belong to their Carrier because unrelated transports do not share one
honest option dictionary. An object store may require a bucket and key, a
database may require a connection and row identity, and a stream may require a
host-owned endpoint.

The composition root may know the selected carrier ID and request type. It
resolves the provider from `ExtensionRegistry` and never constructs a concrete
session implementation directly.

Passing the wrong request type is a carrier contract failure. There is no
generic `**kwargs` fallback and no filename-shaped universal URI pretending to
model memory, databases and sockets equally well.

## Concrete carriers

The separately installable `obst-defaults` plugin documents its
[filesystem, memory and standard-input Carriers](../../plugins/defaults/docs/carriers/README.md).
Those pages own adapter-specific requests, orchestration helpers, guarantees
and limitations. This page owns only the provider and session contracts shared
by every Carrier.

## Third-party carriers

A database carrier may return a row key. An object-store carrier may return an
object version. A socket carrier may expose bytes progressively and therefore
offer a writer rather than pretending it can roll them back.

Credentials, transactions, keys, retries, durability and cleanup belong to
the adapter. The core sees only a bounded `BinaryReader` or `BinaryWriter`.
Range reads and selective remote extraction remain separate
[roadmap](../../ROADMAP.md#later-directions) concerns because they
need indexing and resource policy, not a larger blocking stream interface.
