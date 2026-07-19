package com.allotmint.mcp;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * HTTP client for the AllotMint backend. Every MCP tool that talks to AllotMint should
 * go through here, rather than holding its own {@link WebClient}, so 4xx/5xx handling
 * stays in one place (see {@link AllotMintApiException}).
 */
@Component
class AllotMintClient {

    private final WebClient webClient;
    private final String baseUrl;

    AllotMintClient(WebClient allotMintWebClient, @Value("${allotmint.api.base-url:http://localhost:8000}") String baseUrl) {
        this.webClient = allotMintWebClient;
        this.baseUrl = baseUrl;
    }

    /**
     * Calls the backend's health/OpenAPI endpoint and reports whether it's reachable.
     *
     * TODO(#4): implement this against the real AllotMint endpoint. Suggested shape:
     * <pre>
     *   return webClient.get()
     *           .uri("/health")   // confirm the real path - openapi.json? /health?
     *           .retrieve()
     *           .onStatus(HttpStatusCode::isError, response -> mapError(response))
     *           .bodyToMono(SomeHealthDto.class)
     *           .map(dto -> new AllotMintHealthStatus(true, dto.version(), baseUrl))
     *           .onErrorReturn(AllotMintApiException.class, ...)  // decide: rethrow or
     *                                                              // return reachable=false?
     *           .block();
     * </pre>
     * Key design question: should a 4xx/5xx from the backend make {@code reachable}
     * false, or should it propagate as an {@link AllotMintApiException} for the tool
     * layer to turn into an MCP error result? The issue's "Success looks like" section
     * implies the tool should still return a structured result, so leaning towards the
     * former for this one endpoint - but confirm before other tools copy the pattern.
     */
    AllotMintHealthStatus health() {
        throw new UnsupportedOperationException("TODO(#4): implement AllotMintClient.health()");
    }

    /**
     * TODO(#4): map a 4xx/5xx {@code ClientResponse} into an {@link AllotMintApiException}
     * with a readable message (status code + backend's error body if present), so it
     * never leaks a raw stack trace back through the MCP tool layer.
     */
    // private Mono<? extends Throwable> mapError(ClientResponse response) { ... }
}
