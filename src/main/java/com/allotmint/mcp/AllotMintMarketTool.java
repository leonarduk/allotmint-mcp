package com.allotmint.mcp;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.util.List;
import java.util.Map;

/** Provides market-wide context from the AllotMint backend. */
final class AllotMintMarketTool {

  static final String ACTION = "action";
  static final String OVERVIEW = "overview";
  static final String MOVERS = "movers";
  static final String INDICES = "indices";

  private static final Map<String, Object> INPUT_SCHEMA =
      Map.of(
          "type",
          "object",
          "properties",
          Map.of(ACTION, Map.of("type", "string", "enum", List.of(OVERVIEW, MOVERS, INDICES))),
          "required",
          List.of(ACTION),
          "additionalProperties",
          false);

  private static final Map<String, Object> OUTPUT_SCHEMA =
      Map.of("type", "object", "additionalProperties", true);

  private AllotMintMarketTool() {}

  static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_market", INPUT_SCHEMA)
            .description(
                "Returns an AllotMint market overview, movers, or index levels and changes")
            .outputSchema(OUTPUT_SCHEMA)
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler(
            (exchange, request) -> {
              String action = requireAction(request.arguments());
              Map<String, Object> result =
                  switch (action) {
                    case OVERVIEW -> client.marketOverview();
                    case MOVERS -> client.marketMovers();
                    case INDICES -> extractIndices(client.marketOverview());
                    default ->
                        throw new IllegalArgumentException(
                            "Unsupported action '%s'; expected overview, movers, or indices"
                                .formatted(action));
                  };

              return McpSchema.CallToolResult.builder()
                  .addTextContent("AllotMint market %s returned successfully".formatted(action))
                  .structuredContent(result)
                  .build();
            })
        .build();
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
