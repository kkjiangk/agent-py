"""Safe, explicit fixture payloads for the e-commerce quant AIOps demonstration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

QUANT_ALERT_NAME = "QuantRiskPricingLatencyHigh"
QUANT_SERVICE = "quant-risk-service"
QUANT_SOP_ID = "ecommerce-quant-pricing-latency-sop"


@dataclass(frozen=True, slots=True)
class JavaEcommerceIncident:
    """One correlated Java e-commerce log, alert, and SOP scenario."""

    incident_id: str
    trace_id: str
    service: str
    logger: str
    alert_name: str
    sop_id: str
    severity: str
    symptom: str
    root_cause: str
    exception: str
    dependency: str
    metric_name: str
    metric_value: str
    threshold: str
    investigation_steps: tuple[str, ...]
    recovery_steps: tuple[str, ...]
    verification: str


@dataclass(frozen=True, slots=True)
class JavaEcommerceSopDocument:
    """Generated SOP document ready for upload and indexing."""

    incident_id: str
    sop_id: str
    filename: str
    content: str


JAVA_ECOMMERCE_INCIDENTS: tuple[JavaEcommerceIncident, ...] = (
    JavaEcommerceIncident(
        incident_id="java-ecom-payment-gateway-timeout",
        trace_id="4bf92f3577b34da6a3ce929d0e0e0001",
        service="payment-service",
        logger="com.shop.payment.gateway.PaymentGatewayClient",
        alert_name="PaymentGatewayTimeoutHigh",
        sop_id="java-ecom-payment-gateway-timeout-sop",
        severity="critical",
        symptom="支付确认接口连续超时，结算请求停留在 PAYING 状态。",
        root_cause="第三方支付网关 TLS 握手延迟升高，触发 3 秒读取超时。",
        exception="java.net.SocketTimeoutException",
        dependency="external-payment-gateway",
        metric_name="payment_gateway_timeout_rate",
        metric_value="18.4%",
        threshold="> 5% for 5m",
        investigation_steps=(
            "按 trace_id 查询 PaymentGatewayClient 超时日志并确认目标网关域名。",
            "检查网关 p95 延迟、TLS 握手时间和 payment-service 连接池等待时间。",
            "核对相同订单是否已取得网关流水号，避免重复扣款。",
        ),
        recovery_steps=(
            "切换到已配置的备用支付通道并保持幂等键不变。",
            "对未取得网关流水号的 PAYING 订单执行有界重试。",
        ),
        verification="连续 10 分钟超时率低于 1%，且无重复支付流水。",
    ),
    JavaEcommerceIncident(
        incident_id="java-ecom-inventory-lock-wait",
        trace_id="4bf92f3577b34da6a3ce929d0e0e0002",
        service="inventory-service",
        logger="com.shop.inventory.repository.StockReservationRepository",
        alert_name="InventoryReservationLockWaitHigh",
        sop_id="java-ecom-inventory-lock-wait-sop",
        severity="critical",
        symptom="热门 SKU 库存预占超时，下单接口返回库存繁忙。",
        root_cause="批量补库存事务持锁时间过长，与预占库存更新发生行锁竞争。",
        exception="org.springframework.dao.CannotAcquireLockException",
        dependency="inventory-mysql",
        metric_name="inventory_lock_wait_seconds_p95",
        metric_value="8.7s",
        threshold="> 2s for 5m",
        investigation_steps=(
            "按 trace_id 和 SKU 查询库存预占失败日志。",
            "检查 MySQL innodb_trx、锁等待链和持锁 SQL。",
            "确认补库存批任务是否在故障窗口执行大事务。",
        ),
        recovery_steps=(
            "终止确认无业务提交风险的长事务并暂停补库存批任务。",
            "将补库存更新拆为小批次后恢复，预占请求继续使用版本号 CAS。",
        ),
        verification="锁等待 p95 低于 300ms，库存预占成功率恢复到 99.9%。",
    ),
    JavaEcommerceIncident(
        incident_id="java-ecom-order-db-pool-exhausted",
        trace_id="4bf92f3577b34da6a3ce929d0e0e0003",
        service="order-service",
        logger="com.shop.order.application.OrderApplicationService",
        alert_name="OrderDatabasePoolExhausted",
        sop_id="java-ecom-order-db-pool-exhausted-sop",
        severity="critical",
        symptom="订单创建请求排队并大量返回 503，HikariCP 无可用连接。",
        root_cause="订单详情查询遗漏分页导致慢 SQL，占满 40 个数据库连接。",
        exception="java.sql.SQLTransientConnectionException",
        dependency="order-mysql",
        metric_name="hikaricp_pending_connections",
        metric_value="126",
        threshold="> 20 for 3m",
        investigation_steps=(
            "按 trace_id 确认连接获取超时发生在订单创建事务。",
            "检查 Hikari active/pending、MySQL processlist 和慢查询日志。",
            "定位无分页订单详情 SQL 的调用版本和发布批次。",
        ),
        recovery_steps=(
            "回滚引入无分页查询的版本并终止对应只读慢查询。",
            "连接池恢复后逐步放开网关限流，不直接扩大连接池掩盖问题。",
        ),
        verification="pending connections 归零，订单创建 p95 小于 500ms。",
    ),
    JavaEcommerceIncident(
        incident_id="java-ecom-cart-redis-latency",
        trace_id="4bf92f3577b34da6a3ce929d0e0e0004",
        service="cart-service",
        logger="com.shop.cart.infrastructure.RedisCartRepository",
        alert_name="CartRedisLatencyHigh",
        sop_id="java-ecom-cart-redis-latency-sop",
        severity="warning",
        symptom="购物车读取延迟升高，部分用户看到购物车加载失败。",
        root_cause="Redis 热 key `cart:promotion:index` 执行大对象反序列化并阻塞事件循环。",
        exception="io.lettuce.core.RedisCommandTimeoutException",
        dependency="cart-redis",
        metric_name="redis_command_latency_p99",
        metric_value="1640ms",
        threshold="> 500ms for 5m",
        investigation_steps=(
            "按 trace_id 查询 RedisCartRepository 命令超时及 key 前缀。",
            "检查 Redis SLOWLOG、hotkeys、内存碎片和 blocked_clients。",
            "确认 promotion index value 大小及最近缓存结构变更。",
        ),
        recovery_steps=(
            "删除可重建的 promotion index 热 key 并启用分片 key 写入。",
            "临时关闭非必要促销装饰，保留基础购物车读写。",
        ),
        verification="Redis p99 小于 50ms，购物车读取错误率低于 0.1%。",
    ),
    JavaEcommerceIncident(
        incident_id="java-ecom-gateway-circuit-open",
        trace_id="4bf92f3577b34da6a3ce929d0e0e0005",
        service="api-gateway",
        logger="com.shop.gateway.filter.CheckoutCircuitBreakerFilter",
        alert_name="GatewayCheckoutCircuitOpen",
        sop_id="java-ecom-gateway-circuit-open-sop",
        severity="critical",
        symptom="结算路由熔断器打开，网关快速失败并返回 503。",
        root_cause="inventory-service 错误率持续超过熔断阈值，半开探测仍失败。",
        exception="io.github.resilience4j.circuitbreaker.CallNotPermittedException",
        dependency="inventory-service",
        metric_name="checkout_circuit_open_state",
        metric_value="1",
        threshold="= 1 for 2m",
        investigation_steps=(
            "按 trace_id 确认被拒绝路由和熔断器 checkoutInventory 状态。",
            "检查 inventory-service 健康、错误率和最近发布。",
            "核对熔断窗口、最小调用数和半开探测配置是否被误改。",
        ),
        recovery_steps=(
            "先恢复 inventory-service，再允许熔断器进入半开探测。",
            "仅在探测成功率达标后关闭熔断，不手工强制绕过故障依赖。",
        ),
        verification="半开探测连续成功，checkout 5xx 低于 0.5%。",
    ),
    JavaEcommerceIncident(
        incident_id="java-ecom-promotion-cpu-saturation",
        trace_id="4bf92f3577b34da6a3ce929d0e0e0006",
        service="promotion-service",
        logger="com.shop.promotion.engine.PromotionRuleEngine",
        alert_name="PromotionRuleEvaluationCpuHigh",
        sop_id="java-ecom-promotion-cpu-saturation-sop",
        severity="critical",
        symptom="促销试算延迟超过 2 秒，实例 CPU 持续接近满载。",
        root_cause="新上架的组合促销规则产生指数级候选组合计算。",
        exception="java.util.concurrent.TimeoutException",
        dependency="promotion-rule-engine",
        metric_name="process_cpu_usage",
        metric_value="96%",
        threshold="> 85% for 10m",
        investigation_steps=(
            "按 trace_id 定位超时规则集和活动 ID。",
            "采集 Java Flight Recorder，确认 CPU 集中在组合枚举函数。",
            "比较故障前后规则数量、互斥条件和最大组合深度。",
        ),
        recovery_steps=(
            "下线异常组合促销规则并清理规则缓存。",
            "为组合枚举增加候选上限和计算超时，随后滚动发布。",
        ),
        verification="CPU 低于 60%，促销试算 p95 小于 300ms。",
    ),
    JavaEcommerceIncident(
        incident_id="java-ecom-order-kafka-lag",
        trace_id="4bf92f3577b34da6a3ce929d0e0e0007",
        service="order-event-consumer",
        logger="com.shop.order.event.OrderCreatedConsumer",
        alert_name="OrderEventConsumerLagHigh",
        sop_id="java-ecom-order-kafka-lag-sop",
        severity="warning",
        symptom="订单创建事件积压，积分和履约状态更新明显延迟。",
        root_cause="消费者反序列化遇到新增枚举值后持续重试同一 poison message。",
        exception="org.springframework.kafka.listener.ListenerExecutionFailedException",
        dependency="order-events-kafka",
        metric_name="kafka_consumer_group_lag",
        metric_value="48231",
        threshold="> 10000 for 10m",
        investigation_steps=(
            "按 trace_id 查询失败 offset、partition 和 schemaVersion。",
            "检查 consumer group lag 与单 partition 重试速率。",
            "比对生产者 schema 与消费者 OrderStatus 枚举版本。",
        ),
        recovery_steps=(
            "发布兼容新增枚举的消费者并将 poison message 写入 DLT。",
            "从失败 offset 恢复消费并限制追赶流量，避免压垮下游。",
        ),
        verification="lag 持续下降至 1000 以下，DLT 无新增同类消息。",
    ),
    JavaEcommerceIncident(
        incident_id="java-ecom-search-es-timeout",
        trace_id="4bf92f3577b34da6a3ce929d0e0e0008",
        service="product-search-service",
        logger="com.shop.search.repository.ElasticsearchProductRepository",
        alert_name="ProductSearchTimeoutHigh",
        sop_id="java-ecom-search-es-timeout-sop",
        severity="warning",
        symptom="商品搜索请求超时，关键词搜索返回空结果或降级结果。",
        root_cause="未受限的 wildcard 查询扫描高基数字段，耗尽 Elasticsearch search 线程池。",
        exception="co.elastic.clients.transport.TransportException",
        dependency="product-elasticsearch",
        metric_name="elasticsearch_search_rejected_rate",
        metric_value="12.7%",
        threshold="> 2% for 5m",
        investigation_steps=(
            "按 trace_id 获取慢查询 DSL 和索引名称。",
            "检查 search thread_pool rejected、hot threads 和节点 heap。",
            "确认 wildcard 查询来源及是否绕过查询长度限制。",
        ),
        recovery_steps=(
            "禁用高成本 wildcard 条件并切换到 keyword/prefix 查询。",
            "取消仍在执行的异常任务，待线程池恢复后逐步解除降级。",
        ),
        verification="search rejected 归零，搜索 p95 小于 400ms。",
    ),
    JavaEcommerceIncident(
        incident_id="java-ecom-auth-jwk-refresh",
        trace_id="4bf92f3577b34da6a3ce929d0e0e0009",
        service="auth-service",
        logger="com.shop.auth.jwt.JwkKeyProvider",
        alert_name="AuthJwkRefreshFailureHigh",
        sop_id="java-ecom-auth-jwk-refresh-sop",
        severity="critical",
        symptom="JWT 验签失败率升高，新登录和受保护 API 大量返回 401。",
        root_cause="身份提供方轮换签名 key 后，JWK 缓存因代理 DNS 故障无法刷新。",
        exception="com.nimbusds.jose.RemoteKeySourceException",
        dependency="identity-provider-jwks",
        metric_name="jwt_unknown_kid_rate",
        metric_value="21.3%",
        threshold="> 1% for 3m",
        investigation_steps=(
            "按 trace_id 确认失败 token 的 kid 与当前缓存 key 集不匹配。",
            "从 auth-service 检查 JWK URL DNS、TLS 和代理连通性。",
            "核对身份提供方 key 轮换时间与缓存最后刷新时间。",
        ),
        recovery_steps=(
            "修复代理 DNS 后主动刷新 JWK 缓存，不关闭签名校验。",
            "保留旧 key 的重叠验证窗口并滚动重启异常实例。",
        ),
        verification="unknown kid 率归零，登录成功率恢复且验签仍开启。",
    ),
    JavaEcommerceIncident(
        incident_id="java-ecom-fulfillment-provider-503",
        trace_id="4bf92f3577b34da6a3ce929d0e0e000a",
        service="fulfillment-service",
        logger="com.shop.fulfillment.client.CarrierBookingClient",
        alert_name="FulfillmentProviderUnavailable",
        sop_id="java-ecom-fulfillment-provider-503-sop",
        severity="warning",
        symptom="运单创建持续失败，已支付订单停留在待分配物流状态。",
        root_cause="主物流供应商维护期间返回 503，客户端无退避重试造成请求放大。",
        exception="org.springframework.web.client.HttpServerErrorException$ServiceUnavailable",
        dependency="primary-carrier-api",
        metric_name="carrier_booking_503_rate",
        metric_value="34.6%",
        threshold="> 5% for 5m",
        investigation_steps=(
            "按 trace_id 查询供应商响应码、重试次数和订单幂等键。",
            "检查供应商状态页及备用物流通道健康状态。",
            "确认重试策略是否缺少指数退避和 Retry-After 支持。",
        ),
        recovery_steps=(
            "开启备用物流供应商并暂停对主供应商的即时重试。",
            "按订单幂等键重放待分配任务，加入指数退避与抖动。",
        ),
        verification="运单创建成功率高于 99%，待分配队列持续清空。",
    ),
)


def build_quant_alert_payload(now: datetime) -> list[dict[str, object]]:
    """Build one Alertmanager v2 payload correlated with the CLS fixture."""
    started_at = _as_utc(now)
    return [
        {
            "labels": {
                "alertname": QUANT_ALERT_NAME,
                "service": QUANT_SERVICE,
                "environment": "test",
                "namespace": "ecommerce-quant",
                "severity": "critical",
                "team": "quant-platform",
            },
            "annotations": {
                "summary": "Quant risk pricing latency exceeded the 2s SLO.",
                "description": (
                    "PricingEngine quote calculation timed out while requesting market data."
                ),
                "sop": QUANT_SOP_ID,
            },
            "startsAt": _iso8601(started_at),
            "endsAt": _iso8601(started_at + timedelta(hours=1)),
            "generatorURL": "http://localhost:9090/graph?g0.expr=quant_pricing_latency",
        }
    ]


def generate_quant_incident_logs(*, count: int, now: datetime) -> list[dict[str, str]]:
    """Generate a bounded Java quant-service incident sequence without sensitive data."""
    scenarios = (
        ("INFO", "quote_request_received", "Received valuation request", "85", "none"),
        ("WARN", "market_data_retry", "Market data request retry scheduled", "680", "none"),
        (
            "WARN",
            "pricing_executor_saturated",
            "Pricing executor queue above threshold",
            "1120",
            "none",
        ),
        (
            "ERROR",
            "quote_calculation_timeout",
            "Quote calculation timed out",
            "2450",
            "TimeoutException",
        ),
        (
            "ERROR",
            "upstream_market_data_unavailable",
            "Market data dependency returned 503",
            "2310",
            "UpstreamUnavailable",
        ),
        (
            "WARN",
            "risk_cache_memory_pressure",
            "Risk cache memory pressure detected",
            "1900",
            "none",
        ),
        (
            "INFO",
            "quote_retry_succeeded",
            "Retry completed with degraded market data",
            "810",
            "none",
        ),
        (
            "INFO",
            "pricing_engine_recovered",
            "Pricing executor recovered below threshold",
            "145",
            "none",
        ),
    )
    timestamp = _iso8601(_as_utc(now))
    logs: list[dict[str, str]] = []
    for index in range(count):
        level, event, message, latency_ms, exception = scenarios[index % len(scenarios)]
        sequence = f"{index + 1:04d}"
        logs.append(
            {
                "timestamp": timestamp,
                "level": level,
                "service": QUANT_SERVICE,
                "environment": "test",
                "logger": "com.ecommerce.quant.risk.PricingEngine",
                "thread": "http-nio-8080-exec-12",
                "event": event,
                "message": message,
                "request_id": f"quant-request-{sequence}",
                "trace_id": f"quant-trace-{sequence}",
                "order_id": f"ORDER-Q-{sequence}",
                "instrument_id": "CSI300-202607",
                "risk_model": "VAR",
                "upstream": "market-data-service",
                "latency_ms": latency_ms,
                "exception": exception,
                "sop": QUANT_SOP_ID,
            }
        )
    return logs


def generate_java_ecommerce_incident_logs(*, now: datetime) -> list[dict[str, str]]:
    """Generate ten correlated Java microservice incident logs."""
    started_at = _as_utc(now)
    logs: list[dict[str, str]] = []
    for index, incident in enumerate(JAVA_ECOMMERCE_INCIDENTS):
        timestamp = _iso8601(started_at + timedelta(seconds=index * 7))
        logs.append(
            {
                "timestamp": timestamp,
                "level": "ERROR" if incident.severity == "critical" else "WARN",
                "service": incident.service,
                "host": f"{incident.service}-01",
                "environment": "test",
                "fixture": "java-ecommerce",
                "logger": incident.logger,
                "thread": f"http-nio-8080-exec-{index + 1}",
                "event": incident.incident_id,
                "incident_id": incident.incident_id,
                "alertname": incident.alert_name,
                "message": incident.symptom,
                "root_cause_hint": incident.root_cause,
                "request_id": f"fixture-request-{index + 1:02d}",
                "trace_id": incident.trace_id,
                "span_id": f"7a3f9b2c1d0e{index + 1:04x}",
                "exception": incident.exception,
                "dependency": incident.dependency,
                "metric_name": incident.metric_name,
                "metric_value": incident.metric_value,
                "threshold": incident.threshold,
                "sop": incident.sop_id,
            }
        )
    return logs


def build_java_ecommerce_alert_payload(now: datetime) -> list[dict[str, object]]:
    """Build ten Alertmanager alerts correlated with Java fixture logs and SOPs."""
    started_at = _as_utc(now)
    alerts: list[dict[str, object]] = []
    for index, incident in enumerate(JAVA_ECOMMERCE_INCIDENTS):
        alert_started_at = started_at + timedelta(seconds=index * 7)
        alerts.append(
            {
                "labels": {
                    "alertname": incident.alert_name,
                    "service": incident.service,
                    "environment": "test",
                    "namespace": "java-ecommerce",
                    "severity": incident.severity,
                    "team": "ecommerce-platform",
                    "fixture": "java-ecommerce",
                    "incident_id": incident.incident_id,
                },
                "annotations": {
                    "summary": incident.symptom,
                    "description": (
                        f"{incident.metric_name}={incident.metric_value}; "
                        f"threshold {incident.threshold}. {incident.root_cause}"
                    ),
                    "trace_id": incident.trace_id,
                    "sop": incident.sop_id,
                    "dependency": incident.dependency,
                },
                "startsAt": _iso8601(alert_started_at),
                "endsAt": _iso8601(alert_started_at + timedelta(hours=4)),
                "generatorURL": (
                    "http://localhost:9090/graph?g0.expr="
                    f"{incident.metric_name}"
                ),
            }
        )
    return alerts


def build_java_ecommerce_sop_documents() -> list[JavaEcommerceSopDocument]:
    """Render ten evidence-oriented Chinese SOP documents."""
    return [
        JavaEcommerceSopDocument(
            incident_id=incident.incident_id,
            sop_id=incident.sop_id,
            filename=f"{incident.sop_id}.md",
            content=_render_java_ecommerce_sop(incident),
        )
        for incident in JAVA_ECOMMERCE_INCIDENTS
    ]


def _render_java_ecommerce_sop(incident: JavaEcommerceIncident) -> str:
    investigation = "\n".join(
        f"{index}. {step}" for index, step in enumerate(incident.investigation_steps, start=1)
    )
    recovery = "\n".join(
        f"{index}. {step}" for index, step in enumerate(incident.recovery_steps, start=1)
    )
    return f"""# {incident.alert_name} 故障处理 SOP

## 适用范围

- **SOP ID**: `{incident.sop_id}`
- **Incident ID**: `{incident.incident_id}`
- **Java 服务**: `{incident.service}`
- **依赖组件**: `{incident.dependency}`
- **告警级别**: `{incident.severity}`

## 告警触发依据

- **指标**: `{incident.metric_name}`
- **当前观测值**: `{incident.metric_value}`
- **触发阈值**: `{incident.threshold}`
- **用户可见症状**: {incident.symptom}

## 日志证据定位

在 CLS 中使用以下条件查询本次 fixture：

```text
trace_id:{incident.trace_id} AND service:{incident.service}
```

预期命中 logger `{incident.logger}`，异常类型 `{incident.exception}`。trace ID 仅用于
定位本场景证据，不应将其他 trace 的日志作为结论依据。

## 已知根因假设

{incident.root_cause}

该根因必须由上述日志、依赖健康状态和指标共同验证；未获得证据时不得直接判定。

## 排查步骤

{investigation}

## 恢复步骤

{recovery}

## 恢复验证

{incident.verification}

## 回滚与风险控制

- 任何重试必须保留业务幂等键，避免重复支付、重复扣减库存或重复创建运单。
- 若恢复动作未改善指标，应立即停止扩大变更并回滚到故障前版本或配置。
- 报告中必须列出实际查询到的 trace、指标和工具失败项，不得补写不存在的证据。
"""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


def _iso8601(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
