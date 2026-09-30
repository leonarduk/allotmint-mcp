package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.GitHubClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.springframework.web.client.RestClientException;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.allotmint.mcp.tool.ToolArguments.optionalString;

/**
 * Opt-in write tool that files a GitHub issue, so an MCP client can raise "there is no tool for X"
 * on the spot instead of drafting text for a human to paste.
 *
 * <p>It is an outward-facing write to a third party, so it is off by default ({@code
 * allotmint.mcp.issues.enabled}), refuses to act unless {@code confirm=true}, and can only target
 * the repository fixed in configuration ({@code allotmint.mcp.github.repo}) - the repository is
 * deliberately not a tool argument.
 */
public final class AllotMintCreateIssueTool {

  static final String TITLE = "title";
  static final String BODY = "body";
  static final String LABELS = "labels";
  static final String CONFIRM = "confirm";

  static final int MAX_TITLE_CHARS = 256;
  static final int MAX_BODY_CHARS = 20_000;
  static final int MAX_LABELS = 5;
  static final int MAX_LABEL_CHARS = 50;

  static final String FOOTER = "\n\n---\n_Filed via allotmint-mcp_";

  private AllotMintCreateIssueTool() {}

  /**
   * @throws IllegalArgumentException if the target repository is not configured as {@code
   *     owner/repo}
   */
  public static McpServerFeatures.SyncToolSpecification specification(GitHubClient client) {
    if (client == null || !client.validRepo()) {
      throw new IllegalArgumentException(
          "ALLOTMINT_MCP_GITHUB_REPO must be set to owner/repo when"
              + " ALLOTMINT_MCP_ISSUES_ENABLED=true");
    }

    Map<String, Object> properties = new LinkedHashMap<>();
    properties.put(
        TITLE,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "maxLength",
            MAX_TITLE_CHARS,
            "description",
            "Short issue title."));
    properties.put(
        BODY,
        Map.of(
            "type",
            "string",
            "maxLength",
            MAX_BODY_CHARS,
            "description",
            "Issue description in Markdown: what is wanted, why, and any constraints."));
    properties.put(
        LABELS,
        Map.of(
            "type",
            "array",
            "items",
            Map.of("type", "string", "minLength", 1, "maxLength", MAX_LABEL_CHARS),
            "maxItems",
            MAX_LABELS,
            "description",
            "Optional labels, e.g. enhancement. Labels that do not exist in the repository are "
                + "created by GitHub."));
    properties.put(
        CONFIRM,
        Map.of(
            "type",
            "boolean",
            "default",
            false,
            "description",
            "Must be true; the tool refuses to file an issue otherwise. Show the user the "
                + "title and body and get their agreement before setting this."));

    Map<String, Object> inputSchema =
        Map.of(
            "type",
            "object",
            "properties",
            properties,
            "required",
            List.of(TITLE),
            "additionalProperties",
            false);

    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_create_issue", inputSchema)
            .description(
                "Files a GitHub issue (e.g. a feature request or bug report) in "
                    + client.repo()
                    + ". Requires confirm=true. Publishes text to GitHub, so check the title and "
                    + "body with the user first, and never include secrets or private "
                    + "portfolio data. Returns the new issue's number and URL.")
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler((exchange, request) -> call(client, request.arguments()))
        .build();
  }

  private static McpSchema.CallToolResult call(GitHubClient client, Map<String, Object> arguments) {
    if (!confirmed(arguments)) {
      return error("allotmint_create_issue requires confirm=true; never silently publish.");
    }
    if (!client.tokenConfigured()) {
      return error(
          "GitHub issue creation is not configured: set ALLOTMINT_MCP_GITHUB_TOKEN to a"
              + " fine-grained token with Issues write access to "
              + client.repo()
              + ".");
    }

    String title = optionalString(arguments, TITLE);
    if (title == null) {
      return error("title is required");
    }
    if (title.length() > MAX_TITLE_CHARS) {
      return error("title must be at most " + MAX_TITLE_CHARS + " characters");
    }

    String body = optionalString(arguments, BODY);
    if (body != null && body.length() > MAX_BODY_CHARS) {
      return error("body must be at most " + MAX_BODY_CHARS + " characters");
    }

    List<String> labels;
    try {
      labels = labels(arguments.get(LABELS));
    } catch (IllegalArgumentException e) {
      return error(e.getMessage());
    }

    try {
      Map<String, Object> created =
          client.createIssue(title, body == null ? FOOTER.stripLeading() : body + FOOTER, labels);

      Map<String, Object> result = new LinkedHashMap<>();
      result.put("repo", client.repo());
      result.put("number", created.get("number"));
      result.put("url", created.get("html_url"));
      return McpSchema.CallToolResult.builder()
          .addTextContent("Created issue in " + client.repo() + ": " + created.get("html_url"))
          .structuredContent(result)
          .build();
    } catch (AllotMintApiException e) {
      return error(e.getMessage());
    } catch (RestClientException e) {
      return error("Unable to reach GitHub: " + e.getMessage());
    }
  }

  private static List<String> labels(Object value) {
    if (value == null) {
      return List.of();
    }
    if (!(value instanceof List<?> raw)) {
      throw new IllegalArgumentException("labels must be an array of strings");
    }
    if (raw.size() > MAX_LABELS) {
      throw new IllegalArgumentException("labels must contain at most " + MAX_LABELS + " entries");
    }
    List<String> labels = new ArrayList<>();
    for (Object item : raw) {
      if (!(item instanceof String text) || text.isBlank()) {
        throw new IllegalArgumentException("labels must be an array of non-blank strings");
      }
      String label = text.trim();
      if (label.length() > MAX_LABEL_CHARS) {
        throw new IllegalArgumentException(
            "each label must be at most " + MAX_LABEL_CHARS + " characters");
      }
      labels.add(label);
    }
    return labels;
  }

  private static boolean confirmed(Map<String, Object> arguments) {
    Object value = arguments.get(CONFIRM);
    if (value instanceof Boolean bool) {
      return bool;
    }
    if (value instanceof String text) {
      return Boolean.parseBoolean(text.trim());
    }
    return false;
  }

  private static McpSchema.CallToolResult error(String message) {
    return McpSchema.CallToolResult.builder().addTextContent(message).isError(true).build();
  }
}
