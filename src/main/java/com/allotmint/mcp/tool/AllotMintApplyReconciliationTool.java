package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.springframework.web.client.RestClientException;

import java.util.List;
import java.util.Map;

/** Explicit, opt-in write step for a previously generated reconciliation. */
public final class AllotMintApplyReconciliationTool {

  private AllotMintApplyReconciliationTool() {}

  public static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
    Map<String, Object> schema =
        Map.of(
            "type",
            "object",
            "properties",
            Map.of(
                "reconciliation_id",
                Map.of(
                    "type", "string",
                    "minLength", 1,
                    "description", "Opaque ID returned by allotmint_reconcile")),
            "required",
            List.of("reconciliation_id"),
            "additionalProperties",
            false);
    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_apply_reconciliation", schema)
            .description(
                "Writes a previously reviewed reconciliation. Only pass the opaque "
                    + "reconciliation_id returned with the exact diff shown to and approved by "
                    + "the user. This tool is unavailable unless writes are explicitly enabled.")
            .build();
    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler((exchange, request) -> call(client, request.arguments()))
        .build();
  }

  private static McpSchema.CallToolResult call(
      AllotMintClient client, Map<String, Object> arguments) {
    String id = AllotMintReconcileTool.required(arguments, "reconciliation_id");
    if (id == null) {
      return AllotMintReconcileTool.error(
          "reconciliation_id is required; first call allotmint_reconcile and review its diff");
    }
    try {
      return McpSchema.CallToolResult.builder()
          .addTextContent("The reviewed reconciliation was applied successfully.")
          .structuredContent(client.applyReconciliation(id))
          .build();
    } catch (AllotMintApiException e) {
      return AllotMintReconcileTool.error(e.getMessage());
    } catch (RestClientException e) {
      return AllotMintReconcileTool.error(
          "Unable to reach the AllotMint backend: " + e.getMessage());
    }
  }
}
