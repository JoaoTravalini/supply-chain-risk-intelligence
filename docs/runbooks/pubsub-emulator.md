# Pub/Sub Emulator Runbook

This runbook documents local Google Cloud Pub/Sub emulator use for SupplyChain Sentinel development. It creates no real cloud resources.

## Terminal A - Start Emulator

```powershell
gcloud beta emulators pubsub start --project=supplychain-local --host-port=127.0.0.1:8085
```

Keep this terminal open while using the emulator. Emulator state is ephemeral and is lost when the emulator process stops.

## Terminal B - Project Environment

```powershell
$env:PUBSUB_EMULATOR_HOST = "127.0.0.1:8085"
$env:PUBSUB_PROJECT_ID = "supplychain-local"
```

PowerShell environment variables apply only to the current shell. Recreate them in each new terminal.

Check that the local port is reachable:

```powershell
Test-NetConnection 127.0.0.1 -Port 8085
```

## Local Project Convention

`supplychain-local` is intentionally not the real Google Cloud project. It is the local emulator project ID used to prevent accidental real-cloud Pub/Sub mutation during development.

Application/bootstrap code creates emulator resources. Do not use `gcloud pubsub` to create project resources for this local stage.

## Safety Rules

- The emulator must be restarted after closing Terminal A.
- Emulator state is not persisted into the repository.
- No service-account key is required.
- Do not copy Application Default Credentials into the repository.
- Do not create real Pub/Sub topics or subscriptions from this runbook.
- Future real cloud Pub/Sub resources must be managed through OpenTofu/IaC.
