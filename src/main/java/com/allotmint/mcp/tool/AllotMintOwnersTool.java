package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;

import java.util.List;
import java.util.Map;

/** Lists account owners so MCP clients can present valid owner choices. */
public final class AllotMintOwnersTool {

  private AllotMintOwnersTool() {}

  public static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_owners", Map.of("type", "object", "properties", Map.of()))
            .description("Lists the account owners available to the authenticated AllotMint user")
            .outputSchema(
                Map.of(
                    "type", "object",
                    "properties", Map.of("owners", Map.of("type", "array")),
                    "required", List.of("owners")))
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler(
            (exchange, request) -> {
              List<Map<String, Object>> owners = client.owners();
              return McpSchema.CallToolResult.builder()
                  .addTextContent("Found %d account owner(s)".formatted(owners.size()))
                  .structuredContent(Map.of("owners", owners))
                  .build();
            })
        .build();
  }
}
