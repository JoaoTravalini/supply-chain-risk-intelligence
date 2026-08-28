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

The local bootstrap can ensure:

- topic: `canonical-events-v1`
- dead-letter topic: `canonical-events-dead-letter-v1`
- subscription: `canonical-events-processing-v1`
- dead-letter inspection subscription: `canonical-events-dead-letter-inspection-v1`

The processing subscription is configured with a native dead-letter policy that
points to `canonical-events-dead-letter-v1` and uses `max_delivery_attempts = 5`.
The value `5` is the service's minimum supported maximum-delivery-attempt value
and the project's intended retry boundary, not a guarantee of exactly five
deliveries. Native Pub/Sub dead-letter forwarding is best effort: forwarding can
occur after fewer attempts, additional attempts may occur, and delivery-attempt
metadata is not a strict application transaction counter.

The dead-letter inspection subscription is attached to
`canonical-events-dead-letter-v1` for future operational inspection or
reprocessing. This runbook does not pull from it, acknowledge dead-letter
messages, replay messages, or implement a DLQ consumer.

If an existing local emulator subscription is missing the processing
subscription policy, points to an unexpected topic, or if the dead-letter
inspection subscription points to an unexpected topic, the local bootstrap may
delete and recreate that local subscription after the emulator-only safety guard
passes. Emulator state is ephemeral, so this reconciliation is
local-development-only.

The emulator can validate local topology creation. Managed Pub/Sub DLQ
forwarding and delivery-attempt behavior are service semantics and may not be
faithfully reproduced by the emulator in every installed version.

Future production Pub/Sub IaC must grant the managed Pub/Sub service agent the
permissions required for native dead-letter forwarding, including publishing to
the dead-letter topic and consuming or acknowledging from the source
subscription as required by Google Pub/Sub semantics. Do not implement or test
those production IAM resources from the local emulator runbook.

If the emulator is restarted, these resources must be bootstrapped again because emulator state is ephemeral.

## Safety Rules

- The emulator must be restarted after closing Terminal A.
- Emulator state is not persisted into the repository.
- No service-account key is required.
- Do not copy Application Default Credentials into the repository.
- Do not create real Pub/Sub topics or subscriptions from this runbook.
- Future real cloud Pub/Sub resources must be managed through OpenTofu/IaC.
