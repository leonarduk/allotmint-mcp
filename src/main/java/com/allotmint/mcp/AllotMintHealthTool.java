package com.allotmint.mcp;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;

import java.util.List;
import java.util.Map;

/**
 * The {@code allotmint_health} tool: no arguments, proves the MCP server can reach the
 * AllotMint backend. Registered against both the HTTP and stdio transports so behavior
 * matches (see {@link EchoTool} for the same pattern).
 */
final class AllotMintHealthTool {

    private AllotMintHealthTool() {
    }

    static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
        McpSchema.Tool tool = McpSchema.Tool.builder("allotmint_health", Map.of("type", "object", "properties", Map.of()))
                .description("Checks connectivity to the AllotMint backend and reports its version")
                .build();

        return McpServerFeatures.SyncToolSpecification.builder()
                .tool(tool)
                .callHandler((exchange, request) -> {
                    // TODO(#4): call client.health(), map AllotMintHealthStatus into the
                    // {reachable, version, baseUrl} result the issue asks for. Also
                    // decide what happens if AllotMintClient.health() throws
                    // AllotMintApiException - should this tool ever return
                    // CallToolResult.builder().isError(true)...? for a health check, or
                    // always return reachable=false instead?
                    throw new UnsupportedOperationException("TODO(#4): implement allotmint_health callHandler");
                })
                .build();
    }
}
