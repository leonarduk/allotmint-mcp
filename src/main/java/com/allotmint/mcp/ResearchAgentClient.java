package com.allotmint.mcp;

import com.allotmint.mcp.error.AllotMintApiException;
import com.allotmint.mcp.pojo.ResearchAnswer;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpRequest;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.util.StreamUtils;
import org.springframework.web.client.RestClient;

/**
 * HTTP client for the research agent sidecar - the Python process that runs the Pydantic AI agent
 * loop behind {@code allotmint_research}.
 *
 * <p>Spike #12 settled the JVM/Python interop question: the agent is a small local HTTP service
 * called over plain HTTP, the same pattern {@link AllotMintClient} already uses for the AllotMint
 * backend, rather than an in-JVM Python runtime. This class is deliberately the mirror image of
 * {@link AllotMintClient} so there is one interop story in this codebase, not two.
 */
@Slf4j
public class ResearchAgentClient {

  private final RestClient restClient;
  private final String baseUrl;

  public ResearchAgentClient(RestClient researchAgentRestClient, String baseUrl) {
    this.restClient = researchAgentRestClient;
    this.baseUrl = baseUrl;
  }

  public String baseUrl() {
    return baseUrl;
  }

  /**
   * Asks the agent one natural-language question.
   *
   * @param question the user's question, already validated as non-blank by the tool layer
   * @param owner optional owner slug scoping portfolio lookups; may be null
   * @param lookbackDays how far back retrieval should consider dated documents
   * @return the agent's grounded answer with its citations
   * @throws AllotMintApiException if the sidecar answers 4xx/5xx
   */
  public ResearchAnswer ask(String question, String owner, int lookbackDays) {
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("question", question);
    if (owner != null) {
      payload.put("owner", owner);
    }
    payload.put("lookback_days", lookbackDays);

    log.debug(
        "Asking research agent at {} (owner={}, lookback_days={})", baseUrl, owner, lookbackDays);

    ResearchAnswer answer =
        restClient
            .post()
            .uri("/research/ask")
            .contentType(MediaType.APPLICATION_JSON)
            .body(payload)
            .retrieve()
            .onStatus(HttpStatusCode::isError, this::mapError)
            .body(ResearchAnswer.class);

    if (answer == null) {
      throw new AllotMintApiException(502, "Research agent returned an empty response body");
    }
    return answer;
  }

  /**
   * Maps a 4xx/5xx from the sidecar into an {@link AllotMintApiException}, so the tool layer
   * reports a readable message instead of leaking a stack trace. Mirrors {@link AllotMintClient}'s
   * handler.
   */
  private void mapError(HttpRequest request, ClientHttpResponse response) throws IOException {
    String body = StreamUtils.copyToString(response.getBody(), StandardCharsets.UTF_8);
    throw new AllotMintApiException(
        response.getStatusCode().value(),
        "Research agent returned %d: %s".formatted(response.getStatusCode().value(), body));
  }
}
