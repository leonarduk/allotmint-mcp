package com.allotmint.mcp.client;

import com.allotmint.mcp.exception.AllotMintApiException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpRequest;
import org.springframework.http.MediaType;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.util.StreamUtils;
import org.springframework.web.client.RestClient;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Minimal GitHub REST client, used only by {@code allotmint_create_issue}. The target repository is
 * fixed at construction from configuration, never taken from a tool argument, so a model cannot
 * redirect issues to another repository.
 *
 * <p>The bearer token lives only in the {@link RestClient}'s default headers (see {@code
 * GitHubClientConfig}); nothing in this class logs it or includes it in an exception message.
 */
@Slf4j
public class GitHubClient {

  private static final Pattern REPO = Pattern.compile("[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+");
  private static final int MAX_ERROR_BODY_CHARS = 500;
  private static final ParameterizedTypeReference<Map<String, Object>> OBJECT_MAP =
      new ParameterizedTypeReference<>() {};

  private final RestClient restClient;
  private final String repo;
  private final boolean tokenConfigured;

  public GitHubClient(RestClient githubRestClient, String repo, boolean tokenConfigured) {
    this.restClient = githubRestClient;
    this.repo = repo == null ? "" : repo.trim();
    this.tokenConfigured = tokenConfigured;
  }

  /** The configured {@code owner/repo}, possibly blank or malformed; see {@link #validRepo()}. */
  public String repo() {
    return repo;
  }

  /**
   * True when the repository is {@code owner/repo} with both segments made of GitHub-legal
   * characters. Segments consisting only of dots ({@code .}, {@code ..}) are rejected: they would
   * be resolved as path traversal in the request URL rather than as names.
   */
  public boolean validRepo() {
    if (!REPO.matcher(repo).matches()) {
      return false;
    }
    for (String segment : repo.split("/", 2)) {
      if (segment.chars().allMatch(c -> c == '.')) {
        return false;
      }
    }
    return true;
  }

  public boolean tokenConfigured() {
    return tokenConfigured;
  }

  /**
   * Creates an issue in the configured repository via {@code POST /repos/{owner}/{repo}/issues}.
   *
   * @return the GitHub response (notably {@code number} and {@code html_url})
   * @throws AllotMintApiException if GitHub answers 4xx/5xx
   * @throws IllegalStateException if the repository or token is not configured
   */
  public Map<String, Object> createIssue(String title, String body, List<String> labels) {
    if (!validRepo()) {
      throw new IllegalStateException("GitHub repository is not configured as owner/repo");
    }
    if (!tokenConfigured) {
      throw new IllegalStateException("GitHub token is not configured");
    }

    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("title", title);
    if (body != null) {
      payload.put("body", body);
    }
    if (labels != null && !labels.isEmpty()) {
      payload.put("labels", labels);
    }

    String[] parts = repo.split("/", 2);
    Map<String, Object> response =
        restClient
            .post()
            .uri("/repos/{owner}/{repo}/issues", parts[0], parts[1])
            .contentType(MediaType.APPLICATION_JSON)
            .body(payload)
            .retrieve()
            .onStatus(status -> status.isError(), this::mapError)
            .body(OBJECT_MAP);
    return response == null ? Map.of() : response;
  }

  private void mapError(HttpRequest request, ClientHttpResponse response) throws IOException {
    int status = response.getStatusCode().value();
    String detail = StreamUtils.copyToString(response.getBody(), StandardCharsets.UTF_8);
    if (detail.length() > MAX_ERROR_BODY_CHARS) {
      detail = detail.substring(0, MAX_ERROR_BODY_CHARS) + "...";
    }
    String message =
        switch (status) {
          case 401 -> "GitHub rejected the token (401). Check ALLOTMINT_MCP_GITHUB_TOKEN.";
          case 403 ->
              "GitHub refused the request (403): the token lacks Issues write access to "
                  + repo
                  + " or a rate limit was hit. "
                  + detail;
          case 404 ->
              "GitHub returned 404: repository "
                  + repo
                  + " was not found or the token has no access to it.";
          default -> "GitHub returned %d: %s".formatted(status, detail);
        };
    log.warn("GitHub issue creation failed with status {}", status);
    throw new AllotMintApiException(status, message);
  }
}
