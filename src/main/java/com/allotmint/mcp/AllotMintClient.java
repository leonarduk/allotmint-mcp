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
    } catch (RestClientException e) {
      log.warn("AllotMint backend at {} is unreachable: {}", baseUrl, e.getMessage());
      return new AllotMintHealthStatus(false, null, baseUrl);
    }
  }

  List<Map<String, Object>> searchInstruments(String query) {
    List<Map<String, Object>> matches =
        restClient
            .get()
            .uri(uriBuilder -> uriBuilder.path("/instrument/search").queryParam("q", query).build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(new ParameterizedTypeReference<>() {});
    return matches == null ? List.of() : matches;
  }

  Map<String, Object> instrumentDetail(String ticker) {
    Map<String, Object> detail =
        restClient
            .get()
            .uri(
                uriBuilder ->
                    uriBuilder
                        .path("/instrument")
                        .queryParam("ticker", ticker)
                        .queryParam("format", "json")
                        .build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(new ParameterizedTypeReference<>() {});
    return detail == null ? Map.of() : detail;
  }

  List<Map<String, Object>> latestQuotes(String ticker) {
    List<Map<String, Object>> quotes =
        restClient
            .get()
            .uri(uriBuilder -> uriBuilder.path("/api/quotes").queryParam("symbols", ticker).build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(new ParameterizedTypeReference<>() {});
    return quotes == null ? List.of() : quotes;
  }

  List<Map<String, Object>> instrumentNews(String ticker) {
    List<Map<String, Object>> news =
        restClient
            .get()
            .uri(uriBuilder -> uriBuilder.path("/news").queryParam("ticker", ticker).build())
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(new ParameterizedTypeReference<>() {});
    return news == null ? List.of() : news;
  }

  /**
   * Maps a 4xx/5xx response into an {@link AllotMintApiException} carrying a readable message
   * (status code + backend's error body if present), so it never leaks a raw stack trace back
   * through the MCP tool layer.
   */
  private void mapError(HttpRequest request, ClientHttpResponse response) throws IOException {
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
