package com.allotmint.mcp;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;

import java.util.List;
import java.util.Map;

/**
 * Shared tool specification for the {@code echo} tool, registered against both the
 * HTTP and stdio MCP transports so they expose identical behavior.
 */
final class EchoTool {

    public static final String MESSAGE = "message";

    private EchoTool() {
    }

    static McpServerFeatures.SyncToolSpecification specification() {
        Map<String, Object> inputSchema = Map.of(
                "type", "object",
                "properties", Map.of(
                        MESSAGE, Map.of("type", "string")),
                "required", List.of(MESSAGE));

        McpSchema.Tool tool = McpSchema.Tool.builder("echo", inputSchema)
                .description("Echoes back the provided message")
                .build();

        return McpServerFeatures.SyncToolSpecification.builder()
                .tool(tool)
                .callHandler((exchange, request) -> {
                    String message = String.valueOf(request.arguments().get(MESSAGE));
                    return McpSchema.CallToolResult.builder()
                            .textContent(List.of("You said: " + message))
                            .build();
                })
                .build();
    }
}
