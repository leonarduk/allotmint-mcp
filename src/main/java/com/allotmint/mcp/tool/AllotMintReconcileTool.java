package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.springframework.web.client.RestClientException;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Read-only broker CSV reconciliation. */
public final class AllotMintReconcileTool {

  private AllotMintReconcileTool() {}

  public static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
    Map<String, Object> properties = new LinkedHashMap<>();
    properties.put("owner", stringProperty("AllotMint owner slug"));
    properties.put("account_type", stringProperty("Account containing the broker positions"));
    properties.put(
        "csv_content",
        stringProperty("Complete, unmodified broker-exported CSV content, including headers"));
    Map<String, Object> schema =
        Map.of(
            "type",
            "object",
            "properties",
            properties,
            "required",
            List.of("owner", "account_type", "csv_content"),
            "additionalProperties",
            false);

    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_reconcile", schema)
            .description(
                "Compares a broker CSV with stored holdings and returns a read-only structured "
                    + "diff. It never writes. Show the complete diff to the user before offering "
                    + "to apply its reconciliation_id.")
            .build();
    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler((exchange, request) -> call(client, request.arguments()))
        .build();
  }

  private static McpSchema.CallToolResult call(
      AllotMintClient client, Map<String, Object> arguments) {
    String owner = required(arguments, "owner");
    String accountType = required(arguments, "account_type");
    String csv = required(arguments, "csv_content");
    if (owner == null || accountType == null || csv == null) {
      return error("owner, account_type, and non-empty csv_content are required");
    }
    try {
      Map<String, Object> diff = client.reconcileHoldings(owner, accountType, csv);
      return McpSchema.CallToolResult.builder()
          .addTextContent(
              "Read-only reconciliation complete. Review every discrepancy before applying it.")
          .structuredContent(diff)
          .build();
    } catch (AllotMintApiException e) {
      return error(e.getMessage());
    } catch (RestClientException e) {
      return error("Unable to reach the AllotMint backend: " + e.getMessage());
    }
  }

  private static Map<String, Object> stringProperty(String description) {
    return Map.of("type", "string", "minLength", 1, "description", description);
  }

  static String required(Map<String, Object> arguments, String name) {
    Object value = arguments.get(name);
    return value instanceof String text && !text.isBlank() ? text.trim() : null;
  }

  static McpSchema.CallToolResult error(String message) {
    return McpSchema.CallToolResult.builder().addTextContent(message).isError(true).build();
  }
}
