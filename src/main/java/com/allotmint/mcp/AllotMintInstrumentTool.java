package com.allotmint.mcp;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.springframework.web.client.RestClientException;

/**
 * The {@code allotmint_instrument} tool: searches instruments and retrieves detail, current quotes,
 * and news from the AllotMint backend.
 */
final class AllotMintInstrumentTool {

  static final String ACTION = "action";
  static final String QUERY = "query";
  static final String TICKER = "ticker";
  static final String EXCHANGE = "exchange";

  private static final List<String> ACTIONS = List.of("search", "detail", "prices", "news");

  private static final Map<String, Object> INPUT_SCHEMA =
      Map.of(
          "type",
          "object",
          "properties",
          Map.of(
              ACTION,
              Map.of("type", "string", "enum", ACTIONS),
              QUERY,
              Map.of("type", "string", "description", "Search text; required for search"),
              TICKER,
              Map.of("type", "string", "description", "Ticker; required except for search"),
              EXCHANGE,
              Map.of(
                  "type",
                  "string",
                  "description",
                  "Accepted for compatibility; exchange is inferred from the ticker suffix")),
          "required",
          List.of(ACTION),
          "additionalProperties",
          false);

  private AllotMintInstrumentTool() {}

  static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_instrument", INPUT_SCHEMA)
            .description(
                "Searches AllotMint instruments or returns detail, latest prices, or recent news")
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler((exchange, request) -> call(client, request.arguments()))
        .build();
  }

  private static McpSchema.CallToolResult call(
      AllotMintClient client, Map<String, Object> arguments) {
    try {
      String action = required(arguments, ACTION).toLowerCase(Locale.ROOT);
      if (!ACTIONS.contains(action)) {
        throw new IllegalArgumentException(
            "Unsupported action '%s'; expected one of search, detail, prices, news"
                .formatted(action));
      }

      return switch (action) {
        case "search" ->
            success(
                "Instrument search results", client.searchInstruments(required(arguments, QUERY)));
        case "detail" -> detail(client, required(arguments, TICKER));
        case "prices" -> success("Latest quote", client.latestQuotes(required(arguments, TICKER)));
        case "news" ->
            success("Recent instrument news", client.instrumentNews(required(arguments, TICKER)));
        default -> throw new IllegalStateException("Unreachable action: " + action);
      };
    } catch (IllegalArgumentException | AllotMintApiException e) {
      return error(e.getMessage());
    } catch (RestClientException e) {
      return error("Unable to call the AllotMint backend: " + e.getMessage());
    }
  }

  private static McpSchema.CallToolResult detail(AllotMintClient client, String ticker) {
    Map<String, Object> merged = new LinkedHashMap<>(client.instrumentDetail(ticker));
    merged.put("news", client.instrumentNews(ticker));
    return success("Instrument detail with price history, positions, and recent news", merged);
  }

  private static String required(Map<String, Object> arguments, String name) {
    Object value = arguments == null ? null : arguments.get(name);
    if (!(value instanceof String text) || text.isBlank()) {
      throw new IllegalArgumentException(
          "'%s' is required and must be a non-blank string".formatted(name));
    }
    return text.trim();
  }

  private static McpSchema.CallToolResult success(String summary, Object structured) {
    return McpSchema.CallToolResult.builder()
        .addTextContent(summary)
        .structuredContent(structured)
        .build();
  }

  private static McpSchema.CallToolResult error(String message) {
    return McpSchema.CallToolResult.builder().addTextContent(message).isError(true).build();
  }
}
