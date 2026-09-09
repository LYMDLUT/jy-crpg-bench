# Full session recordings

Set `QUNXIA_RECORDING_DIR` to a writable disk directory. The single server uses
`<port>.jsonl`; `QUNXIA_RECORDING_FILE` can select a file within persistent storage.
The benchmark broker assigns a separate file per run, outside the disposable
game copy. A reset archives the previous recording rather than deleting it.

Every tile delta and key/action event produced by the existing stream is appended
and flushed to JSONL. The server retains no history list. A storage error pauses
interactive input and retries the bounded pending write; a benchmark storage
failure invalidates the run. This retains the existing stream cadence; it does
not claim to capture every native emulator frame.

`GET /api/recording` still exports the original JSON envelope, now as a stream.
`?format=jsonl` downloads the raw journal. The existing 4x browser replay and
MediaRecorder MP4/WebM export read bounded pages of one fixed snapshot. Benchmark
MP4 rendering and its timeline publication also consume the disk recording.
Browser MediaRecorder output chunks are still held in the browser until download;
this change bounds the server history and replay input, not all browser memory.

Paged responses advertise `seek_supported`. To seek the same pinned snapshot,
request `?view=paged&token=<token>&time=<recorded-seconds>`. The first seek builds
a sparse SQLite keyframe index in `.replay-index/`, returning HTTP 202 with
`indexing`, `scanned` and `total` until ready. Normal startup and sequential
playback do not build that index. Later opens extend cached metadata only for
newly committed bytes of the same inode.

A ready seek returns the bounded page starting at the last complete frame at
or before the requested time (or the first frame), plus `seek.at`, `seek.origin`
and the held keys at that cursor. Apply that frame and subsequent deltas through
the target time. Old unmarked complete frames are recognized from their tile
headers. The JSONL remains unchanged; reset and append cannot change an open
reader's prefix. Closing a reader cancels its index worker, which owns and
releases a separate descriptor. The index stores offsets/key state, not frame
payloads; SQLite uses a 2 MiB cache and temporary data stays on disk.

Cloud Run's writable container filesystem uses instance memory and disappears
when the instance stops. A path under `/tmp` does not solve that problem. Configure
an actual POSIX persistent volume and point `QUNXIA_RECORDING_DIR` to it; startup
rejects the container root filesystem and tmpfs, unless the deployment sets
`QUNXIA_RECORDING_ALLOW_EPHEMERAL=1`, which accepts the instance memory - a run
cannot outlive its instance, so the only thing lost is the journal read back
after the instance stops - and says so in a warning at every start-up. NFS buffering, game copies,
process working memory and host page caches still count toward deployment limits.
The directory probe checks write/fsync/rename, not crash durability of a remote
storage service. No volume or cloud deployment is created by this change.

Sources: [Cloud Run filesystem contract](https://docs.cloud.google.com/run/docs/container-contract),
[NFS volume behavior](https://docs.cloud.google.com/run/docs/configuring/services/nfs-volume-mounts).
