package com.allotmint.mcp.client;

import com.allotmint.mcp.exception.AllotMintApiException;
import com.allotmint.mcp.model.AllotMintHealthStatus;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpRequest;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.util.StreamUtils;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/**
 * HTTP client for the AllotMint backend. Every MCP tool that talks to AllotMint should go through
 * here, rather than holding its own {@link RestClient}, so 4xx/5xx handling stays in one place (see
 * {@link AllotMintApiException}).
 */
@Slf4j
@Component
public class AllotMintClient {

  public static final String AUTH_ERROR_MESSAGE =
      "Auth token missing or expired. Run 'allotmint-mcp login' or set"
          + " ALLOTMINT_MCP_AUTH_TOKEN.";
  private static final ParameterizedTypeReference<Map<String, Object>> OBJECT_MAP =
      new ParameterizedTypeReference<>() {};
  private static final ParameterizedTypeReference<List<Map<String, Object>>> LIST_RESPONSE =
      new ParameterizedTypeReference<>() {};

  private final RestClient restClient;
  private final RestClient postRestClient;
  private final String baseUrl;

  public AllotMintClient(
      @Qualifier("allotMintRestClient") RestClient allotMintRestClient,
      @Qualifier("allotMintPostRestClient") RestClient allotMintPostRestClient,
      @Value("${allotmint.api.base-url:http://localhost:8000}") String baseUrl) {
    this.restClient = allotMintRestClient;
    this.postRestClient = allotMintPostRestClient;
    this.baseUrl = baseUrl;
  }

  /**
   * Reports whether the AllotMint backend is reachable, and its version if so.
   *
   * <p>Calls {@code /openapi.json} rather than {@code /health}: the backend's {@code /health}
   * endpoint (see {@code backend/app.py}) returns only {@code {status, env}}, no version, while
   * {@code /openapi.json} is unauthenticated (no route guard applies to it) and its {@code
   * info.version} field gives us both signals - reachable and version - in one round trip.
   *
   * <p>Any failure (4xx/5xx mapped to {@link AllotMintApiException} by the status handler below,
   * connection refused, timeout, ...) is reported as {@code reachable=false} rather than thrown: a
   * health check's job is to describe backend state, not to fail the MCP tool call itself.
   */
  public AllotMintHealthStatus health() {
    try {
      OpenApiDocument doc =
          restClient
              .get()
              .uri("/openapi.json")
              .retrieve()
              .onStatus(HttpStatusCode::isError, this::mapError)
              .body(OpenApiDocument.class);
      String version = doc == null ? null : doc.info().version();
      return new AllotMintHealthStatus(true, version, baseUrl);
    } catch (RestClientException | AllotMintApiException e) {
      log.warn("AllotMint backend at {} is unreachable: {}", baseUrl, e.getMessage());
      return new AllotMintHealthStatus(false, null, baseUrl);
    }
  }

  public Map<String, Object> portfolio(String owner) {
    return getObject("portfolio", owner);
  }

  public List<Map<String, Object>> portfolioSectors(String owner) {
    List<Map<String, Object>> response =
        restClient
            .get()
            .uri(builder -> builder.pathSegment("portfolio", owner, "sectors").build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(LIST_RESPONSE);
    return response == null ? List.of() : response;
  }

  /**
   * Returns sector weights as of {@code lookbackDays} ago via {@code GET
   * /portfolio/{owner}/sectors?lookback_days={days}}. Callers that catch {@link
   * AllotMintApiException} or {@link RestClientException} can treat a missing historical endpoint
   * as a no-op: the current snapshot is still valid, just without year-ago enrichment.
   */
  public List<Map<String, Object>> portfolioSectors(String owner, int lookbackDays) {
    List<Map<String, Object>> response =
        restClient
            .get()
            .uri(
                builder ->
                    builder
                        .pathSegment("portfolio", owner, "sectors")
                        .queryParam("lookback_days", lookbackDays)
                        .build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(LIST_RESPONSE);
    return response == null ? List.of() : response;
  }

  public Map<String, Object> performance(String owner) {
    return getObject("performance", owner);
  }

  /** Returns a read-only diff between stored holdings and broker CSV positions. */
  public Map<String, Object> reconcileHoldings(
      String owner, String accountType, String csvContent) {
    return postObject(
        "/holdings/reconcile",
        Map.of("owner", owner, "account_type", accountType, "csv_content", csvContent));
  }

  /** Applies a backend-issued reconciliation after the caller has reviewed its diff. */
  public Map<String, Object> applyReconciliation(String reconciliationId) {
    return postObject("/holdings/reconcile/apply", Map.of("reconciliation_id", reconciliationId));
  }

  private Map<String, Object> postObject(String path, Map<String, Object> request) {
    Map<String, Object> response =
        postRestClient
            .post()
            .uri(path)
            .contentType(MediaType.APPLICATION_JSON)
            .body(request)
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(OBJECT_MAP);
    return response == null ? Map.of() : response;
  }

  private Map<String, Object> getObject(String endpoint, String owner) {
    Map<String, Object> response =
        restClient
            .get()
            .uri(builder -> builder.pathSegment(endpoint, owner).build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(OBJECT_MAP);
    return response == null ? Map.of() : response;
  }

  /** Returns the combined market overview from {@code /market/overview}. */
  public Map<String, Object> marketOverview() {
    return getObjectMap("/market/overview");
  }

  /** Returns the standalone gainers and losers response from {@code /movers}. */
  public Map<String, Object> marketMovers() {
    return getObjectMap("/movers");
  }

  private Map<String, Object> getObjectMap(String path) {
    Map<String, Object> body =
        restClient
            .get()
            .uri(path)
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(OBJECT_MAP);
    return body == null ? Map.of() : body;
  }

  /**
   * Matches instruments by ticker or name via {@code GET /instrument/search?q=...}. Returns a
   * (possibly empty) list of {@code {ticker, name, sector, region}} maps.
   */
  public List<Map<String, Object>> instrumentSearch(String query) {
    List<Map<String, Object>> response =
        restClient
            .get()
            .uri(
                builder ->
                    builder.pathSegment("instrument", "search").queryParam("q", query).build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(LIST_RESPONSE);
    return response == null ? List.of() : response;
  }

  /**
   * Returns price history and portfolio positions for one ticker via {@code GET
   * /instrument?ticker=...&format=json}. Despite living at the router root, this is a per-ticker
   * detail endpoint, not portfolio-scoped.
   */
  public Map<String, Object> instrumentDetail(String ticker) {
    Map<String, Object> response =
        restClient
            .get()
            .uri(
                builder ->
                    builder
                        .pathSegment("instrument")
                        .queryParam("ticker", ticker)
                        .queryParam("format", "json")
                        .build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(OBJECT_MAP);
    return response == null ? Map.of() : response;
  }

  /**
   * Returns the latest quote for one ticker via {@code GET /api/quotes?symbols=...}. The backend
   * endpoint accepts a comma-separated list, but this client only ever requests a single symbol.
   */
  public List<Map<String, Object>> quotes(String ticker) {
    List<Map<String, Object>> response =
        restClient
            .get()
            .uri(
                builder ->
                    builder.pathSegment("api", "quotes").queryParam("symbols", ticker).build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(LIST_RESPONSE);
    return response == null ? List.of() : response;
  }

  /**
   * Returns recent headlines for one ticker via {@code GET /news?ticker=...}, most recent first.
   */
  public List<Map<String, Object>> news(String ticker) {
    List<Map<String, Object>> response =
        restClient
            .get()
            .uri(builder -> builder.pathSegment("news").queryParam("ticker", ticker).build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(LIST_RESPONSE);
    return response == null ? List.of() : response;
  }

  /**
   * Returns the aggregated data-quality issue list via {@code GET /data-quality/issues}. The
   * backend aggregates holdings across all owners server-side, so no owner argument is required.
   * Optional filters ({@code type}, {@code severity}, {@code owner}, {@code account}, {@code
   * ticker}) are passed through as query parameters when present.
   */
  public Map<String, Object> dataQualityIssues(Map<String, String> filters) {
    Map<String, Object> response =
        restClient
            .get()
            .uri(
                builder -> {
                  builder.pathSegment("data-quality", "issues");
                  // Skip null/blank values so a direct caller can't emit empty query
                  // parameters like ?type=; the tool layer already filters these.
                  filters.forEach(
                      (name, value) -> {
                        if (value != null && !value.isBlank()) {
                          builder.queryParam(name, value);
                        }
                      });
                  return builder.build();
                })
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(OBJECT_MAP);
    return response == null ? Map.of() : response;
  }

  /** Returns per-series quality metrics via {@code GET /data-quality/timeseries}. */
  public Map<String, Object> dataQualitySeries() {
    return getObjectMap("/data-quality/timeseries");
  }

  /**
   * Returns one issue's suggested fix via {@code GET /data-quality/issues/{issue_id}/preview}.
   * Read-only; never mutates state.
   */
  public Map<String, Object> dataQualityPreview(String issueId) {
    Map<String, Object> response =
        restClient
            .get()
            .uri(
                builder ->
                    builder.pathSegment("data-quality", "issues", issueId, "preview").build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(OBJECT_MAP);
    return response == null ? Map.of() : response;
  }

  /**
   * Applies a previewed fix via {@code POST /data-quality/issues/{issue_id}/fix}. Refuses to call
   * the backend unless {@code confirm} is true - writes must never be silent.
   */
  public Map<String, Object> dataQualityFix(String issueId, boolean confirm) {
    requireWriteConfirmation("fix", confirm);
    return postNoBody("data-quality", "issues", issueId, "fix");
  }

  /**
   * Dedupes a cached series via {@code POST /data-quality/series/{ticker}/{exchange}/dedupe}.
   * Refuses to call the backend unless {@code confirm} is true.
   */
  public Map<String, Object> dataQualityDedupe(String ticker, String exchange, boolean confirm) {
    requireWriteConfirmation("dedupe", confirm);
    return postNoBody("data-quality", "series", ticker, exchange, "dedupe");
  }

  /** Returns the append-only fix history via {@code GET /data-quality/audit}. */
  public Map<String, Object> dataQualityAudit() {
    return getObjectMap("/data-quality/audit");
  }

  /**
   * Reverts one audited action via {@code POST /data-quality/audit/{entry_id}/undo}. Refuses to
   * call the backend unless {@code confirm} is true.
   */
  public Map<String, Object> dataQualityUndo(String auditId, boolean confirm) {
    requireWriteConfirmation("undo", confirm);
    return postNoBody("data-quality", "audit", auditId, "undo");
  }

  private Map<String, Object> postNoBody(String... pathSegments) {
    Map<String, Object> response =
        postRestClient
            .post()
            .uri(builder -> builder.pathSegment(pathSegments).build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(OBJECT_MAP);
    return response == null ? Map.of() : response;
  }

  private static void requireWriteConfirmation(String action, boolean confirm) {
    if (!confirm) {
      throw new IllegalArgumentException(
          "AllotMint write action '"
              + action
              + "' requires confirm=true; refusing to mutate state.");
    }
  }

  /**
   * Maps a 4xx/5xx response into an {@link AllotMintApiException} carrying a readable message
   * (status code + backend's error body if present), so it never leaks a raw stack trace back
   * through the MCP tool layer.
   */
  private void mapError(HttpRequest request, ClientHttpResponse response) throws IOException {
    if (response.getStatusCode().value() == 401) {
      throw new AllotMintApiException(401, AUTH_ERROR_MESSAGE);
    }

    String body = StreamUtils.copyToString(response.getBody(), StandardCharsets.UTF_8);
    throw new AllotMintApiException(
        response.getStatusCode().value(),
        "AllotMint backend returned %d: %s".formatted(response.getStatusCode().value(), body));
  }

  /** Minimal slice of an OpenAPI document - only the fields {@link #health()} needs. */
  private record OpenApiDocument(Info info) {
    private record Info(String version) {}
  }
}
