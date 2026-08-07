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

/**
 * Instrument lookups composed from AllotMint's per-ticker endpoints: {@code search} matches
 * tickers/names, {@code detail} merges price history + portfolio positions + recent news, {@code
 * prices} returns the latest quote, and {@code news} returns recent headlines alone.
 */
public final class AllotMintInstrumentTool {

  static final String ACTION = "action";
  static final String QUERY = "query";
  static final String TICKER = "ticker";
  static final String EXCHANGE = "exchange";

  private static final List<String> ACTIONS = List.of("search", "detail", "prices", "news");

  private AllotMintInstrumentTool() {}

  public static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
    Map<String, Object> properties = new LinkedHashMap<>();
    properties.put(ACTION, Map.of("type", "string", "enum", ACTIONS));
    properties.put(
        QUERY,
        Map.of(
            "type", "string",
            "minLength", 1,
            "description", "Ticker or name search term. Required for the search action."));
    properties.put(
        TICKER,
        Map.of(
            "type", "string",
            "minLength", 1,
            "description",
                "Full ticker, e.g. VWRL.L. Required for the detail, prices, and news actions."));
    properties.put(
        EXCHANGE,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "description",
            "Optional exchange suffix (e.g. L for London Stock Exchange), appended to ticker "
                + "when ticker does not already carry one - ticker=VWRL, exchange=L becomes "
                + "VWRL.L."));

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
        McpSchema.Tool.builder("allotmint_instrument", inputSchema)
            .description(
                "Looks up an AllotMint instrument. Actions: search (query required) matches "
                    + "instruments by ticker or name; detail (ticker required) merges price "
                    + "history, portfolio holding positions, and recent news for one ticker; "
                    + "prices (ticker required) returns the latest quote; news (ticker required) "
                    + "returns recent headlines.")
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler((exchange, request) -> call(client, request.arguments()))
        .build();
  }

  private static McpSchema.CallToolResult call(
      AllotMintClient client, Map<String, Object> arguments) {
    String action = optionalString(arguments, ACTION);
    if (action == null || !ACTIONS.contains(action.toLowerCase(Locale.ROOT))) {
      return error("action must be one of: search, detail, prices, news");
    }
    String normalizedAction = action.toLowerCase(Locale.ROOT);

    if (normalizedAction.equals("search")) {
      String query = optionalString(arguments, QUERY);
      if (query == null) {
        return error("query is required for the search action");
      }
      return execute(normalizedAction, () -> search(client, query));
    }

    String ticker = resolveTicker(arguments);
    if (ticker == null) {
      return error("ticker is required for the " + normalizedAction + " action");
    }
    return switch (normalizedAction) {
      case "detail" -> execute(normalizedAction, () -> detail(client, ticker));
      case "prices" -> execute(normalizedAction, () -> prices(client, ticker));
      case "news" -> execute(normalizedAction, () -> news(client, ticker));
      default -> throw new IllegalStateException("validated action became invalid");
    };
  }

  private static McpSchema.CallToolResult execute(
      String action, Supplier<Map<String, Object>> call) {
    try {
      return McpSchema.CallToolResult.builder()
          .addTextContent("AllotMint instrument %s returned successfully".formatted(action))
          .structuredContent(call.get())
          .build();
    } catch (AllotMintApiException e) {
      return error(e.getMessage());
    } catch (RestClientException e) {
      return error("Unable to reach the AllotMint backend: " + e.getMessage());
    }
  }

  private static Map<String, Object> search(AllotMintClient client, String query) {
    List<Map<String, Object>> matches = client.instrumentSearch(query);
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "search");
    result.put("query", query);
    result.put("matches", matches);
    return result;
  }

  private static Map<String, Object> detail(AllotMintClient client, String ticker) {
    Map<String, Object> instrument = client.instrumentDetail(ticker);
    List<Map<String, Object>> news = client.news(ticker);

    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "detail");
    result.put("ticker", ticker);
    result.putAll(instrument);
    result.put("news", news);
    return result;
  }

  private static Map<String, Object> prices(AllotMintClient client, String ticker) {
    List<Map<String, Object>> quotes = client.quotes(ticker);
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "prices");
    result.put("ticker", ticker);
    result.put("quote", quotes.isEmpty() ? null : quotes.getFirst());
    return result;
  }

  private static Map<String, Object> news(AllotMintClient client, String ticker) {
    List<Map<String, Object>> headlines = client.news(ticker);
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", "news");
    result.put("ticker", ticker);
    result.put("headlines", headlines);
    return result;
  }

  /**
   * Combines {@code ticker}/{@code exchange} into one AllotMint-style ticker (e.g. {@code VWRL} +
   * {@code L} -> {@code VWRL.L}). The backend infers exchange from the ticker suffix rather than a
   * separate parameter, so a ticker that already carries a suffix is used as-is and {@code
   * exchange} is ignored.
   */
  private static String resolveTicker(Map<String, Object> arguments) {
    String ticker = optionalString(arguments, TICKER);
    if (ticker == null) {
      return null;
    }
    String exchange = optionalString(arguments, EXCHANGE);
    if (exchange != null && ticker.indexOf('.') < 0) {
      return ticker + "." + exchange;
    }
    return ticker;
  }

  private static String optionalString(Map<String, Object> values, String key) {
    Object value = values.get(key);
    if (!(value instanceof String text) || text.isBlank()) {
      return null;
    }
    return text.trim();
  }

  private static McpSchema.CallToolResult error(String message) {
    return McpSchema.CallToolResult.builder().addTextContent(message).isError(true).build();
  }
}
