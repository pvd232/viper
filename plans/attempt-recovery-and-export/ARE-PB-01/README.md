# ARE-PB-01

This plan exposes a failed terminal run on `RunError` and resumes verified
completed stages from that run during `retry()`. It extends the existing reuse
receipt and snapshot path; stage workers, GPU/CPU boundaries, and metric or
build call signatures do not change.
