# Part A prerequisite #1: stateful POSIX pause/resume protocol

Date: 2026-09-13
Status: implementation and bounded-verification checkpoint; fresh parent review required
Scope: replace the POSIX `SIGSLEEP`/`SIGVTALRM` edge protocol with an
authoritative pause state plus acknowledgement. This note does not change or
evaluate detached-native pthread lifetime, native join ownership, alternate
signal-stack exit/free behavior, TextureCache/Part B, the Bloodborne FSM, or
loading.

## Provenance and boundary

The source input is the clean rejected negative-history commit
`c9f173edc952231f2a40d990288918ea7f516411` in
`/media/ubuntu/UsbSSD447G/shadps4/shadPS4-source`. The project input is
`f3bec19a96ed71f4c983a4d8bd2158e2d61548c3` in
`/home/ubuntu/bb-shadPS4-correctness-instrumentation`; its unrelated untracked
evidence and schema artifacts are preserved.

Authoritative preceding context:

* [`bb-a5-native-detached-audit-20260913.md`](bb-a5-native-detached-audit-20260913.md)
  records the rejected detached-native audit and the Sol finding that the
  standard `SIGSLEEP` protocol can strand a target after Pause/Resume
  coalescing.
* [`bloodborne-overnight-stage-ledger.md`](../notes/bloodborne-overnight-stage-ledger.md)
  records the same blocker and keeps the separate active-`SA_ONSTACK` exit
  blocker open.

The established source build directories are
`/media/ubuntu/UsbSSD447G/shadps4/shadPS4-build` and
`/media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build`. No Bloodborne process
is part of this prerequisite.

## Existing POSIX state machine

At c9f, `DebugStateImpl` has one atomic logical bit,
`is_guest_threads_paused`, plus a `guest_threads_mutex`-protected vector of
raw native `pthread_t` values (`src/core/debug_state.h:140-143`). The current
control transitions are:

```text
Running --PauseGuestThreads--> Paused
Paused  --ResumeGuestThreads-> Running
```

`PauseGuestThreads` takes `guest_threads_mutex`, returns immediately when the
bit is already true, sends `SIGSLEEP` to each non-self ID, records pause time,
then stores the bit true. A self target is signalled after the mutex is
released. `ResumeGuestThreads` takes the same mutex, returns when the bit is
false, sends the same `SIGSLEEP` to every listed ID, updates guest pause-time
accounting, and stores the bit false (`src/core/debug_state.cpp:31-102`).

On POSIX, `SIGSLEEP` is an alias for standard `SIGVTALRM`
(`src/core/signals.h:11-15`). The installed `SA_SIGINFO | SA_ONSTACK` handler
does not inspect `DebugState`; its `SIGSLEEP` arm unconditionally calls
`sigwait` for another `SIGSLEEP` (`src/core/signals.cpp:294-301`). Thus the
first signal is treated as “enter a sleep edge” and the second as “leave it”.
The signal is standard, so repeated pending instances are not a reliable
counter.

Registration starts in `RunThread` after `g_curthread` and the native cleanup
key are set, where `DebugState.AddCurrentThreadToGuestList()` stores the raw
ID (`src/core/libraries/kernel/threads/pthread.cpp:545-560`). Normal return
removes the ID before `posix_pthread_exit`; the native cleanup callback also
removes the current ID for direct guest exit
(`pthread.cpp:91-123`, `pthread.cpp:596-598`). The signal handler has no
registration or exit-state acknowledgement, so list removal does not quiesce
an already accepted signal.

Cancellation remains separate: POSIX uses `SIGRTMAX` (or `SIGUSR2` on Apple
and FreeBSD), while Windows uses `NtQueueApcThreadEx`; the cancellation
handler and APC path are not part of this replacement
(`pthread.cpp:1002-1055`).

## Concrete old lost-resume/coalescing interleaving

The following is a bounded, scheduler-independent ordering; no timing sleep
is needed.

1. Target is running and is present in `guest_threads`.
2. Controller executes `PauseGuestThreads`. It sends standard `SIGVTALRM` and
   returns from `pthread_kill`; delivery/handler entry is deliberately held
   back. The target has one pending standard signal, and no pause acknowledgement
   exists.
3. Before the target enters `SignalHandler`, controller executes
   `ResumeGuestThreads`. It sends the same standard `SIGVTALRM`, but the first
   pending standard signal already represents that signal number, so the
   second edge need not create a second pending instance. The logical bit is
   now false.
4. The target finally enters the `SIGSLEEP` handler. The handler does not read
   the false logical bit; it calls `sigwait(SIGVTALRM)` and consumes the one
   coalesced notification as if it were the Resume edge.
5. The handler waits forever for another `SIGVTALRM`. The controller already
   observed Resume and will not send another signal while the logical bit is
   false. If the target exits/removes itself before delayed handler entry, the
   ID may no longer be available for a recovery Resume, making the same edge
   unresumable across removal.

The failure is not repaired by adding another signal at the sender: the signal
is only an edge and neither sender nor handler records which logical state was
requested. A deterministic test must model one pending standard notification
slot and use barriers to place handler entry after both transitions; a watchdog
must report the old strand instead of hanging the test process.

## Smallest replacement protocol

The POSIX implementation will add a `PauseProtocol` with one atomic packed
word:

```text
packed = (epoch << 1) | paused
```

The epoch increases only when the logical state changes. Pause/Pause and
Resume/Resume return the current epoch without a new transition. Pause ->
Resume -> Pause produces three monotonically ordered states when the initial
state is Running: `(1, Paused)`, `(2, Running)`, `(3, Paused)`.

Each registered POSIX guest thread has a participant record containing:

* a pointer to the shared authoritative protocol;
* an atomic `registered` flag;
* an atomic highest acknowledged epoch; and
* a POSIX semaphore used only as a controller-side wait wake. The handler
  publishes the acknowledgement before `sem_post`; `sem_post` is the
  POSIX-specified async-signal-safe operation used from the handler.

The transition and handler rules are:

1. Under `guest_threads_mutex`, `PauseGuestThreads` publishes the Paused
   state with release ordering before sending any notification. It sends at
   most the existing one notification per listed target, then releases the
   list lock and waits for every non-self target’s acknowledgement of at least
   that epoch. A target that unregisters satisfies the wait as a terminal
   outcome. Self pause keeps the existing “signal after releasing the list
   lock” behavior and cannot synchronously wait beneath its own handler.
2. `ResumeGuestThreads` publishes Running with release ordering before sending
   notifications. It does not depend on a signal count or wait for a second
   edge.
3. On every POSIX pause notification, the handler loads the packed state with
   acquire ordering, acknowledges the observed epoch, and then acts on that
   same snapshot. If the snapshot is Running, it returns. If it is Paused, it
   waits for another `SIGVTALRM` only as a wake, then loops and rereads the
   authoritative state. A coalesced Resume notification therefore still
   causes the next read to observe Running; a coalesced Pause notification
   still causes the final Paused epoch to be acknowledged and waited on.
4. Registration is published before the ID is inserted in the debug list.
   Removal first publishes `registered = false`, then blocks `SIGVTALRM` on
   that exiting POSIX thread, then erases the list entry. This makes a pending
   pause notification harmless: a handler that starts before invalidation can
   finish its state protocol, while a handler that starts after invalidation
   returns without dereferencing a removed registration. The participant
   remains owned by its thread or an in-flight controller snapshot until no
   handler/waiter can use it.

### Exact invariant

For every registered POSIX target and every pause epoch `p`:

> If `PauseGuestThreads` has published epoch `p`, then either the target
> acknowledges an epoch `a >= p`, or registration becomes false; once a
> target handler has acknowledged epoch `a`, it never waits based on an old
> epoch and can return from the pause handler only after an acquire load sees
> a Running state (or registration is false).

Consequently, a Resume transition cannot be lost before or during handler
entry: the handler’s first acquire load is authoritative, and every wait
iteration performs another acquire load. Signals only wake the handler; no
correctness decision depends on how many standard signals the kernel coalesces.

The no-lost-wake condition for the controller is:

```text
ack_epoch.store(a, release); sem_post();
controller checks registered/ack_epoch with acquire;
if still waiting, sem_wait();
```

The predicate is checked before sleeping and the post occurs after the
predicate publication, so an acknowledgement cannot fall between the check
and the wait unnoticed. There is no polling/busy loop; a stale semaphore
token is harmless because the acquire predicate is authoritative.

### Lock and lifetime ordering

* `guest_threads_mutex` protects membership, state-transition serialization,
  target-ID capture, and signal generation. It is never taken by the signal
  handler.
* The participant record has no handler-held C++ mutex. Its atomics are the
  only handler/controller synchronization; the semaphore is the wake edge.
* Remote Pause/Resume holds `guest_threads_mutex` through the POSIX
  `pthread_kill` call, as the existing code does. A controller waits for ack
  only after releasing that mutex. Removal invalidates registration before
  taking the list mutex, preventing a sender/waiter versus removal deadlock.
* The protocol does not alter `Pthread` native ownership, `NativeThread`,
  join/detach, or the native cleanup callback. It only gives the existing
  debug-list entry a state/ack record and makes removal safe for a pending
  pause notification.
* `SignalDispatch::RemoveHandlers` and singleton shutdown ordering remain
  unchanged. The pause protocol must outlive registered handlers and target
  threads just as the current `DebugState` does; no handler is invoked after
  signal-handler removal. This stage does not add a shutdown protocol.

## Platform and architecture disposition

Linux x86-64 and arm64 use the POSIX record above. The packed word is a
64-bit atomic and must be lock-free on both supported targets; handler-side
operations are limited to lock-free atomic accesses, `sem_post`, and the
existing `sigwait` notification wait. No x86-specific instruction or signal
number is introduced.

Windows is intentionally separate. `PauseThread`/`ResumeThread` continue to
use `OpenThread` plus `SuspendThread`/`ResumeThread`; Windows APC delivery for
guest signals/cancellation is untouched. The POSIX participant and
`SIGVTALRM` protocol are not copied into the Windows branch, and this stage
does not claim Windows runtime validation.

The active `SA_ONSTACK` exit/free issue remains a separate prerequisite. This
change must not modify `NativeThread::Exit`, `sigaltstack`, active-handler
exit, or alternate-stack reclamation.

## Deterministic focused test matrix

The source test target will use barriers/latches and a bounded watchdog. It
will not rely on standard-signal queue counts and will not use an unbounded
`ctest` hang as a failure mechanism. The final focused matrix is:

1. Pause, wait for target acknowledgement, then Resume.
2. Publish Pause, publish immediate Resume before handler entry.
3. Race Resume with deterministic handler-entry release.
4. Pause -> Resume -> Pause with all notifications coalesced before entry.
5. Repeated Pause is one idempotent epoch and does not require extra edges.
6. Repeated Resume is one idempotent epoch and does not require extra edges.
7. Deliver the independent cancellation notification while the pause handler
   is waiting; verify the cancellation hook runs and pause state remains
   authoritative.
8. Unregister/exit with a pending Pause notification; verify the bounded
   waiter completes and no removed participant is touched.
9. Thousands of deterministic transitions/notifications complete with no
   permanent sleep; the watchdog fails the test if a worker does not reach its
   barrier within the fixed bound.

The pre-implementation checkpoint ran the legacy one-slot model and recorded
its bounded strand before the production debug signal path changed. The
implementation and bounded verification checkpoint is recorded below.

## Implementation and bounded verification checkpoint

The source implementation is committed separately from this project evidence:

* source negative baseline: `c9f173edc952231f2a40d990288918ea7f516411`;
* source test-only reproduction checkpoint: `18927166`;
* source implementation checkpoint: `8851d272` (`Kernel.Debug: make POSIX pause stateful and acknowledged`);
* project evidence/design checkpoint before source implementation: `a100efb6`.

Changed source files are exactly:

* `src/core/debug_state.cpp`;
* `src/core/debug_state.h`;
* `src/core/pause_protocol.h` (new POSIX-only state/ack participant);
* `src/core/signals.cpp`;
* `src/core/signals.h`;
* `tests/CMakeLists.txt`;
* `tests/test_pause_protocol.cpp` (new deterministic legacy and protocol tests).

The focused test target retains the old model as a regression witness. Before
production integration, this command passed against `18927166`:

```text
./tests/shadps4_pause_protocol_test --gtest_filter=PauseProtocolLegacy.PauseThenImmediateResumeCoalescesAndStrands
```

Result: one bounded legacy test passed. Its assertion is that the delayed
handler remains stranded after the coalesced Pause/Resume edge; the test then
performs a test-only wake so it cannot hang. The equivalent single-test ctest
invocation also passed (`1/1`, `0.00 sec`).

After `8851d272`, the deterministic matrix passed:

```text
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build \
  --target shadps4_pause_protocol_test shadps4_native_thread_test -j4
./tests/shadps4_pause_protocol_test --gtest_color=no
ctest --test-dir /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build \
  -R '^PauseProtocol' --output-on-failure
./tests/shadps4_native_thread_test --gtest_color=no
```

Results: the focused binary ran 10 tests (1 legacy reproduction plus 9
stateful cases) and all passed in 25 ms; ctest ran 10/10 and all passed in
0.04 sec; the existing native-thread guard suite ran 18 tests and all passed
in 58 ms. The nine stateful cases cover Pause/ack/Resume, immediate Resume
before handler entry, Resume racing entry, rapid Pause->Resume->Pause,
repeated Pause, repeated Resume, independent cancellation while paused,
pending-pause unregister/exit, and 5,000 coalesced-transition iterations with
a bounded watchdog. The tests use semaphores/latches and explicit signal
masking; correctness does not depend on standard-signal queue counts or
timing-only sleeps.

Normal and static checks passed:

```text
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build \
  --target shadps4 -j4
clang-format-19 --dry-run --Werror \
  src/core/debug_state.cpp src/core/debug_state.h src/core/pause_protocol.h \
  src/core/signals.cpp src/core/signals.h tests/test_pause_protocol.cpp
git diff --check
```

The normal executable linked successfully. CMake reconfiguration reported
`x86_64`; `file`/`readelf -h` reported an ELF64 x86-64 executable. No arm64
cross-toolchain was available in this environment, so arm64 was not
cross-built. The protocol contains no x86-specific instruction or ABI logic;
its portability requirement is a lock-free 64-bit `std::atomic` (enforced by
the source `static_assert`) plus POSIX `sem_post`/`sigwait` behavior.

The state machine now has one authoritative packed `(epoch, paused)` word:

```text
Running(epoch n) --Pause/CAS--> Paused(epoch n+1)
Paused(epoch n)  --Pause------> Paused(epoch n)       [idempotent]
Paused(epoch n)  --Resume/CAS-> Running(epoch n+1)
Running(epoch n) --Resume-----> Running(epoch n)      [idempotent]
```

Pause publishes Paused before notifying targets and waits for each remote
participant to acknowledge the requested epoch, unless that participant
unregisters. Resume publishes Running before notifying and never waits for a
second signal. The handler loads the state on entry, acknowledges that epoch,
returns immediately for Running, and for Paused uses `SIGVTALRM` only as a
wake before repeating an acquire load. Thus coalescing can remove a wake but
cannot remove a logical transition.

The exact invariant is:

> If PauseGuestThreads has published epoch `p`, every target either
> acknowledges epoch `a >= p` or becomes unregistered; once a handler has
> acknowledged `a`, it never waits from an older epoch and returns only after
> an acquire load observes Running or registration is false.

Acknowledgement publication is `ack_epoch.store(..., release)` followed by
`sem_post`; the controller checks registration/acknowledgement with acquire
ordering before `sem_wait`. The list mutex serializes membership, state
transitions, ID capture, and notification. The handler never takes it.
Removal invalidates registration, blocks `SIGVTALRM`, then erases the list
entry; the participant is retained by the target TLS owner or an in-flight
controller snapshot until no handler/waiter can use it.

Windows remains a separate mechanism: `OpenThread` plus
`SuspendThread`/`ResumeThread` is unchanged, as are APC delivery and the
private cancellation path. No POSIX participant is compiled into that branch,
and no Windows runtime claim is made.

This checkpoint intentionally did not change detached-native pthread
lifetime, native join ownership, `NativeThread::Exit`, `sigaltstack`, active
`SA_ONSTACK` exit/free behavior, guest suspend/resume semantics, TextureCache,
Part B, Bloodborne FSM, loading, or run Bloodborne. The active `SA_ONSTACK`
exit/free issue remains the next separate prerequisite: it still needs an
independent safe-stack/post-handler reclamation design and fresh review. This
source checkpoint is ready for the parent to send to a fresh Sol review; it is
not a production-approval declaration.

## Fresh Sol correction design — before implementation

Fresh review of `8851d272` returned `REQUEST_CHANGES`. The accepted scope is
still only the POSIX pause prerequisite. The following correction design was
written before modifying production source.

The first implementation has six gaps:

1. insertion after a Pause target snapshot can let a newly registered guest
   run while the authoritative state is already Paused;
2. an unchanged/idempotent second Pause returns without joining the current
   epoch's acknowledgement obligation;
3. `pthread_kill` errors are discarded and production `sem_wait` is
   unbounded;
4. `sigwait` is not specified as async-signal-safe and only the packed state,
   not every handler-touched atomic, has a lock-free assertion;
5. tests do not exercise enough actual signal-handler wiring, multi-target,
   registration, shutdown, or delivery-failure cases; and
6. epoch exhaustion and stale semaphore-token accumulation are undefined.

The bounded correction is:

* Registration publishes the participant under `guest_threads_mutex`, then
  synchronously rereads and honors the authoritative state before returning
  to `RunThread`. If Paused, the registering target acknowledges and remains
  in the same state-wait path until Running.
* `Protocol` provides a Pause-only serializer. Every Pause caller acquires it,
  snapshots the then-current epoch and participants, and completes that
  epoch's acknowledgement obligation before releasing it. Resume never takes
  this serializer or the guest-list mutex while a target sleeps.
* One named total acknowledgement deadline covers all targets. A live target's
  delivery error, wait error, or deadline expiry conditionally rolls exactly
  that Paused epoch to a newer Running epoch and wakes the current participant
  list. Delivery failures are logged. A concurrent Resume wins the same
  conditional comparison and needs no rollback.
* The pause handler uses `pselect` with no file descriptors and a finite
  state-recheck interval. POSIX lists `pselect`, `pthread_sigmask`, signal-set
  operations, and `sem_post` as async-signal-safe. Every handler loop
  acquire-loads state; the timeout only bounds recovery latency after a lost
  wake and is not an edge or state decision. There is no busy polling.
* Every handler-touched C++ atomic has an `is_always_lock_free` assertion. The
  acknowledgement semaphore is guarded by a lock-free pending-wake bit, so at
  most one unconsumed token exists. A waiter that consumes a token clears that
  bit and always rechecks the authoritative predicate.
* The 63-bit epoch fails safely while still Running before a final Pause could
  consume the last representable epoch. Paused states therefore always retain
  one representable rollback/Resume transition; numeric acknowledgement
  comparison never crosses wrap.

The corrected invariant is stronger:

> A registered target cannot cross registration into guest execution while
> the acquired authoritative snapshot is Paused. Every Pause call is ordered
> by the Pause-only serializer and returns only after each participant in its
> snapshot acknowledges at least that Paused epoch, unregisters, or the
> operation has diagnosed failure and conditionally published Running. Resume
> never waits for the Pause serializer; a handler returns to guest execution
> only after observing Running, unregistration, or publishing the explicit
> fail-open rollback for an internal wait error.

Tests will add active-Pause and empty-list registration, a deterministic
two-controller Pause barrier plus independent Resume, blocked and injected
delivery failure/rollback, multiple targets, unregister/shutdown, an isolated
actual `sigaction` path through the production pause-handler entry point,
deferred cancellation notification while paused, near-exhaustion behavior,
single-token accumulation, and the existing thousands stress. The legacy test
remains only a deterministic one-slot model of the old interleaving; it is not
claimed as execution of the old production handler.

## Correction implementation and verification

The correction is implemented in source commit `381b9ba2` (`Kernel.Debug:
harden POSIX pause acknowledgements`), as a new commit after `8851d272`; test
baseline `18927166` and rejected-history ancestor
`c9f173edc952231f2a40d990288918ea7f516411` remain intact.

Finding disposition:

1. **HIGH, registration while Paused — fixed.** Registration binds TLS,
   inserts under `guest_threads_mutex`, captures the authoritative state, and
   synchronously enters `SynchronizeState()` when that state is Paused before
   returning to guest execution. Both active-list and empty-list Pause then
   register cases are deterministic tests.
2. **HIGH, concurrent/idempotent Pause — fixed.** A Pause-only serializer
   orders every Pause invocation, including unchanged ones. Each invocation
   snapshots the current participants and joins the current Paused epoch's
   acknowledgement obligation. Resume does not acquire that serializer; the
   guest-list lock is released before acknowledgement waits. A two-controller
   barrier test and an independent-Resume test cover these properties.
3. **HIGH, unbounded production failure — fixed.** `pthread_kill` results are
   checked. One shared five-second deadline bounds the complete participant
   acknowledgement operation. Delivery failure, wait failure, or timeout is
   diagnosed and conditionally rolls only the exact Paused epoch to a newer
   Running epoch; a concurrent Resume wins rather than being overwritten.
   Handler-side `pselect` rechecks authoritative state every 100 ms, so even a
   failed Resume notification cannot cause permanent sleep. Tests inject
   delivery failure, block delivery to force deadline rollback, and suppress
   the Resume wake. These intervals are recovery bounds, not correctness
   sleeps or signal-count assumptions.
4. **HIGH, handler safety — fixed for the pause path.** `SIGVTALRM` now enters
   the dedicated `DebugPause::PauseSignalHandler`, not the generic translated
   handler, and production pause waiting no longer calls `sigwait`. The handler
   uses lock-free C++ atomics and POSIX async-signal-safe `pthread_sigmask`,
   `sigdelset`, `pselect`, and `sem_post`. Compile-time lock-free assertions
   cover every handler atomic type. An internal wait/mask error records the
   error and conditionally performs the same exact-epoch fail-open rollback.
   `SA_ONSTACK` is deliberately retained and its separate exit/free problem
   is not changed.

The justified MEDIUM test request is covered by 22 focused tests: the bounded
legacy one-slot model plus 21 protocol tests spanning real production handler
entry in a fork, multiple targets, registration, unregister/shutdown,
delivery errors, all required orderings/idempotence cases, and 5,000
transitions. The native suite adds actual production deferred-cancellation
delivery while paused; it observes the interrupt through a test-only hook,
confirms deferred cancellation does not exit in the pause handler, resumes on
the normal stack, and exits at `PthreadTestCancel`. Its test-installed pause
action intentionally omits `SA_ONSTACK`, avoiding any claim about the separate
active-altstack exit gate. Normal pthread lifecycle/join behavior is unchanged;
the hook is compiled only under `SHADPS4_PTHREAD_LIFECYCLE_TEST` on POSIX.

The LOW epoch/token request is also fixed. Pause fails while Running at the
last safe 63-bit epoch, leaving one representable Running transition for every
reachable Paused state and avoiding wrap comparisons. A lock-free pending-wake
bit coalesces acknowledgements so at most one unconsumed semaphore token
exists; consumption clears the bit and rereads the predicate. Near-exhaustion
and 5,000-ack accumulation/drain tests pass.

The corrected invariant is:

> A registered target cannot cross registration into guest execution while
> its acquired authoritative snapshot is Paused. Every Pause is ordered by
> the Pause-only serializer and returns only after each participant in its
> snapshot acknowledges at least that Paused epoch, unregisters, or failure is
> diagnosed and that exact epoch is conditionally rolled to Running. Resume
> never waits for the Pause serializer. A pause handler returns to guest code
> only after observing Running, unregistration, or publishing an explicit
> fail-open rollback for its exact Paused epoch.

State CAS/publication uses release ordering and readers use acquire ordering.
Acknowledgement epoch publication is release-before-`sem_post`; controller
predicates are acquire reads. Lock order is Pause serializer then
`guest_threads_mutex`, with the list lock released before waiting. Resume takes
only the list lock. The handler takes neither lock. Unregistration marks the
participant unregistered, blocks `SIGVTALRM`, removes it under the list lock,
clears the TLS raw pointer, and releases its owner; controller `shared_ptr`
snapshots pin lifetime. Member declaration order destroys participant owners
before the protocol. Resume racing acknowledgement and rapid
Pause->Resume->Pause are resolved only by the authoritative packed state.

Exact verification performed at `381b9ba2`:

```text
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build \
  --target shadps4_pause_protocol_test shadps4_native_thread_test -j4
ctest --test-dir /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build \
  -R '^PauseProtocol' --output-on-failure
./tests/shadps4_native_thread_test --gtest_color=no
./tests/shadps4_pause_protocol_test \
  --gtest_filter='PauseProtocol.RegistrationDuringActivePauseCannotEnterGuest:PauseProtocol.EmptyListPauseThenRegistrationCannotEnterGuest:PauseProtocol.ConcurrentPauseJoinsCurrentAcknowledgementEpoch:PauseProtocol.FailedResumeNotificationUsesBoundedStateRecheck:PauseProtocol.ThousandsOfCoalescedTransitionsDoNotPermanentlySleep' \
  --gtest_repeat=20 --gtest_break_on_failure --gtest_brief=1
./tests/shadps4_pause_protocol_test \
  --gtest_filter='*ForkIsolatedProductionPauseHandlerEntryResumes' \
  --gtest_repeat=20 --gtest_break_on_failure --gtest_brief=1
./tests/shadps4_native_thread_test \
  --gtest_filter='*DeferredCancellationInterruptsPauseAndExitsAtLaterCancelPoint' \
  --gtest_repeat=50 --gtest_break_on_failure --gtest_brief=1
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build \
  --target shadps4 -j4
clang-format-19 --dry-run --Werror \
  src/core/debug_state.cpp src/core/debug_state.h src/core/pause_protocol.h \
  src/core/signals.cpp src/core/signals.h tests/test_pause_protocol.cpp \
  tests/test_native_thread.cpp
clang-format-19 --dry-run --Werror --lines=1089:1106 \
  src/core/libraries/kernel/threads/pthread.cpp
clang-format-19 --dry-run --Werror --lines=523:526 \
  src/core/libraries/kernel/threads/pthread.h
git diff --check
```

Results: focused ctest 22/22 passed in 0.22 s; native suite 19/19 passed
in 55 ms; the five-case repeat passed all 100 invocations, including 100,000
stress transitions; fork-isolated production handler entry passed 20/20;
actual deferred cancellation passed 50/50. The normal 90-step build linked
successfully. Format and whitespace checks passed. `file` and `readelf -h`
identify the resulting binary as ELF64 AMD x86-64.

No arm64 cross-compiler or Windows build/runtime was available. The POSIX code
has no x86-specific instruction; arm64 must satisfy the same compile-time
lock-free atomic assertions and uses the same specified POSIX primitives.
Windows remains on its existing `SuspendThread`/`ResumeThread` and APC paths;
no POSIX protocol is compiled there and those paths were not modified.

No Bloodborne run was performed. This checkpoint does not declare production
approval; it is ready for a fresh parent-spawned Sol review. The remaining
Part A prerequisite is still active-`SA_ONSTACK` exit/free: a later isolated
task must establish a safe stack trampoline/post-handler reclamation owner and
shutdown ordering before changing `NativeThread::Exit`, altstack teardown, or
storage reclamation.

## Recursive-signal correction design — before implementation

Fresh review of `381b9ba2` found that the handler's `pselect` mask unblocked
`SIGVTALRM`. A Resume followed by another Pause can therefore recursively
enter a second persistent pause handler while the first is still active.

The correction will keep `SIGVTALRM` blocked for the complete handler body and
wait on a per-participant nonblocking pipe. The signal remains only the entry
notification. State transitions publish the authoritative word and write one
coalesced byte to the pipe; the handler waits for pipe readability while its
own signal stays blocked, drains the token, and rereads state. `read`, `write`,
and `pselect` are async-signal-safe. Nonblocking descriptors plus a lock-free
pending-token bit prevent controller or handler blockage and cap queued wake
storage at one byte. Participant construction/destruction owns both FDs;
registration TLS ownership and controller `shared_ptr` snapshots retain the
existing lifetime proof.

Acknowledgement waits will use `sem_clockwait(CLOCK_MONOTONIC)` where supplied
by the Linux/glibc target. The portable fallback will use bounded relative
`pselect` slices, recomputing each slice from `steady_clock`; no realtime
absolute deadline can extend the operation after a backward wall-clock jump.

Handler fail-open will publish an explicit error record containing the failed
Paused epoch and resulting snapshot. Controller reconciliation under
`guest_threads_mutex` will treat either its own exact rollback or an already
won `Running(p+1)` fail-open as responsibility for clearing guest-pause
bookkeeping, applying elapsed paused time once, and waking the current list.
It will not reconcile a newer epoch, so concurrent Resume or a subsequent
Pause cannot be clobbered. Handler entry will save `errno` before touching
protocol state and restore it on every return; protocol errors remain in the
participant record.

Tests will hold one handler while repeatedly cycling Resume/Pause and assert
maximum handler depth one, cover fast and paused errno preservation, inject a
handler wait error and verify state plus pause-time accounting, and add a
fork-isolated integration executable using the real `SignalDispatch` and
`DebugStateImpl` registration/Pause/Resume/removal paths with multiple targets,
registration during Pause, unregister, and rollback. Deferred cancellation
will run through a production guest pthread and real DebugState registration;
the test will return from the pause handler before cancellation reaches its
normal-stack cancellation point, without exercising active-altstack exit.
## Recursive pause-handler correction result

The correction is implemented in source commit
`f37ab79bcc52a59691872add3aca5f5bf681cef9` (`Kernel.Debug: make pause handler
wake nonrecursive`), as a new commit directly atop source
`381b9ba2ad8378ab0c185fffe2b4f9a13365a31b`. The project evidence input remains
commit `5632334a8c0f780532859dbbf135612a7c57cc20`; this stage changes only the
ledger and this companion evidence note. The source files in the checkpoint
are:

* `src/core/debug_state.cpp`
* `src/core/debug_state.h`
* `src/core/pause_protocol.h`
* `src/core/signals.cpp`
* `src/core/signals.h`
* `tests/CMakeLists.txt`
* `tests/test_pause_protocol.cpp`
* `tests/test_pause_integration.cpp`
* `tests/stubs/pause_integration_stub.cpp`

Finding disposition:

1. **HIGH, recursive `SIGVTALRM` — fixed.** The signal is an entry
   notification only. The handler adds `SIGVTALRM` to the `pselect` mask for
   its entire wait, and state changes use a nonblocking, one-byte,
   per-participant pipe plus a lock-free pending bit. `EAGAIN` leaves the bit
   set; the pipe is drained before the authoritative packed state is reread.
   The handler takes no guest-list or pause-request lock. Persistent-handler
   stress records maximum depth one across 5,000 transitions per invocation.
2. **MEDIUM, stale fail-open rollback/accounting — fixed.** The controller
   reconciles an already-won handler rollback only when the current state is
   exactly `Running(p+1)` and a participant in the captured snapshot,
   including the controller's self participant, records the matching failed
   `Paused(p)` epoch. It clears bookkeeping, applies elapsed pause time once,
   and wakes the current list. A newer state is left untouched. The
   integration test covers multiple targets, an unregistering target, a
   failing target, and self fail-open.
3. **MEDIUM, handler `errno` — fixed.** `PauseSignalHandler` saves `errno`
   before touching TLS/protocol state and restores it on every return; fast
   path and paused-wait tests cover this.
4. **MEDIUM, realtime acknowledgement deadline — fixed.** Linux/glibc uses
   `sem_clockwait(CLOCK_MONOTONIC)`. Other POSIX builds use `sem_trywait` and
   bounded 10 ms `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` slices,
   while the outer deadline remains `steady_clock` based. No realtime
   absolute semaphore deadline is used.
5. **MEDIUM, production wiring/cancellation coverage — fixed in scope.** The
   new fork-isolated integration executable links the actual
   `SignalDispatch`, `DebugStateImpl`, participant TLS, guest list, and
   Add/Remove/Pause/Resume paths. It uses a 15-second parent watchdog and
   covers multiple native targets, concurrent Pause callers, registration
   during Pause, unregister while waiting, signal-delivery failure, pipe-wake
   recovery, multi-target fail-open, and self fail-open. The existing native
   pthread suite supplies the production deferred-cancellation case: the
   cancellation interrupt is observed while the pause handler waits, then
   cancellation reaches a later normal-stack cancellation point after
   Resume. Active-handler `pthread_exit`, alternate-stack return, and altstack
   storage reclamation are not exercised.

The LOW epoch boundary now validates the test constructor before packing,
rejects an invalid `Paused(MaximumEpoch)` seed, refuses a new Paused state at
`MaximumEpoch-1` or later, and leaves a representable Running transition for
every reachable Paused state. Acknowledgement wake coalescing still permits
at most one unconsumed semaphore token. Participant construction closes both
pipe descriptors on every post-`pipe` failure, the destructor closes both
before `sem_destroy`, and controller `shared_ptr` snapshots pin the record
until no waiter can use its descriptors. Unregister invalidates first,
temporarily blocks the pause signal, wakes waiters, and restores the prior
mask.

The exact invariant for this checkpoint is:

> A registered target cannot cross registration into guest execution while
> its acquired authoritative snapshot is Paused. Every Pause is ordered by
> the Pause-only serializer and returns only after each participant in its
> snapshot acknowledges at least that Paused epoch, unregisters, or failure is
> diagnosed and that exact epoch is conditionally rolled to Running. Resume
> never waits for the Pause serializer. A pause handler returns to guest code
> only after observing Running, unregistration, or publishing an explicit
> fail-open rollback for its exact Paused epoch.

Handler-side operations are limited to lock-free atomics and the audited POSIX
signal-safe mask, `pselect`, `read`, and `sem_post` path. Pipe writes are
controller/unregister operations, never handler operations. State is the only
correctness predicate; pipe and semaphore wakes are bounded hints.

Exact verification performed at source `f37ab79b`:

~~~text
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build --target shadps4_pause_protocol_test shadps4_pause_integration_test shadps4_native_thread_test -j4
./tests/shadps4_pause_protocol_test --gtest_color=no
./tests/shadps4_pause_integration_test --gtest_color=no --gtest_filter='PauseProductionIntegration.*'
ctest --test-dir /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build -R '^(PauseProtocol|PauseProductionIntegration)' --output-on-failure
./tests/shadps4_pause_protocol_test --gtest_color=no --gtest_filter='PauseProtocol.RegistrationDuringActivePauseCannotEnterGuest:PauseProtocol.EmptyListPauseThenRegistrationCannotEnterGuest:PauseProtocol.ConcurrentPauseJoinsCurrentAcknowledgementEpoch:PauseProtocol.FailedResumeNotificationUsesBoundedStateRecheck:PauseProtocol.ThousandsOfCoalescedTransitionsDoNotPermanentlySleep' --gtest_repeat=20 --gtest_break_on_failure --gtest_brief=1
./tests/shadps4_pause_integration_test --gtest_color=no --gtest_filter='PauseProductionIntegration.*' --gtest_repeat=50 --gtest_break_on_failure --gtest_brief=1
./tests/shadps4_native_thread_test --gtest_color=no
./tests/shadps4_native_thread_test --gtest_color=no --gtest_filter='*DeferredCancellationInterruptsPauseAndExitsAtLaterCancelPoint' --gtest_repeat=50 --gtest_break_on_failure --gtest_brief=1
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build --target shadps4 -j4
clang-format-19 --dry-run --Werror src/core/debug_state.cpp src/core/debug_state.h src/core/pause_protocol.h src/core/signals.cpp src/core/signals.h tests/test_pause_protocol.cpp tests/test_pause_integration.cpp tests/stubs/pause_integration_stub.cpp
git diff --check
file /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build/shadps4
readelf -h /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build/shadps4
~~~

Results: focused protocol binary passed 30/30 tests (29 protocol tests plus
the retained bounded legacy model); production integration passed 1/1; ctest
31/31 in 1.41 s; five-test stress repeat passed all 100 invocations and
exercised 100,000 transition iterations; integration repeat 50/50; native
suite 19/19; deferred cancellation repeat 50/50; normal build linked;
format/whitespace/ELF checks passed; ELF64 AMD x86-64.

No arm64 cross-compiler or Windows runtime was available. POSIX protocol code
has no x86-specific instruction and asserts lock-free atomics; arm64 needs a
target build and runtime libc verification. Windows excludes POSIX and its
existing `SuspendThread`/`ResumeThread`/APC branches were not changed. No
Bloodborne. Detached-native, altstack exit/free, and Part B are out of scope.
A fresh independent review is required; no later stage begins until the
parent review gate passes. Active-altstack exit/free remains a separate
prerequisite.

## A6 correction loop — fail-open epoch, publication, accounting, and TLS

The late independent review of source `f37ab79bcc52a59691872add3aca5f5bf681cef9`
returned `REQUEST_CHANGES` on four concrete findings. All four reproduce against
the source at that commit; none is rejected. The correction is source commit
`cda2e76a05dd22037047fa398f06998cb659428f`, directly atop `f37ab79b`. The
project evidence input for this note is `963e0efeba49678d996ea8235d0d5b47e3b39568`.

The deterministic baseline probes established:

* With an old `Paused(1)` snapshot held across `Resume` and a newer `Pause`,
  the pre-correction `FailOpen` attempted only the old rollback, then
  acknowledged the returned newer `Paused(3)` snapshot and returned. The
  observed final state was `Paused(3)` with no fail-open markers, rather than
  `Running(4)`.
* A publication barrier after the old `wait_error.store` observed `wait_error`
  as `EBADF` while the exact failed-epoch and Running markers were still at
  their sentinels. This is the controller visibility interval called out by
  the review.
* A delayed-failure integration variant injected the wait error only after the
  original `PauseGuestThreads` had returned. The pre-correction bookkeeping
  charged through the guest-running delay and the fork-isolated parent failed.
* `CurrentParticipant` was a plain `thread_local` pointer read by the signal
  handler while bind/clear wrote it. That asynchronous read/write pair had no
  signal-safe C++ publication protocol; the finding is valid even where a
  particular run does not expose the race.

Finding disposition and bounded correction:

1. **HIGH, stale fail-open epoch — fixed.** `FailOpen` treats its caller
   snapshot as a hint, rereads after every failed exact CAS, and loops until it
   observes Running/unregistered or atomically rolls back the currently
   observed Paused epoch. It never acknowledges a Paused snapshot while
   returning from fail-open. The old-to-new epoch test asserts the newer epoch,
   exact markers, and acknowledgement.
2. **MEDIUM, publication interval — fixed.** The failed epoch, monotonic
   `FencedRDTSC` timestamp, and resulting Running epoch are published before
   `wait_error`; the resulting epoch is the release publication gate for the
   record. A lock-free pending bit covers the smaller interval in which the
   protocol CAS has made Running visible but the record is not complete.
   `DebugStateImpl` defers reconciliation while that bit is set. A direct
   barrier test checks marker visibility before `wait_error`, and the real
   integration barrier holds the CAS-to-record interval while a controller
   attempts reconciliation.
3. **MEDIUM, late fail-open/accounting — fixed.** The exact fail-open record is
   durable on the participant. Pause, Resume, and current-thread removal
   reconcile it under `guest_threads_mutex`, charge through the recorded
   Running edge once, and refuse to start a new pause while publication is
   pending. The integration model pauses, returns, injects the delayed error,
   holds publication, verifies bookkeeping remains open, waits 50 ms of guest
   running time, then removes/resumes and checks accounting against the
   fail-open timestamp rather than the later wall time.
4. **MEDIUM, participant TLS — fixed.** `CurrentParticipant` is now a
   lock-free `thread_local std::atomic<Participant*>`, with a compile-time
   lock-free assertion. Bind uses release publication, the handler uses an
   acquire load, and clear uses an identity-checked CAS so a stale clear cannot
   erase a newer binding. The interrupt bind/clear test repeatedly exercises
   the real `SIGVTALRM` entry while cycling the binding.

The correction preserves the protocol invariant:

> At every fail-open return, a registered participant has observed authoritative
> Running/unregistered or has atomically rolled back exactly the current
> Paused epoch; a handler-won rollback publishes its exact record before
> `wait_error` or acknowledgement, and no controller closes pause accounting
> while that record is pending. A later Pause, Resume, or participant removal
> reconciles a durable late record once.

State remains authoritative; pipe and semaphore wakes remain bounded hints. The
handler still has no recursion, no guest-list or pause-request lock, no
unbounded wait, and preserves `errno`. Monotonic timing, cancellation
independence, idempotence, and participant lifetime are unchanged. Detached
native pthread lifetime, active-`SA_ONSTACK` exit/free, Bloodborne/runtime
harness, and Part B were not touched.

Exact post-correction verification at source `cda2e76a`:

~~~text
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build --target shadps4_pause_protocol_test shadps4_pause_integration_test shadps4_native_thread_test -j4
./tests/shadps4_pause_protocol_test --gtest_color=no --gtest_filter='PauseProtocol.FailOpenRollsBackCurrentPausedEpochAfterStateAdvance:PauseProtocol.FailOpenPublishesRollbackRecordBeforeWaitError:PauseProtocol.CurrentParticipantBindingCanBeInterruptedDuringBindAndClear'
./tests/shadps4_pause_protocol_test --gtest_color=no
./tests/shadps4_pause_integration_test --gtest_color=no
ctest --test-dir /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build -R '^(PauseProtocol|PauseProductionIntegration)' --output-on-failure
./tests/shadps4_native_thread_test --gtest_color=no
./tests/shadps4_pause_protocol_test --gtest_color=no --gtest_repeat=20 --gtest_break_on_failure --gtest_brief=1
./tests/shadps4_pause_integration_test --gtest_color=no --gtest_repeat=50 --gtest_break_on_failure --gtest_brief=1
./tests/shadps4_native_thread_test --gtest_color=no --gtest_repeat=50 --gtest_break_on_failure --gtest_brief=1
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build --target shadps4 -j4
clang-format-19 --dry-run --Werror src/core/pause_protocol.h src/core/debug_state.h src/core/debug_state.cpp tests/test_pause_protocol.cpp tests/test_pause_integration.cpp
git diff --check
~~~

Results: the three new deterministic protocol tests passed 3/3; the full
protocol binary passed 33/33; production integration passed 1/1; focused ctest
passed 34/34 in 1.40 s; native suite passed 19/19. The full protocol repeat
passed all 20/20 invocations (33/33 each), integration repeat passed 50/50,
and native repeat passed 50/50 (19/19 each). The normal `shadps4` build
completed successfully; format and whitespace checks passed. No Bloodborne run
was performed. A fresh independent parent review remains required before any
later stage; this correction loop does not approve Part A prerequisite #1.

## A6 targeted correction — publication gate and durable rollback ownership

The fresh independent review of source `cda2e76a05dd22037047fa398f06998cb659428f`
returned `REQUEST_CHANGES` with no HIGH findings and two blocking MEDIUM races.
The source correction is `d644dffd312719d885114d552143a6aeb7844456`, directly
atop `cda2e76a`; the project documentation input was
`1259c5191bbf119f41820c878fb4212d53b02b07`. Both findings were validated
against the source and addressed; neither was rejected.

The bounded correction is:

1. `Participant::FailOpen` enters a protocol-owned lock-free publication count
   before attempting `Paused(p) -> Running(p+1)`. A successful CAS has a
   deterministic test seam exactly before `FencedRDTSC`; the exact
   `(failed_pause_epoch, running_epoch, uptime)` record is release-published
   before the count is decremented. `SynchronizeState` treats `Running` with a
   nonzero count as not guest-safe and rechecks in its bounded wait loop, so a
   descheduled winner cannot expose Running to another handler before its
   rollback time exists.
2. The rollback record and publication count live in `Protocol`, not in a
   participant. Reconciliation refuses to close the pause interval while any
   publication is pending, and the last completion posts a coalesced semaphore
   wake. A record whose running epoch is the current epoch supplies the exact
   monotonic boundary; the atomic bookkeeping exchange makes the PTC adjustment
   exactly once, and participant removal cannot erase the record.

New lifecycle/accounting invariant:

> From before a handler-won `Paused(p) -> Running(p+1)` CAS until its exact
> rollback record is published and all publication participants complete, the
> protocol publication count is nonzero. No pause handler returns guest
> execution while that count is nonzero. Reconciliation only clears pause
> bookkeeping after the count reaches zero; for matching `Running(p+1)` it
> uses the captured rollback uptime, clamps at `pause_time`, and clears the
> interval with one atomic exchange. Therefore no time after the handler CAS
> and before timestamp/publication can be charged as paused, and a removed
> winner cannot lose the accounting boundary.

The deterministic tests are
`PauseProtocol.PublicationGateBlocksRunningObserverDuringTimestampCapture` and
`PauseProtocol.RollbackRecordSurvivesWinnerRemovalUntilLastPendingCompletion`.
The latter holds a winner record, leaves a loser pending, removes the winner,
delays loser completion, verifies the completion wake and exact record, and
exercises a concurrent `PauseGuestThreads` plus exactly-once PTC adjustment.

~~~text
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build --target shadps4_pause_protocol_test shadps4_pause_integration_test shadps4_native_thread_test -j4
./tests/shadps4_pause_protocol_test --gtest_color=no --gtest_filter='PauseProtocol.PublicationGateBlocksRunningObserverDuringTimestampCapture:PauseProtocol.RollbackRecordSurvivesWinnerRemovalUntilLastPendingCompletion'
./tests/shadps4_pause_integration_test --gtest_color=no --gtest_filter='PauseProductionIntegration.SignalDispatchDebugStateLifecycleAndRollback'
./tests/shadps4_pause_protocol_test --gtest_color=no
./tests/shadps4_pause_integration_test --gtest_color=no
./tests/shadps4_native_thread_test --gtest_color=no
ctest --test-dir /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build --output-on-failure -R '^(PauseProtocol|PauseProductionIntegration)'
./tests/shadps4_pause_protocol_test --gtest_color=no --gtest_repeat=20 --gtest_break_on_failure --gtest_brief=1
./tests/shadps4_pause_integration_test --gtest_color=no --gtest_repeat=50 --gtest_break_on_failure --gtest_brief=1
./tests/shadps4_native_thread_test --gtest_color=no --gtest_repeat=50 --gtest_break_on_failure --gtest_brief=1
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build --target shadps4 -j4
clang-format-19 --dry-run --Werror src/core/pause_protocol.h src/core/debug_state.h src/core/debug_state.cpp tests/test_pause_protocol.cpp tests/test_pause_integration.cpp
git diff --check
~~~

Results at source `d644dffd`: the focused protocol tests passed 2/2 and the
focused production integration passed 1/1; full protocol passed 35/35,
production integration 1/1, and native suite 19/19. Focused ctest passed
36/36 in 1.59 s. Deterministic repeats passed 20/20 protocol invocations
(35/35 each), 50/50 integration invocations, and 50/50 native invocations
(19/19 each). The production build linked successfully; format and whitespace
checks passed. An initial repeat exposed a test-only assumption that guest-list
insertion order identified the winning native thread; the test was corrected to
use native thread IDs, and the final clean repeats passed.

This remains a source-correction checkpoint, not approval. A fresh independent
review of `d644dffd` is required before the parent opens the next stage. No
Bloodborne, detached-native, altstack, or Part B work was performed.

## A6 late-review correction — registration-safe publication gate

Date: 2026-09-14. The source input was clean commit
`d644dffd312719d885114d552143a6aeb7844456`; the project evidence input was
`90dbb15faad0b04f11a352bb328a5a63e9ba3ff0`. Fresh review returned
`REQUEST_CHANGES` with one MEDIUM production race and one LOW test-rigor
finding. The source correction is committed separately as
`75645a6c0a0d80b5b91fd8c12c66d7e5f24bac44`, directly atop `d644dffd`.

The production correction removes the pre-read `Paused` shortcut from
`DebugStateImpl::AddCurrentThreadToGuestList`: after publishing the participant
in the guest list, registration always calls `SynchronizeState()`. Its existing
authoritative predicate is therefore applied to both `Paused` and
`Running && RollbackPublicationPending`; a registering thread cannot return to
guest execution during the CAS-to-record publication interval. No guest-list
lock is taken by the handler, and the protocol-owned publication count, exact
rollback record, durable reconciliation, idempotent accounting exchange, and
bounded wake behavior remain unchanged.

The deterministic coverage adds a test-only hook immediately before the
participant state wait and one immediately before the rollback-completion
semaphore wait. The production integration holds the exact fail-open
CAS-to-timestamp seam, registers a newcomer after list insertion, proves its
registration/guest entry remains blocked while publication is pending, then
releases the publication and verifies the state wake. The lifecycle rollback
case also replaces its timing sleep with the actual timestamp seam plus a
bookkeeping barrier.

Exact verification at source `75645a6c`:

~~~text
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build --target shadps4_pause_protocol_test shadps4_pause_integration_test shadps4_native_thread_test -j4
./tests/shadps4_pause_protocol_test --gtest_color=no --gtest_filter='PauseProtocol.PublicationGateBlocksRunningObserverDuringTimestampCapture:PauseProtocol.RollbackRecordSurvivesWinnerRemovalUntilLastPendingCompletion'
./tests/shadps4_pause_integration_test --gtest_color=no --gtest_filter='PauseProductionIntegration.SignalDispatchDebugStateLifecycleAndRollback'
./tests/shadps4_pause_protocol_test --gtest_color=no
./tests/shadps4_pause_integration_test --gtest_color=no
./tests/shadps4_native_thread_test --gtest_color=no
ctest --test-dir /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build --output-on-failure -R '^(PauseProtocol|PauseProductionIntegration)'
./tests/shadps4_pause_protocol_test --gtest_color=no --gtest_filter='PauseProtocol.PublicationGateBlocksRunningObserverDuringTimestampCapture:PauseProtocol.RollbackRecordSurvivesWinnerRemovalUntilLastPendingCompletion' --gtest_repeat=300 --gtest_break_on_failure
./tests/shadps4_pause_integration_test --gtest_color=no --gtest_filter='PauseProductionIntegration.SignalDispatchDebugStateLifecycleAndRollback' --gtest_repeat=100 --gtest_break_on_failure
./tests/shadps4_native_thread_test --gtest_color=no --gtest_repeat=50 --gtest_break_on_failure --gtest_brief=1
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build --target shadps4 -j4
clang-format-19 --dry-run --Werror src/core/debug_state.cpp src/core/pause_protocol.h tests/test_pause_protocol.cpp tests/test_pause_integration.cpp
git diff --check
~~~

Results: focused protocol 2/2 and production integration 1/1; full protocol
35/35, production integration 1/1, native 19/19, and focused ctest 36/36 in
1.58 s. Concurrent deterministic stress passed 300 protocol repeat iterations
and 100 production-integration repeat iterations; native passed 50 repeat
iterations of all 19 tests. The normal build linked successfully, the output
is ELF64 x86-64, and format/whitespace checks passed. An initial stress run
exposed a pre-existing timing assumption in an adjacent lifecycle case; the
case was made seam/barrier-driven and the final concurrent repeats passed.

This is a source-correction handoff, not approval. No later stage is opened
until fresh independent review passes. Detached-native, altstack exit/free,
Bloodborne, and Part B remain untouched; no Bloodborne runtime was run.

## A6 APPROVE_WITH_FOLLOWUPS cleanup — signal-test rigor

Date: 2026-09-14. The parent review disposition was
`APPROVE_WITH_FOLLOWUPS`, limited to the two LOW test-rigor findings above.
The clean source input was
`75645a6c0a0d80b5b91fd8c12c66d7e5f24bac44`; the clean project input was
`24e8918e71a2e14ae327655370394f9c74f53036`. The source-only correction is
committed as `ccaf14efb113303cbd4c14cf50197a1aaaf1ab94`, directly atop the
source input. The source worktree was clean at that checkpoint.

The integration newcomer no longer sends `SIGVTALRM` as a purported state
wake. The test-only `DebugStateImpl::TestNotifyStateChange(ThreadID)` seam
looks up the registered participant and invokes its existing coalesced
`NotifyStateChange()` pipe wake. The test releases the state-wait barrier,
uses that actual pipe wake, and then verifies guest entry; it does not depend
on the 100 ms state recheck.

All signal-context pause test hooks, including `HoldFailOpenTimestamp`, now
use lock-free atomic reached/release flags. The test gates assert that
`std::atomic_bool` is always lock-free; bounded watchdog waits stay on the
ordinary test thread, while the signal-context hook performs only atomic
operations. The existing ordinary test semaphores remain for non-signal
barriers. No production pause protocol behavior or production busy-loop was
added; the test-only seam is compiled only under
`SHADPS4_PAUSE_PROTOCOL_TEST`.

Exact verification at source `ccaf14ef`:

~~~text
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build --target shadps4_pause_protocol_test shadps4_pause_integration_test shadps4_native_thread_test -j4
./tests/shadps4_pause_protocol_test --gtest_color=no
./tests/shadps4_pause_integration_test --gtest_color=no --gtest_filter='PauseProductionIntegration.*'
./tests/shadps4_native_thread_test --gtest_color=no
ctest --test-dir /media/ubuntu/UsbSSD447G/shadps4/shadPS4-test-build --output-on-failure -R '^(PauseProtocol|PauseProductionIntegration)'
./tests/shadps4_pause_protocol_test --gtest_color=no --gtest_filter='PauseProtocol.FailOpenRollsBackCurrentPausedEpochAfterStateAdvance:PauseProtocol.FailOpenPublishesRollbackRecordBeforeWaitError:PauseProtocol.PublicationGateBlocksRunningObserverDuringTimestampCapture:PauseProtocol.RollbackRecordSurvivesWinnerRemovalUntilLastPendingCompletion' --gtest_repeat=300 --gtest_break_on_failure --gtest_brief=1
./tests/shadps4_pause_integration_test --gtest_color=no --gtest_filter='PauseProductionIntegration.SignalDispatchDebugStateLifecycleAndRollback' --gtest_repeat=100 --gtest_break_on_failure --gtest_brief=1
./tests/shadps4_native_thread_test --gtest_color=no --gtest_filter='PthreadProductionPath.DeferredCancellationInterruptsPauseAndExitsAtLaterCancelPoint' --gtest_repeat=50 --gtest_break_on_failure --gtest_brief=1
cmake --build /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build --target shadps4 -j4
clang-format-19 --dry-run --Werror src/core/debug_state.h tests/test_pause_protocol.cpp tests/test_pause_integration.cpp
git diff --check
file /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build/shadps4
readelf -h /media/ubuntu/UsbSSD447G/shadps4/shadPS4-build/shadps4
~~~

Results: source test-target build passed; full protocol passed 35/35,
production integration 1/1, native suite 19/19, and focused ctest 36/36 in
1.47 s. The four followup protocol cases passed 300/300 repeat iterations;
production integration passed 100/100; and the deferred-cancellation native
case passed 50/50. The normal `shadps4` build linked, format and whitespace
checks passed, and the artifact was ELF64 x86-64.

The arm64/non-glibc runtime remains unavailable in this environment: no
arm64 cross-runtime or non-glibc runtime was available for execution, and
that provisioning is not fixable within this test-only cleanup. No Bloodborne
runtime was run. Detached-native, altstack exit/free, and Part B were not
touched. This is a source-correction handoff for fresh independent review,
not a production-semantics change or a later-stage opening.

## Final independent review closure — `APPROVE`

Date: 2026-09-14. The final independent reviewer returned `APPROVE` with no
findings for final source `ccaf14efb113303cbd4c14cf50197a1aaaf1ab94`. The
test/evidence project input for this documentation closure is
`28ef846c488a7c68a81f9db08d3708bfb13a1faf`.

The review covered the test-only cleanup: the actual participant pipe wake and
the signal-safe lock-free atomic test gates. The established invariant remains:

> If `PauseGuestThreads` has published epoch `p`, then either the target
> acknowledges an epoch `a >= p`, or registration becomes false; once a target
> handler has acknowledged epoch `a`, it never waits based on an old epoch and
> can return from the pause handler only after an acquire load sees a `Running`
> state (or registration is false).

Final evidence totals are protocol 35/35, integration 1/1, native 19/19, and
ctest 36/36; repeats are 300/300, 100/100, and 50/50. Build, format, and diff
checks passed.

This approves Part A prerequisite #1 only. Stop here: detached-native, the
active-`SA_ONSTACK` Part A prerequisite #2, Bloodborne, and Part B were
untouched. arm64/non-glibc runtime coverage was unavailable and remains a
later validation consideration; this closure opens no later stage.
