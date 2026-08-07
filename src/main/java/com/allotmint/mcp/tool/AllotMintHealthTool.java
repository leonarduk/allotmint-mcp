package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.pojo.AllotMintHealthStatus;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The {@code allotmint_health} tool: no arguments, proves the MCP server can reach the AllotMint
 * backend. Registered against both the HTTP and stdio transports so behavior matches (see {@link
 * EchoTool} for the same pattern).
 */
public final class AllotMintHealthTool {

  private static final Map<String, Object> OUTPUT_SCHEMA =
      Map.of(
          "type", "object",
          "properties",
              Map.of(
                  "reachable", Map.of("type", "boolean"),
                  "version", Map.of("type", "string"),
                  "baseUrl", Map.of("type", "string")),
          "required", List.of("reachable", "baseUrl"));

  private AllotMintHealthTool() {}

  public static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_health", Map.of("type", "object", "properties", Map.of()))
            .description("Checks connectivity to the AllotMint backend and reports its version")
            .outputSchema(OUTPUT_SCHEMA)
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler(
            (exchange, request) -> {
              AllotMintHealthStatus status = client.health();

              Map<String, Object> structured = new LinkedHashMap<>();
              structured.put("reachable", status.reachable());
              structured.put("baseUrl", status.baseUrl());
              if (status.version() != null) {
                structured.put("version", status.version());
              }

              String summary =
                  status.reachable()
                      ? "AllotMint backend reachable at %s (version %s)"
                          .formatted(status.baseUrl(), status.version())
                      : "AllotMint backend at %s is not reachable".formatted(status.baseUrl());

              return McpSchema.CallToolResult.builder()
                  .addTextContent(summary)
                  .structuredContent(structured)
                  .build();
            })
        .build();
  }
}
