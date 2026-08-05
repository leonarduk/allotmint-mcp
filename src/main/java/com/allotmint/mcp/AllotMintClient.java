package com.allotmint.mcp;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

/**
 * HTTP client for the AllotMint backend. Every MCP tool that talks to AllotMint should go through
 * here, rather than holding its own {@link WebClient}, so 4xx/5xx handling stays in one place (see
 * {@link AllotMintApiException}).
 */
@Component
class AllotMintClient {

  private static final Logger log = LoggerFactory.getLogger(AllotMintClient.class);

  private final WebClient webClient;
  private final String baseUrl;

  AllotMintClient(
      WebClient allotMintWebClient,
      @Value("${allotmint.api.base-url:http://localhost:8000}") String baseUrl) {
    this.webClient = allotMintWebClient;
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
   * <p>Any failure (4xx/5xx from {@link #mapError}, connection refused, timeout, ...) is reported
   * as {@code reachable=false} rather than thrown: a health check's job is to describe backend
   * state, not to fail the MCP tool call itself.
   */
  AllotMintHealthStatus health() {
    return webClient
        .get()
        .uri("/openapi.json")
        .retrieve()
        .onStatus(HttpStatusCode::isError, this::mapError)
        .bodyToMono(OpenApiDocument.class)
        .map(doc -> new AllotMintHealthStatus(true, doc.info().version(), baseUrl))
        .onErrorResume(this::unreachable)
        .block();
  }

  private Mono<AllotMintHealthStatus> unreachable(Throwable error) {
    log.warn("AllotMint backend at {} is unreachable: {}", baseUrl, error.getMessage());
    return Mono.just(new AllotMintHealthStatus(false, null, baseUrl));
  }

  /**
   * Maps a 4xx/5xx {@link ClientResponse} into an {@link AllotMintApiException} carrying a readable
   * message (status code + backend's error body if present), so it never leaks a raw stack trace
   * back through the MCP tool layer.
   */
  private Mono<? extends Throwable> mapError(ClientResponse response) {
    return response
        .bodyToMono(String.class)
        .defaultIfEmpty("")
        .map(
            body ->
                new AllotMintApiException(
                    response.statusCode().value(),
                    "AllotMint backend returned %d: %s"
                        .formatted(response.statusCode().value(), body)));
  }

  /** Minimal slice of an OpenAPI document - only the fields {@link #health()} needs. */
  private record OpenApiDocument(Info info) {
    private record Info(String version) {}
  }
}
