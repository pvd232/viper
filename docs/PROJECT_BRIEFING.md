# VIPER project briefing

VIPER 0.1.0a1 is available from PyPI. The next project action is to use the
public package in a real experiment and record the first interface problem that
blocks or complicates that run.

## Why VIPER exists

VIPER gives a machine-learning experiment an executable contract. The contract
fixes the source, inputs, stage definitions, environment, and run-wide
reproducibility controls before execution. VIPER then records what each stage
used and produced. Verification follows those stored relationships from the
terminal run back to the frozen plan.

The frozen-plan and verification chain gives a human or an agent a bounded way
to change experimental code while preserving the evidence needed to inspect
the result. Data-use roles also prevent evaluation and benchmark inputs from
entering a training stage through a valid plan.

## How one run moves through the system

```text
project source + experiment decisions
                  |
                  v
           frozen run plan
                  |
                  v
        complete-plan preflight
                  |
                  v
       ordered stage invocations
                  |
                  v
   immutable attempt and stage files
                  |
                  v
         terminal verification
                  |
                  v
    optional benchmark confirmation
```

The frozen plan identifies exact project-owned callables and parameter classes.
The runner constructs a typed stage context and launches each callable in a
controlled child process. The child records the realized CPU or CUDA runtime,
the applied reproducibility controls, and the files produced by the stage. The
runner publishes those files into content-addressed snapshots and writes one
canonical attempt document. The verifier retrieves each referenced file,
checks its byte identity, and checks every declared relationship.

## Verified current position

The public alpha has crossed its implementation, deployment, and publication
gates.
The repository marks the parameter, stage-invocation, startup, HTTP, metric,
artifact, attempt, benchmark, cloud, and package-release contracts as
implemented.

The exact candidate passed the complete repository suite under Python 3.14.6:
225 host-independent tests and 33 subtests passed. Six hardware-gated tests ran
separately on the L4 host.
The same commit passed GitHub Actions under Python 3.11 through 3.14. Clean
environments for all four Python versions imported the built wheel from
`site-packages` and passed the public-interface checks.

The installed wheel also completed the generated acquisition run, the
five-stage candidate run, an independent benchmark confirmation, and terminal
verification outside the source checkout. A pre-provisioned GCE instance with
an NVIDIA L4 then ran the same wheel, passed the live CUDA startup checks, and
completed the generated project. The ephemeral VM and its 500 GB SSD were
deleted after the gate; the approved machine image remains available. The
[release-candidate report](releases/0.1.0a1.md) records the exact commit,
distribution digests, commands, environments, and results.

PyPI and TestPyPI contain the same wheel and source archive. The signed tag
`v0.1.0a1` identifies the validated source commit.

## Public release

Install the public alpha with:

```bash
python -m pip install "viper-provenance==0.1.0a1"
```

The [release report](releases/0.1.0a1.md) records the complete validation and
publication evidence. The [publication checklist](PUBLICATION_TODO.md) records
every completed release obligation.
