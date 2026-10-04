# E-commerce quantitative pricing latency runbook

## Scope

Investigate `QuantRiskPricingLatencyHigh` from `quant-risk-service` in the `ecommerce-quant` namespace. The test alert represents a Java PricingEngine request for `CSI300-202607` using the VAR model that exceeds a two-second pricing SLO.

## Expected evidence

Query CLS events for the affected service within the active alert window. Correlate environment `test`, SOP identifier `ecommerce-quant-pricing-latency-sop`, trace ID, and the progression through `market_data_retry`, `pricing_executor_saturated`, `quote_calculation_timeout`, `upstream_market_data_unavailable`, and `pricing_engine_recovered`.

## Investigation

1. Verify service, severity, and alert start time.
2. Retrieve CLS events for the relevant window and group by trace_id and order_id.
3. Check whether market-data retries or executor saturation precede quote calculation timeout.
4. Treat upstream_market_data_unavailable as dependency evidence only when it appears in the same correlated window.
5. Record recovery evidence if pricing_engine_recovered exists, while assessing the impact of earlier timeouts.

## Response

Check market-data health and latency before changing risk calculations. If the pricing executor remains overloaded, consider queueing nonurgent requests under the owner's approved procedure. Escalate persistent post-recovery timeouts to the platform owner. Record the alert, correlation IDs, observed latency, and recovery evidence in the final report.

These are reviewed response options, not automatic authorization for remediation. Keep conclusions within retrieved runbook/tool evidence and exclude credentials, customer data, and trading details from logs and reports.
