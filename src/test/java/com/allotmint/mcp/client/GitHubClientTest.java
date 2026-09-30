package com.allotmint.mcp.client;

import com.allotmint.mcp.exception.AllotMintApiException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class GitHubClientTest {

  private static final String BASE_URL = "https://github.test";
  private static final String ISSUES_URL = BASE_URL + "/repos/octo/tracker/issues";

  private MockRestServiceServer server;
  private RestClient restClient;

  @BeforeEach
  void setUp() {
    RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
    server = MockRestServiceServer.bindTo(builder).build();
    restClient = builder.build();
  }

  private GitHubClient client() {
    return new GitHubClient(restClient, "octo/tracker", true);
  }

  @Test
  void postsTheIssueToTheConfiguredRepositoryAndReturnsTheResponse() {
    server
        .expect(requestTo(ISSUES_URL))
        .andExpect(method(HttpMethod.POST))
        .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
        .andExpect(jsonPath("$.title").value("A title"))
        .andExpect(jsonPath("$.body").value("A body"))
        .andExpect(jsonPath("$.labels[0]").value("enhancement"))
        .andRespond(
            withSuccess(
                "{\"number\":42,\"html_url\":\"https://github.com/octo/tracker/issues/42\"}",
                MediaType.APPLICATION_JSON));

    Map<String, Object> response =
        client().createIssue("A title", "A body", List.of("enhancement"));

    assertThat(response)
        .containsEntry("number", 42)
        .containsEntry("html_url", "https://github.com/octo/tracker/issues/42");
    server.verify();
  }

  @Test
  void omitsBodyAndLabelsWhenNotProvided() {
    server
        .expect(requestTo(ISSUES_URL))
        .andExpect(jsonPath("$.title").value("Only a title"))
        .andExpect(jsonPath("$.body").doesNotExist())
        .andExpect(jsonPath("$.labels").doesNotExist())
        .andRespond(withSuccess("{\"number\":1}", MediaType.APPLICATION_JSON));

    assertThat(client().createIssue("Only a title", null, List.of())).containsEntry("number", 1);
    server.verify();
  }

  @Test
  void mapsAuthenticationFailureWithoutEchoingTheResponseBody() {
    server
        .expect(requestTo(ISSUES_URL))
        .andRespond(withStatus(HttpStatus.UNAUTHORIZED).body("secret-ish body"));

    assertThatThrownBy(() -> client().createIssue("t", null, List.of()))
        .isInstanceOf(AllotMintApiException.class)
        .hasMessageContaining("rejected the token")
        .hasMessageContaining("ALLOTMINT_MCP_GITHUB_TOKEN")
        .hasMessageNotContaining("secret-ish");
  }

  @Test
  void mapsForbiddenAndNotFoundToActionableMessages() {
    server.expect(requestTo(ISSUES_URL)).andRespond(withStatus(HttpStatus.FORBIDDEN).body("nope"));
    assertThatThrownBy(() -> client().createIssue("t", null, List.of()))
        .isInstanceOf(AllotMintApiException.class)
        .hasMessageContaining("403")
        .hasMessageContaining("octo/tracker")
        .hasMessageContaining("nope");

    server.reset();
    server.expect(requestTo(ISSUES_URL)).andRespond(withStatus(HttpStatus.NOT_FOUND));
    assertThatThrownBy(() -> client().createIssue("t", null, List.of()))
        .isInstanceOf(AllotMintApiException.class)
        .hasMessageContaining("404")
        .hasMessageContaining("octo/tracker");
  }

  @Test
  void includesGitHubValidationDetailForOtherErrorsAndTruncatesLongBodies() {
    server
        .expect(requestTo(ISSUES_URL))
        .andRespond(withStatus(HttpStatus.UNPROCESSABLE_ENTITY).body("x".repeat(2_000)));

    assertThatThrownBy(() -> client().createIssue("t", null, List.of()))
        .isInstanceOf(AllotMintApiException.class)
        .hasMessageStartingWith("GitHub returned 422: xxx")
        .satisfies(e -> assertThat(e.getMessage().length()).isLessThan(600));
  }

  @Test
  void refusesToCallGitHubWithoutAToken() {
    GitHubClient noToken = new GitHubClient(restClient, "octo/tracker", false);

    assertThat(noToken.tokenConfigured()).isFalse();
    assertThatThrownBy(() -> noToken.createIssue("t", null, List.of()))
        .isInstanceOf(IllegalStateException.class)
        .hasMessageContaining("token");
    server.verify();
  }

  @Test
  void validatesTheRepositoryFormat() {
    assertThat(new GitHubClient(restClient, "octo/tracker", true).validRepo()).isTrue();
    assertThat(new GitHubClient(restClient, " octo/my.repo_1-x ", true).validRepo()).isTrue();
    for (String bad :
        new String[] {
          "", "octo", "octo/", "/tracker", "a/b/c", "octo/a b", "../x", "octo/..", "./x", "octo/."
        }) {
      GitHubClient client = new GitHubClient(restClient, bad, true);
      assertThat(client.validRepo()).as("repo=%s", bad).isFalse();
      assertThatThrownBy(() -> client.createIssue("t", null, List.of()))
          .isInstanceOf(IllegalStateException.class)
          .hasMessageContaining("owner/repo");
    }
    assertThat(new GitHubClient(restClient, null, true).validRepo()).isFalse();
    assertThat(new GitHubClient(restClient, " octo/tracker ", true).repo())
        .isEqualTo("octo/tracker");
  }
}
