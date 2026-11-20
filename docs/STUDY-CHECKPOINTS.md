# Study checkpoint inputs

Use checkpoints produced by this repository's training commands in a workspace you control. This applies to explicit checkpoint arguments, checkpoint directories, and paths read from study reports when resuming or evaluating a run.

Stable-Baselines3 checkpoint archives can contain serialized Python objects. Treat loading a checkpoint as executing code with your account's permissions. For a checkpoint supplied by a collaborator, confirm who produced it and verify its SHA-256 against a digest obtained from that collaborator through a trusted channel before loading it. A digest verifies the file's identity. The producer still needs to be trusted.

For a checkpoint of unknown provenance, rerun training from trusted source and inputs. Keep the checkpoint's producing command, repository revision, and digest with any shared study result that depends on it.
