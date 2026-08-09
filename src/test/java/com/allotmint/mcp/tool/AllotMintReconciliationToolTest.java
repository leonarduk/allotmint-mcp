package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class AllotMintReconciliationToolTest {

  private final AllotMintClient client = mock(AllotMintClient.class);

  @Test
  void reconcileHasStrictReadOnlyInputSchema() {
    McpSchema.Tool tool = AllotMintReconcileTool.specification(client).tool();

    assertThat(tool.name()).isEqualTo("allotmint_reconcile");
    assertThat(tool.inputSchema().get("required"))
        .isEqualTo(List.of("owner", "account_type", "csv_content"));
    assertThat(tool.inputSchema()).containsEntry("additionalProperties", false);
  }

  @Test
  void returnsBackendDiffWithoutApplyingIt() {
    when(client.reconcileHoldings("alice", "SIPP", "Code,Quantity\nVWRL,2"))
        .thenReturn(Map.of("reconciliation_id", "rec-1", "added", Map.of("ticker", "VWRL.L")));

    McpSchema.CallToolResult result =
        call(
            AllotMintReconcileTool.specification(client),
            Map.of(
                "owner", "alice",
                "account_type", "SIPP",
                "csv_content", "Code,Quantity\nVWRL,2"));

    assertThat(result.isError()).isNotEqualTo(true);
    assertThat(((Map<?, ?>) result.structuredContent()).get("reconciliation_id"))
        .isEqualTo("rec-1");
    verify(client).reconcileHoldings("alice", "SIPP", "Code,Quantity\nVWRL,2");
  }

  @Test
  void preservesCsvContentWhitespaceButTrimsOwnerAndAccountType() {
    when(client.reconcileHoldings("alice", "SIPP", " Code,Quantity\nVWRL,2\n"))
        .thenReturn(Map.of("reconciliation_id", "rec-1"));

    McpSchema.CallToolResult result =
        call(
            AllotMintReconcileTool.specification(client),
            Map.of(
                "owner", " alice ",
                "account_type", " SIPP ",
                "csv_content", " Code,Quantity\nVWRL,2\n"));

    assertThat(result.isError()).isNotEqualTo(true);
    verify(client).reconcileHoldings("alice", "SIPP", " Code,Quantity\nVWRL,2\n");
  }

  @Test
  void rejectsMissingCsvBeforeCallingBackend() {
    McpSchema.CallToolResult result =
        call(
            AllotMintReconcileTool.specification(client),
            Map.of("owner", "alice", "account_type", "SIPP"));

    assertThat(result.isError()).isTrue();
    verifyNoInteractions(client);
  }

  @Test
  void applyRequiresOpaqueIdAndForwardsOnlyThatId() {
    when(client.applyReconciliation("rec-1")).thenReturn(Map.of("status", "applied"));

    McpSchema.CallToolResult result =
        call(
            AllotMintApplyReconciliationTool.specification(client),
            Map.of("reconciliation_id", "rec-1"));

    assertThat(result.isError()).isNotEqualTo(true);
    assertThat(((Map<?, ?>) result.structuredContent()).get("status")).isEqualTo("applied");
    verify(client).applyReconciliation("rec-1");
  }

  @Test
  void applyRejectsMissingOpaqueId() {
    McpSchema.CallToolResult result =
        call(AllotMintApplyReconciliationTool.specification(client), Map.of());

    assertThat(result.isError()).isTrue();
    verifyNoInteractions(client);
  }

  private static McpSchema.CallToolResult call(
      McpServerFeatures.SyncToolSpecification specification, Map<String, Object> arguments) {
    return specification
        .callHandler()
        .apply(null, new McpSchema.CallToolRequest(specification.tool().name(), arguments));
  }
}
