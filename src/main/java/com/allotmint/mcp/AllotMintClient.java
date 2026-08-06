package com.allotmint.mcp;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpRequest;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.util.StreamUtils;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * HTTP client for the AllotMint backend. Every MCP tool that talks to AllotMint should go through
 * here, rather than holding its own {@link RestClient}, so 4xx/5xx handling stays in one place (see
 * {@link AllotMintApiException}).
 */
@Component
class AllotMintClient {

  static final String AUTH_ERROR_MESSAGE =
      "Auth token missing or expired. Run 'allotmint-mcp login' or set"
          + " ALLOTMINT_MCP_AUTH_TOKEN.";
  private static final ParameterizedTypeReference<Map<String, Object>> OBJECT_MAP =
      new ParameterizedTypeReference<>() {};
  private static final ParameterizedTypeReference<List<Map<String, Object>>> LIST_RESPONSE =
      new ParameterizedTypeReference<>() {};

  private static final Logger log = LoggerFactory.getLogger(AllotMintClient.class);

  private final RestClient restClient;
  private final String baseUrl;

  AllotMintClient(
      RestClient allotMintRestClient,
      @Value("${allotmint.api.base-url:http://localhost:8000}") String baseUrl) {
    this.restClient = allotMintRestClient;
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
  AllotMintHealthStatus health() {
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

  Map<String, Object> portfolio(String owner) {
    return getObject("portfolio", owner);
  }

  List<Map<String, Object>> portfolioSectors(String owner) {
    List<Map<String, Object>> response =
        restClient
            .get()
            .uri(builder -> builder.pathSegment("portfolio", owner, "sectors").build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(LIST_RESPONSE);
    return response == null ? List.of() : response;
  }

  Map<String, Object> performance(String owner) {
    return getObject("performance", owner);
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
  Map<String, Object> marketOverview() {
    return getObjectMap("/market/overview");
  }

  /** Returns the standalone gainers and losers response from {@code /movers}. */
  Map<String, Object> marketMovers() {
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
  List<Map<String, Object>> instrumentSearch(String query) {
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
  Map<String, Object> instrumentDetail(String ticker) {
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
  List<Map<String, Object>> quotes(String ticker) {
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
  List<Map<String, Object>> news(String ticker) {
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
