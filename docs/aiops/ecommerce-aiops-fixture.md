# Java e-commerce incident fixture

This fixture validates integration with actual CLS, Alertmanager, knowledge retrieval, and diagnostic evidence persistence. Scripts create ten synthetic scenarios. Each has one key log, one test-tagged active alert, one Markdown SOP, and a distinct 32-character trace ID.

Records correlate through `incident_id`, `service`, `alertname`, and `sop`; alert annotations and the runbook retain the same trace ID.

| Service | Alert | Synthetic fault |
| --- | --- | --- |
| `payment-service` | `PaymentGatewayTimeoutHigh` | Payment gateway TLS/read timeout leaves orders in PAYING |
| `inventory-service` | `InventoryReservationLockWaitHigh` | Replenishment transaction competes with reservation row locks |
| `order-service` | `OrderDatabasePoolExhausted` | Slow unpaged queries occupy the HikariCP pool |
| `cart-service` | `CartRedisLatencyHigh` | Hot promotion key and large deserialization delay Redis work |
| `api-gateway` | `GatewayCheckoutCircuitOpen` | Inventory errors open the checkout circuit breaker |
| `promotion-service` | `PromotionRuleEvaluationCpuHigh` | Combinatorial promotion rules saturate CPU |
| `order-event-consumer` | `OrderEventConsumerLagHigh` | New enum deserialization repeatedly fails on a poison message |
| `product-search-service` | `ProductSearchTimeoutHigh` | Wildcard query exhausts Elasticsearch search workers |
| `auth-service` | `AuthJwkRefreshFailureHigh` | Proxy DNS failure prevents JWK refresh after key rotation |
| `fulfillment-service` | `FulfillmentProviderUnavailable` | Provider 503 responses and unbounded retries amplify traffic |

Use [Real logs and alerts](../tutorials/real-log-and-alert.md) for prerequisites and the three explicit publishing/seeding commands. Open the diagnosis workspace after indexing completes and verify that tool evidence matches the alert's trace ID.

## Quantitative pricing fixture

The existing quant profile remains available. From the backend directory:

```bash
uv run python scripts/generate_and_upload_cls_logs.py --profile quant --count 16
uv run python scripts/publish_ecommerce_quant_alert.py --profile quant
uv run python scripts/seed_ecommerce_aiops_sop.py --profile quant
```

Its process is described in the [pricing latency runbook](ecommerce-quant-pricing-latency-sop.md). All input is test data; actual CLS upload and API writes still occur. Repeated SOP upload uses stable filenames and overwrite behavior. Do not interpret fixture counts as production incident counts or model-accuracy results.
