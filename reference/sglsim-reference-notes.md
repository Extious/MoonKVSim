# SGLSim reference notes

SGLSim is a dirty, reference-only checkout at commit
`ca1fe76e88959a2bac0f6060e3042dc2c7d4f855`. The exact files inspected are
locked individually in `source-lock.json`; modified and untracked files use
their worktree SHA-256 in addition to any base-commit blob.

The untracked `global_des.py` contains useful stable-event and audit ideas, but
also contains SGLang physical-rank identity plus HiCache/AegisKV tiers and
accounts. MoonKVSim must not port those enums, scheduling semantics or
wall-clock behavior. Its own DES is independent and is validated against the
MoonKVSim plan.

The Weka trace and README are also untracked source artifacts. Their separate
hashes, license statement and `source_hash_blocks_64` evidence boundary are
part of the lock; the repository commit alone cannot reproduce them.
