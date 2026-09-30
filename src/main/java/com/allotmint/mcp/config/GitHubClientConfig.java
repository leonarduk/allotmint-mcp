package com.allotmint.mcp.config;

import com.allotmint.mcp.client.GitHubClient;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClient;

import java.time.Duration;

/**
 * Wires the {@link RestClient} used by {@link GitHubClient}, which backs {@code
 * allotmint_create_issue}.
 *
 * <p>The beans are unconditional because they are inert until called; whether the tool is
 * registered at all is decided by {@code allotmint.mcp.issues.enabled} in {@link McpServerConfig}
 * and {@link StdioMcpServerConfig}. The token is attached as a default header here and is never
 * exposed by {@link GitHubClient}.
 */
@Configuration
class GitHubClientConfig {

  @Bean
  RestClient githubRestClient(
      @Value("${allotmint.mcp.github.api-url:https://api.github.com}") String apiUrl,
      @Value("${allotmint.mcp.github.token:}") String token,
      @Value("${allotmint.mcp.github.connect-timeout-seconds:5}") int connectTimeoutSeconds,
      @Value("${allotmint.mcp.github.read-timeout-seconds:15}") int readTimeoutSeconds) {
    SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
    requestFactory.setConnectTimeout(Duration.ofSeconds(connectTimeoutSeconds));
    requestFactory.setReadTimeout(Duration.ofSeconds(readTimeoutSeconds));

    RestClient.Builder builder =
        RestClient.builder()
            .baseUrl(apiUrl)
            .requestFactory(requestFactory)
            .defaultHeader(HttpHeaders.ACCEPT, "application/vnd.github+json")
            .defaultHeader("X-GitHub-Api-Version", "2022-11-28")
            .defaultHeader(HttpHeaders.USER_AGENT, "allotmint-mcp");
    if (StringUtils.hasText(token)) {
      builder.defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + token.trim());
    }
    return builder.build();
  }

  @Bean
  GitHubClient githubClient(
      @Qualifier("githubRestClient") RestClient githubRestClient,
      @Value("${allotmint.mcp.github.repo:}") String repo,
      @Value("${allotmint.mcp.github.token:}") String token) {
    return new GitHubClient(githubRestClient, repo, StringUtils.hasText(token));
  }
}
