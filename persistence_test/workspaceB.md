# Persistence test write — Workspace B

Written by a second, independent fresh `git clone`, started from the same
base as Workspace A (cc40191) but *without* re-fetching after A's push, to
verify the serialization/atomic-claim mechanism in PERSISTENCE.md: a plain
push from a stale base must be rejected, not silently overwrite A's work.
