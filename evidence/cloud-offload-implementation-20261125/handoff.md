# Published native storage handoff

Use Viper `df10a3e2258a28d7eb276d5a35a5621c0384a694` and JEP `d44073e296a638944a83684e9635d9b7fffc104f` from the published review branches. JEP pins the Viper source. Integrate the storage changes into the existing worktree while preserving unrelated agent-supervision and campaign changes.

Viper owns the durable background queue, retries, recovery, shared cache and deletion decision. Related work belongs inside one `viper.storage.workflow` owned by the runner. New native executions enqueue original completed outputs. Existing saved runs can use `viper.execution.enroll`. Ordinary artifact access uses native references and the shared resolver. The offload setting controls local retention; per-artifact preferences remain available.

Inside an open workflow, checkpoint acknowledgments use verified per-source publication copies. Final root publication completion is observed only after collection closes. Source files and their host remain available until successful verification or a verified durable handoff. Keep existing attached project/account, namespace, allocation and resource-ownership checks. Do not restore a separate JEP upload queue.

The final validation record covers 805 fast tests, 227 selected integration nodes and 47 JEP CPU tests, with their scoped subtest results. Ten reviews were reconciled. Source restoration now proves the original Git commit/path as well as payload content. The proof metadata uses existing snapshot transport and registry authority.

The functional dependency is published. Complete the existing agent-supervision implementation, then start the user-authorized JEP annotation campaign under its existing execution contracts and ownership boundaries. Use the current public Viper API as the storage abstraction.

CFO-REQ-10 remains open because source/test code grew by 10,763 lines. These draft publications do not assert formal contract acceptance. There was no live cloud/campaign execution in this implementation task.
