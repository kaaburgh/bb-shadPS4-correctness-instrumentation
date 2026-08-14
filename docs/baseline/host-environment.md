# Host and run environment manifest

The host manifest records the bounded environment facts needed to decide whether
two correctness or performance observations are comparable. It is metadata, not
evidence that Bloodborne or shadPS4 ran successfully.

The machine-readable contract is
[`schemas/host-environment.schema.json`](../../schemas/host-environment.schema.json).
The current identity is `bb-host-environment/v1`; consumers must reject unknown
schema identities or versions instead of guessing a compatibility mapping.

## Collect a manifest

The collector uses only the Python standard library:

```text
python tools/collect_host_environment.py \
  --backend vulkan \
  --emulator-config /path/to/config.toml \
  --output artifacts/host-environment.json
```

`--backend` is an explicit semantic label. The collector deliberately does not
infer the active graphics backend from a UI setting or process state.

`--emulator-config` fingerprints the exact file bytes with SHA-256. The output
contains neither the path nor the file contents. Omit either input when it is not
known: the corresponding value is `null` and its JSON Pointer appears in
`unknown_fields`. Writing to a file is atomic; without `--output`, JSON is written
to standard output. Fingerprinting fails closed if the input is not a regular
file, exceeds 16 MiB, or changes while it is being read.

## Field boundary

The v1 manifest contains:

- collector identity and an RFC 3339 UTC capture time;
- OS family, product name, version/build, and kernel release;
- CPU architecture, vendor/model, and logical processor count;
- total physical memory in bytes;
- a deterministically sorted, bounded list of GPU names, PCI vendor/device IDs,
  and driver name/version where the platform exposes them;
- the explicitly supplied graphics backend;
- a SHA-256 fingerprint of the exact emulator configuration file.

The configuration digest is an identity token, not a semantic description. Two
different digests establish that the inputs differ; matching digests establish
only byte identity. A future consumer that needs named shadPS4 settings must add
an allowlisted, versioned semantic extractor rather than serializing the full
configuration.

GPU discovery is best effort and bounded to 16 records. If a platform exposes
more than 16 candidate controllers, the collector refuses to identify an
arbitrary subset: `host.gpus` is empty, `/host/gpus` is unknown, and the bounded
warning `gpu-inventory-too-many` is emitted. Windows queries the allowlisted
`Name` and `Manufacturer` properties from `Win32_Processor`, plus `Name`,
`DriverVersion`, and `PNPDeviceID` from `Win32_VideoController`; Linux reads PCI
IDs and driver module names from sysfs; macOS reads the allowlisted
display-controller fields from `system_profiler`. Some platforms intentionally
report a driver field as unknown when there is no separate, reliably exposed
version.

## Unknowns and collection failures

Every nullable field is always present. A value that was not supplied, was not
exposed by the platform, or could not be collected is `null`; `unknown_fields`
contains the corresponding JSON Pointer. If no GPU can be identified, the array
is empty and `/host/gpus` is unknown. `collection_warnings` contains bounded
machine-readable codes and field pointers, never raw command output or exception
text.

This makes partial manifests usable without confusing missing data with an empty
or default value. A manifest with unknown fields can identify a run, but it may be
insufficient for a comparison that depends on those fields.

## Privacy and redaction contract

Collection is allowlist-based. The manifest never intentionally records:

- host name, user/account name, home directory, or source/configuration paths;
- command lines, arbitrary environment variables, configuration contents, or
  process lists;
- IP/MAC addresses or other network state;
- hardware serial numbers, GPU UUIDs, monitor identity, or OS installation IDs;
- raw PowerShell, sysfs, `system_profiler`, stderr, or exception output.

The backend input is restricted to a 1–64 character semantic token. The config
fingerprint permits equality correlation between manifests, so manifests should
still be handled as project metadata rather than published automatically. Never
pass a secrets file merely to identify an emulator configuration.

## Stability and comparison

Object keys, GPU ordering, architecture aliases, hexadecimal PCI IDs, backend
case, unknown pointers, and warning order are normalized. The capture timestamp
is expected to differ between runs. Consumers should compare material fields,
not JSON bytes, and should keep the exact manifest alongside or referenced by a
detached run record.

The collector does not record the shadPS4 source/build identity or the Bloodborne
target identity; those are separate baseline contracts. It also does not prove
that a backend was active, that the emulator used the supplied configuration, or
that target behavior was observed.

## Validation

Run the synthetic contract, normalization, privacy, fingerprint, and parser tests:

```text
python -m unittest discover -s tests -v
```

Run the real collector as a host-capability smoke test:

```text
python tools/collect_host_environment.py --backend synthetic-smoke --output host-environment.json
```

Synthetic tests establish producer behavior and privacy boundaries. A smoke test
establishes only that collection completed on that host; neither is Bloodborne
target-runtime evidence.
