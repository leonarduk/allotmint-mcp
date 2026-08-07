package com.allotmint.mcp.config;

import com.allotmint.mcp.ResearchAgentClient;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * Wires the {@link RestClient} used by {@link ResearchAgentClient} to talk to the research agent
 * sidecar (see {@code research-agent/}).
 *
 * <p>The timeout is its own property, and far longer than anything {@link AllotMintClientConfig}
 * needs: one {@code allotmint_research} call is an entire agent loop - retrieval, one or more LLM
 * turns, and the v0 tool calls the agent decides to chain - and against a local Ollama model that
 * routinely takes tens of seconds. The default read timeout is generous on purpose; a truncated
 * agent run is a worse failure than a slow one.
 *
 * <p>The beans are unconditional because they are inert until called; whether the {@code
 * allotmint_research} tool is registered at all is decided by {@code
 * allotmint.mcp.research.enabled} in {@link McpServerConfig} and {@link StdioMcpServerConfig}.
 */
@Configuration
class ResearchAgentClientConfig {

  @Bean
  RestClient researchAgentRestClient(
      @Value("${allotmint.research.base-url:http://localhost:8100}") String baseUrl,
      @Value("${allotmint.research.connect-timeout-seconds:5}") int connectTimeoutSeconds,
      @Value("${allotmint.research.read-timeout-seconds:180}") int readTimeoutSeconds) {
    SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
    requestFactory.setConnectTimeout(Duration.ofSeconds(connectTimeoutSeconds));
    requestFactory.setReadTimeout(Duration.ofSeconds(readTimeoutSeconds));

    return RestClient.builder().baseUrl(baseUrl).requestFactory(requestFactory).build();
  }

  @Bean
  ResearchAgentClient researchAgentClient(
      RestClient researchAgentRestClient,
      @Value("${allotmint.research.base-url:http://localhost:8100}") String baseUrl) {
    return new ResearchAgentClient(researchAgentRestClient, baseUrl);
  }
}
