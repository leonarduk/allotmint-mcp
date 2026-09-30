package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.GitHubClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.ResourceAccessException;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AllotMintCreateIssueToolTest {

  private GitHubClient client;
  private McpServerFeatures.SyncToolSpecification specification;

  @BeforeEach
  void setUp() {
    client = configuredClient(true);
    specification = AllotMintCreateIssueTool.specification(client);
  }

  private static GitHubClient configuredClient(boolean tokenConfigured) {
    GitHubClient client = mock(GitHubClient.class);
    when(client.repo()).thenReturn("octo/tracker");
    when(client.validRepo()).thenReturn(true);
    when(client.tokenConfigured()).thenReturn(tokenConfigured);
    return client;
  }

  @Test
  void metadataRequiresOnlyTheTitleAndDoesNotExposeTheRepository() {
    McpSchema.Tool tool = specification.tool();

    assertThat(tool.name()).isEqualTo("allotmint_create_issue");
    assertThat(tool.inputSchema())
        .containsEntry("required", List.of("title"))
        .containsEntry("additionalProperties", false);
    assertThat(tool.description()).contains("octo/tracker").contains("confirm=true");

    @SuppressWarnings("unchecked")
    Map<String, Object> properties = (Map<String, Object>) tool.inputSchema().get("properties");
    assertThat(properties).containsOnlyKeys("title", "body", "labels", "confirm");
  }

  @Test
  void specificationRejectsAnInvalidOrMissingRepository() {
    GitHubClient invalid = mock(GitHubClient.class);
    when(invalid.validRepo()).thenReturn(false);

    assertThatThrownBy(() -> AllotMintCreateIssueTool.specification(invalid))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("ALLOTMINT_MCP_GITHUB_REPO");
    assertThatThrownBy(() -> AllotMintCreateIssueTool.specification(null))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("ALLOTMINT_MCP_GITHUB_REPO");
  }

  @Test
  void createsTheIssueAndReturnsItsNumberAndUrl() {
    when(client.createIssue(anyString(), anyString(), anyList()))
        .thenReturn(Map.of("number", 42, "html_url", "https://github.com/octo/tracker/issues/42"));

    McpSchema.CallToolResult result =
        call(
            Map.of(
                "title",
                " Add X ",
                "body",
                "Because Y",
                "labels",
                List.of(" enhancement "),
                "confirm",
                true));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.structuredContent())
        .isEqualTo(
            Map.of(
                "repo", "octo/tracker",
                "number", 42,
                "url", "https://github.com/octo/tracker/issues/42"));
    assertThat(text(result)).contains("https://github.com/octo/tracker/issues/42");
    verify(client)
        .createIssue(
            "Add X", "Because Y" + AllotMintCreateIssueTool.FOOTER, List.of("enhancement"));
  }

  @Test
  void aTitleOnlyIssueStillCarriesTheProvenanceFooter() {
    when(client.createIssue(anyString(), anyString(), anyList()))
        .thenReturn(Map.of("number", 1, "html_url", "u"));

    call(Map.of("title", "Just a title", "confirm", true));

    verify(client)
        .createIssue("Just a title", AllotMintCreateIssueTool.FOOTER.stripLeading(), List.of());
  }

  @Test
  void acceptsConfirmAsTheStringTrue() {
    when(client.createIssue(anyString(), anyString(), anyList()))
        .thenReturn(Map.of("number", 1, "html_url", "u"));

    assertThat(call(Map.of("title", "t", "confirm", "true")).isError()).isNotEqualTo(Boolean.TRUE);
  }

  @Test
  void refusesWithoutConfirmAndNeverCallsGitHub() {
    for (Map<String, Object> arguments :
        List.of(
            Map.<String, Object>of("title", "t"),
            Map.<String, Object>of("title", "t", "confirm", false),
            Map.<String, Object>of("title", "t", "confirm", "yes"),
            Map.<String, Object>of("title", "t", "confirm", 1))) {
      McpSchema.CallToolResult result = call(arguments);

      assertThat(result.isError()).as("%s", arguments).isEqualTo(Boolean.TRUE);
      assertThat(text(result)).contains("requires confirm=true");
    }
    verify(client, never()).createIssue(any(), any(), any());
  }

  @Test
  void reportsAMissingTokenWithoutCallingGitHub() {
    GitHubClient noToken = configuredClient(false);
    McpServerFeatures.SyncToolSpecification spec = AllotMintCreateIssueTool.specification(noToken);

    McpSchema.CallToolResult result =
        spec.callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_create_issue", Map.of("title", "t", "confirm", true)));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(text(result)).contains("ALLOTMINT_MCP_GITHUB_TOKEN").contains("octo/tracker");
    verify(noToken, never()).createIssue(any(), any(), any());
  }

  @Test
  void rejectsMissingBlankAndOversizedTitles() {
    for (Object title : new Object[] {null, "", "   ", "none"}) {
      Map<String, Object> arguments = new LinkedHashMap<>();
      arguments.put("title", title);
      arguments.put("confirm", true);
      McpSchema.CallToolResult result = call(arguments);

      assertThat(result.isError()).as("title=%s", title).isEqualTo(Boolean.TRUE);
      assertThat(text(result)).contains("title is required");
    }

    McpSchema.CallToolResult tooLong =
        call(
            Map.of(
                "title",
                "x".repeat(AllotMintCreateIssueTool.MAX_TITLE_CHARS + 1),
                "confirm",
                true));
    assertThat(tooLong.isError()).isEqualTo(Boolean.TRUE);
    assertThat(text(tooLong)).contains("title must be at most 256");
    verify(client, never()).createIssue(any(), any(), any());
  }

  @Test
  void rejectsAnOversizedBody() {
    McpSchema.CallToolResult result =
        call(
            Map.of(
                "title",
                "t",
                "body",
                "x".repeat(AllotMintCreateIssueTool.MAX_BODY_CHARS + 1),
                "confirm",
                true));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(text(result)).contains("body must be at most 20000");
    verify(client, never()).createIssue(any(), any(), any());
  }

  @Test
  void rejectsInvalidLabels() {
    List<Object> tooMany = new ArrayList<>(List.of("a", "b", "c", "d", "e", "f"));
    for (Object labels :
        new Object[] {"enhancement", tooMany, List.of(""), List.of(7), List.of("x".repeat(51))}) {
      McpSchema.CallToolResult result =
          call(Map.of("title", "t", "labels", labels, "confirm", true));

      assertThat(result.isError()).as("labels=%s", labels).isEqualTo(Boolean.TRUE);
      assertThat(text(result)).contains("label");
    }
    verify(client, never()).createIssue(any(), any(), any());
  }

  @Test
  void surfacesGitHubApiErrorsAsToolErrors() {
    when(client.createIssue(anyString(), anyString(), anyList()))
        .thenThrow(new AllotMintApiException(404, "GitHub returned 404: repository not found"));

    McpSchema.CallToolResult result = call(Map.of("title", "t", "confirm", true));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(text(result)).contains("GitHub returned 404");
  }

  @Test
  void surfacesAnUnreachableGitHubAsAToolError() {
    when(client.createIssue(anyString(), anyString(), anyList()))
        .thenThrow(new ResourceAccessException("timed out"));

    McpSchema.CallToolResult result = call(Map.of("title", "t", "confirm", true));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(text(result)).contains("Unable to reach GitHub");
  }

  private static String text(McpSchema.CallToolResult result) {
    return ((McpSchema.TextContent) result.content().get(0)).text();
  }

  private McpSchema.CallToolResult call(Map<String, Object> arguments) {
    return specification
        .callHandler()
        .apply(null, new McpSchema.CallToolRequest("allotmint_create_issue", arguments));
  }
}
