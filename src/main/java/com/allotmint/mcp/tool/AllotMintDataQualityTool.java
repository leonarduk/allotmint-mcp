package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.springframework.web.client.RestClientException;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.function.Supplier;

import static com.allotmint.mcp.tool.ToolArguments.optionalString;

/**
 * Read-write data-quality admin for AllotMint: the aggregated issue list (no owner required),
 * per-issue preview, per-series quality metrics, and the guarded fix/dedupe/undo write actions.
 *
 * <p>Write actions never run silently: the tool rejects them unless {@code confirm=true} and the
 * server's write capability is enabled ({@code allotmint.mcp.write.enabled=true}); the backend
 * additionally enforces no-clobber, {@code .bak} backups, and atomic audit records.
 */
public final class AllotMintDataQualityTool {

  static final String ACTION = "action";
  static final String TYPE = "type";
  static final String SEVERITY = "severity";
  static final String OWNER = "owner";
  static final String ACCOUNT = "account";
  static final String TICKER = "ticker";
  static final String ISSUE_ID = "issue_id";
  static final String EXCHANGE = "exchange";
  static final String AUDIT_ID = "audit_id";
  static final String CONFIRM = "confirm";

  private static final List<String> ACTIONS =
      List.of("issues", "series", "preview", "fix", "dedupe", "audit", "undo");
  private static final List<String> WRITE_ACTIONS = List.of("fix", "dedupe", "undo");
  private static final List<String> ISSUE_FILTERS = List.of(TYPE, SEVERITY, OWNER, ACCOUNT, TICKER);

  private AllotMintDataQualityTool() {}

  public static McpServerFeatures.SyncToolSpecification specification(
      AllotMintClient client, boolean writeEnabled) {
    Map<String, Object> properties = new LinkedHashMap<>();
    properties.put(ACTION, Map.of("type", "string", "enum", ACTIONS));
    properties.put(
        TYPE,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "description",
            "Filter issues by type, e.g. WRONG_EXCHANGE, GAPS, MISSING_SERIES."));
    properties.put(
        SEVERITY,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "description",
            "Filter issues by severity: high, medium, or low."));
    properties.put(
        OWNER,
        Map.of(
            "type", "string",
            "minLength", 1,
            "description", "Filter issues by holding owner."));
    properties.put(
        ACCOUNT,
        Map.of(
            "type", "string",
            "minLength", 1,
            "description", "Filter issues by holding account."));
    properties.put(
        TICKER,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "description",
            "Filter issues by ticker; also the series to dedupe for the dedupe action."));
    properties.put(
        ISSUE_ID,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "description",
            "Issue id from the issues action. Required for preview and fix."));
    properties.put(
        EXCHANGE,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "description",
            "Exchange suffix (e.g. L) for the dedupe action."));
    properties.put(
        AUDIT_ID,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "description",
            "Audit entry id from the audit action. Required for undo."));
    properties.put(
        CONFIRM,
        Map.of(
            "type",
            "boolean",
            "default",
            false,
            "description",
            "Must be true for the write actions fix, dedupe, and undo; the tool refuses to "
                + "mutate state otherwise."));

    Map<String, Object> inputSchema =
        Map.of(
            "type",
            "object",
            "properties",
            properties,
            "required",
            List.of(ACTION),
            "additionalProperties",
            false);

    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_data_quality", inputSchema)
            .description(
                "AllotMint data-quality admin. Read actions: issues (aggregated issue list "
                    + "across all owners; no owner required; optional type, severity, owner, "
                    + "account, ticker filters), series (per-series quality metrics), preview "
                    + "(review one issue's suggested fix before applying it), audit (append-only "
                    + "fix history). Write actions: fix (apply the previewed fix), dedupe "
                    + "(dedupe a cached series), undo (revert an audited action) - each requires "
                    + "confirm=true. Always call preview before fix."
                    + (writeEnabled
                        ? ""
                        : " Write actions are currently unavailable: the server's write "
                            + "capability is disabled (allotmint.mcp.write.enabled=false)."))
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler((exchange, request) -> call(client, writeEnabled, request.arguments()))
        .build();
  }

  private static McpSchema.CallToolResult call(
      AllotMintClient client, boolean writeEnabled, Map<String, Object> arguments) {
    String action = optionalString(arguments, ACTION);
    if (action == null || !ACTIONS.contains(action.toLowerCase(Locale.ROOT))) {
      return error("action must be one of: issues, series, preview, fix, dedupe, audit, undo");
    }
    String normalized = action.toLowerCase(Locale.ROOT);

    if (WRITE_ACTIONS.contains(normalized)) {
      if (!writeEnabled) {
        return error(
            "Write action '"
                + normalized
                + "' is unavailable: the server's write capability is disabled"
                + " (allotmint.mcp.write.enabled=false).");
      }
      if (!confirmed(arguments)) {
        return error(
            "Write action '"
                + normalized
                + "' requires confirm=true; never silently mutate state.");
      }
    }

    String issueId = optionalString(arguments, ISSUE_ID);
    String ticker = optionalString(arguments, TICKER);
    String exchange = optionalString(arguments, EXCHANGE);
    String auditId = optionalString(arguments, AUDIT_ID);

    if ((normalized.equals("preview") || normalized.equals("fix")) && issueId == null) {
      return error(
          "issue_id is required for the "
              + normalized
              + " action; obtain it from the issues action");
    }
    if (normalized.equals("dedupe") && (ticker == null || exchange == null)) {
      return error("ticker and exchange are required for the dedupe action");
    }
    if (normalized.equals("undo") && auditId == null) {
      return error("audit_id is required for the undo action; obtain it from the audit action");
    }

    return switch (normalized) {
      case "issues" -> execute(normalized, () -> issues(client, arguments));
      case "series" -> execute(normalized, () -> series(client));
      case "preview" -> execute(normalized, () -> preview(client, issueId));
      case "fix" -> execute(normalized, () -> fix(client, issueId));
      case "dedupe" -> execute(normalized, () -> dedupe(client, ticker, exchange));
      case "audit" -> execute(normalized, () -> audit(client));
      case "undo" -> execute(normalized, () -> undo(client, auditId));
      default -> throw new IllegalStateException("validated action became invalid");
    };
  }

  private static McpSchema.CallToolResult execute(
      String action, Supplier<Map<String, Object>> call) {
    try {
      return McpSchema.CallToolResult.builder()
          .addTextContent("AllotMint data quality %s returned successfully".formatted(action))
          .structuredContent(call.get())
          .build();
    } catch (AllotMintApiException e) {
      return error(e.getMessage());
    } catch (RestClientException e) {
      return error("Unable to reach the AllotMint backend: " + e.getMessage());
    }
  }

  private static Map<String, Object> issues(AllotMintClient client, Map<String, Object> arguments) {
    Map<String, String> filters = new LinkedHashMap<>();
    for (String filter : ISSUE_FILTERS) {
      String value = optionalString(arguments, filter);
      if (value != null) {
        filters.put(filter, value);
      }
    }
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "issues");
    result.putAll(client.dataQualityIssues(filters));
    return result;
  }

  private static Map<String, Object> series(AllotMintClient client) {
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "series");
    result.putAll(client.dataQualitySeries());
    return result;
  }

  private static Map<String, Object> preview(AllotMintClient client, String issueId) {
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "preview");
    result.put("issue_id", issueId);
    result.putAll(client.dataQualityPreview(issueId));
    return result;
  }

  private static Map<String, Object> fix(AllotMintClient client, String issueId) {
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "fix");
    result.put("issue_id", issueId);
    result.putAll(client.dataQualityFix(issueId, true));
    return result;
  }

  private static Map<String, Object> dedupe(
      AllotMintClient client, String ticker, String exchange) {
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "dedupe");
    result.put("ticker", ticker);
    result.put("exchange", exchange);
    result.putAll(client.dataQualityDedupe(ticker, exchange, true));
    return result;
  }

  private static Map<String, Object> audit(AllotMintClient client) {
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "audit");
    result.putAll(client.dataQualityAudit());
    return result;
  }

  private static Map<String, Object> undo(AllotMintClient client, String auditId) {
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "undo");
    result.put("audit_id", auditId);
    result.putAll(client.dataQualityUndo(auditId, true));
    return result;
  }

  private static boolean confirmed(Map<String, Object> arguments) {
    Object value = arguments.get(CONFIRM);
    if (value instanceof Boolean bool) {
      return bool;
    }
    if (value instanceof String text) {
      return Boolean.parseBoolean(text.trim());
    }
    return false;
  }

  private static McpSchema.CallToolResult error(String message) {
    return McpSchema.CallToolResult.builder().addTextContent(message).isError(true).build();
  }
}
