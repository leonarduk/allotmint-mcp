package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.allotmint.mcp.tool.ToolArguments.optionalString;

/** Provides market-wide context from the AllotMint backend. */
public final class AllotMintMarketTool {

  public static final String ACTION = "action";
  public static final String OVERVIEW = "overview";
  public static final String MOVERS = "movers";
  public static final String INDICES = "indices";
  public static final String TICKERS = "tickers";

  private static final Map<String, Object> INPUT_SCHEMA;

  static {
    Map<String, Object> properties = new LinkedHashMap<>();
    properties.put(ACTION, Map.of("type", "string", "enum", List.of(OVERVIEW, MOVERS, INDICES)));
    properties.put(
        TICKERS,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "description",
            "Comma-separated tickers, e.g. 'AZN.L,VOD.L'. Required for the movers action; "
                + "ignored otherwise."));

    INPUT_SCHEMA =
        Map.of(
            "type",
            "object",
            "properties",
            properties,
            "required",
            List.of(ACTION),
            "additionalProperties",
            false);
  }

  private static final Map<String, Object> OUTPUT_SCHEMA =
      Map.of("type", "object", "additionalProperties", true);

  private AllotMintMarketTool() {}

  public static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_market", INPUT_SCHEMA)
            .description(
                "Returns an AllotMint market overview, movers, or index levels and changes. "
                    + "The movers action requires tickers (comma-separated, e.g. 'AZN.L,VOD.L') "
                    + "since the backend has no default watchlist to fall back to.")
            .outputSchema(OUTPUT_SCHEMA)
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler(
            (exchange, request) -> {
              Map<String, Object> arguments = request.arguments();
              String action = requireAction(arguments);

              if (MOVERS.equals(action)) {
                String tickers = optionalString(arguments, TICKERS);
                if (tickers == null) {
                  return error(
                      "tickers is required for the movers action (comma-separated, e.g. "
                          + "'AZN.L,VOD.L')");
                }
                return buildResult(action, client.marketMovers(tickers));
              }

              Map<String, Object> result =
                  switch (action) {
                    case OVERVIEW -> client.marketOverview();
                    case INDICES -> extractIndices(client.marketOverview());
                    default ->
                        throw new IllegalArgumentException(
                            "Unsupported action '%s'; expected overview, movers, or indices"
                                .formatted(action));
                  };

              return buildResult(action, result);
            })
        .build();
  }

  private static McpSchema.CallToolResult buildResult(String action, Map<String, Object> result) {
    return McpSchema.CallToolResult.builder()
        .addTextContent("AllotMint market %s returned successfully".formatted(action))
        .structuredContent(result)
        .build();
  }

  private static McpSchema.CallToolResult error(String message) {
    return McpSchema.CallToolResult.builder().addTextContent(message).isError(true).build();
  }

  private static String requireAction(Map<String, Object> arguments) {
    Object action = arguments == null ? null : arguments.get(ACTION);
    if (!(action instanceof String value) || value.isBlank()) {
      throw new IllegalArgumentException("action is required");
    }
    return value;
  }

  private static Map<String, Object> extractIndices(Map<String, Object> overview) {
    Object indexes = overview.get("indexes");
    if (indexes == null) {
      indexes = overview.get("indices");
    }
    if (indexes == null) {
      return Map.of();
    }
    if (!(indexes instanceof Map<?, ?> indexMap)) {
      throw new IllegalStateException(
          "AllotMint market overview returned a non-object indexes value");
    }

    @SuppressWarnings("unchecked")
    Map<String, Object> typedIndexes = (Map<String, Object>) indexMap;
    return typedIndexes;
  }
}
