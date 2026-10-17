# PB-06 validation revision

This revision includes the checked Pyrefly configuration and type corrections from PB-02. PB-03 also gives MemoryHub.head its explicit string type; all later blocks retain that test-helper correction. The original PairBlock implementation remains in its own PR. Historical receipts retain their actual commands. The current CI run checks the exact revised tree.

PB-06 makes the existing snapshot progress record available to the comparison module as SnapshotCopy. PB-07 carries this shared-name correction forward.
