package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.client.RestClientException;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import static com.allotmint.mcp.tool.ToolArguments.optionalString;

/** Read-only portfolio queries composed from the per-owner AllotMint endpoints. */
@Slf4j
public final class AllotMintPortfolioTool {

  static final String ACTION = "action";
  static final String OWNER = "owner";
  static final String ACCOUNT_TYPE = "account_type";
  static final String CURRENCY = "currency";
  static final String INCLUDE_HISTORY = "include_history";
  static final String LOOKBACK_DAYS = "lookback_days";

  private static final List<String> ACTIONS = List.of("summary", "exposure", "holdings");
  private static final int DEFAULT_LOOKBACK_DAYS = 365;
  private static final int MAX_LOOKBACK_DAYS = 3650;

  private AllotMintPortfolioTool() {}

  public static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
    Map<String, Object> properties = new LinkedHashMap<>();
    properties.put(ACTION, Map.of("type", "string", "enum", ACTIONS));
    properties.put(
        OWNER,
        Map.of(
            "type", "string",
            "minLength", 1,
            "description", "Owner slug returned by GET /owners"));
    properties.put(ACCOUNT_TYPE, Map.of("type", "string", "minLength", 1));
    properties.put(CURRENCY, Map.of("type", "string", "minLength", 1));
    properties.put(
        INCLUDE_HISTORY,
        Map.of(
            "type",
            "boolean",
            "default",
            false,
            "description",
            "When true, include the full performance.history array in summary. "
                + "Defaults to false to keep the payload compact for small models."));
    properties.put(
        LOOKBACK_DAYS,
        Map.of(
            "type",
            "integer",
            "minimum",
            0,
            "maximum",
            MAX_LOOKBACK_DAYS,
            "description",
            "Days to look back for historical sector-weight comparison. "
                + "Set to 0 to skip the historical lookup. "
                + "When 1–3650, each sector in the exposure response includes a "
                + "weight_pct_year_ago field IF the backend can price that far back; "
                + "when it cannot, the field is omitted entirely and the response carries "
                + "a historical_comparison note saying so. Never infer a change in weight "
                + "from a missing field. "
                + "Defaults to 365 (year-ago comparison) when omitted."));

    Map<String, Object> inputSchema =
        Map.of(
            "type",
            "object",
            "properties",
            properties,
            "required",
            List.of(ACTION, OWNER),
            "additionalProperties",
            false);

    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_portfolio", inputSchema)
            .description(
                "Reads one owner's AllotMint portfolio. owner is required; call GET /owners "
                    + "through the AllotMint API to discover valid owner slugs. Actions: summary, "
                    + "exposure, or holdings. Optional account_type and currency filters are "
                    + "applied client-side. For summary, set include_history=true to receive "
                    + "the full performance.history array (omitted by default to keep the payload "
                    + "compact for small models).")
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler((exchange, request) -> call(client, request.arguments()))
        .build();
  }

  private static McpSchema.CallToolResult call(
      AllotMintClient client, Map<String, Object> arguments) {
    String owner = requiredString(arguments, OWNER);
    if (owner == null) {
      return error(
          "owner is required. Use GET /owners on the AllotMint API to discover valid owner slugs.");
    }
    String action = requiredString(arguments, ACTION);
    if (action == null || !ACTIONS.contains(action.toLowerCase(Locale.ROOT))) {
      return error("action must be one of: summary, exposure, holdings");
    }

    String accountType = optionalString(arguments, ACCOUNT_TYPE);
    String currency = optionalString(arguments, CURRENCY);
    boolean includeHistory = optionalBoolean(arguments, INCLUDE_HISTORY);
    int lookbackDays = parseLookbackDays(arguments);

    try {
      Map<String, Object> structured =
          switch (action.toLowerCase(Locale.ROOT)) {
            case "summary" -> summary(client, owner, accountType, currency, includeHistory);
            case "exposure" -> exposure(client, owner, accountType, currency, lookbackDays);
            case "holdings" -> holdings(client, owner, accountType, currency);
            default -> throw new IllegalStateException("validated action became invalid");
          };

      return McpSchema.CallToolResult.builder()
          .addTextContent(
              "AllotMint portfolio %s for owner %s returned successfully"
                  .formatted(action.toLowerCase(Locale.ROOT), owner))
          .structuredContent(structured)
          .build();
    } catch (AllotMintApiException e) {
      return error(e.getMessage());
    } catch (RestClientException e) {
      return error("Unable to reach the AllotMint backend: " + e.getMessage());
    }
  }

  private static Map<String, Object> summary(
      AllotMintClient client,
      String owner,
      String accountType,
      String currency,
      boolean includeHistory) {
    Map<String, Object> portfolio = client.portfolio(owner);
    Map<String, Object> performance = client.performance(owner);
    List<Account> accounts = filteredAccounts(portfolio, accountType, currency);

    BigDecimal totalValue =
        accounts.stream()
            .map(account -> accountValue(account, currency))
            .reduce(BigDecimal.ZERO, BigDecimal::add);
    BigDecimal dayChange =
        accounts.stream()
            .flatMap(account -> account.holdings().stream())
            .map(holding -> decimal(holding.get("day_change_gbp")))
            .reduce(BigDecimal.ZERO, BigDecimal::add);

    List<Map<String, Object>> allocation = new ArrayList<>();
    for (Account account : accounts) {
      BigDecimal value = accountValue(account, currency);
      Map<String, Object> row = new LinkedHashMap<>();
      row.put("account_type", account.accountType());
      row.put("currency", account.currency());
      row.put("market_value_gbp", value);
      row.put("weight_pct", percentage(value, totalValue));
      allocation.add(row);
    }

    Map<String, Object> result = baseResult("summary", owner, accountType, currency);
    result.put("as_of", portfolio.get("as_of"));
    result.put("total_value_gbp", totalValue);
    result.put("day_change_gbp", dayChange);
    result.put("allocation", allocation);
    result.put("performance", includeHistory ? performance : withoutHistory(performance));
    return result;
  }

  /**
   * Returns a copy of the performance map without the {@code history} key, so the default payload
   * stays compact for small local models. When the caller explicitly sets {@code include_history:
   * true} the full map is passed through as-is.
   */
  private static Map<String, Object> withoutHistory(Map<String, Object> performance) {
    if (performance == null || performance.isEmpty()) {
      return performance;
    }
    Map<String, Object> trimmed = new LinkedHashMap<>(performance);
    trimmed.remove("history");
    return trimmed;
  }

  private static Map<String, Object> exposure(
      AllotMintClient client, String owner, String accountType, String currency, int lookbackDays) {
    // The sector endpoint is authoritative. Asset-class and currency endpoints do not exist, so
    // those two breakdowns are derived from the portfolio response.
    List<Map<String, Object>> backendSectors = client.portfolioSectors(owner);
    Map<String, Object> portfolio = client.portfolio(owner);
    List<Account> accounts = filteredAccounts(portfolio, accountType, currency);
    List<Map<String, Object>> filteredHoldings = flatten(accounts);

    List<Map<String, Object>> sectors =
        accountType == null && currency == null
            ? backendSectors
            : aggregate(filteredHoldings, "sector", "Unknown");

    // Enrich with historical comparison when lookback is requested.
    String historicalNote = null;
    if (lookbackDays > 0) {
      LocalDate asOf = LocalDate.now(ZoneOffset.UTC).minusDays(lookbackDays);
      try {
        List<Map<String, Object>> historical = client.portfolioSectors(owner, asOf);
        HistoricalWeights enrichment = enrichWithHistoricalWeights(sectors, historical, asOf);
        sectors = enrichment.sectors();
        historicalNote = enrichment.note();
      } catch (AllotMintApiException | RestClientException e) {
        log.warn(
            "Unable to fetch historical sector weights for owner {} (as of {}): {} — "
                + "year-ago enrichment skipped",
            owner,
            asOf,
            e.getMessage());
        historicalNote =
            "Year-ago sector weights are unavailable: the historical lookup failed. "
                + "Do not report any change in sector weight.";
      }
    }

    Map<String, Object> result = baseResult("exposure", owner, accountType, currency);
    result.put("as_of", portfolio.get("as_of"));
    result.put("sectors", sectors);
    if (historicalNote != null) {
      result.put("historical_comparison", historicalNote);
    }
    result.put("asset_classes", aggregate(filteredHoldings, "asset_class", "Unknown"));
    result.put("currencies", aggregate(filteredHoldings, "currency", "Unknown"));
    return result;
  }

  private static Map<String, Object> holdings(
      AllotMintClient client, String owner, String accountType, String currency) {
    Map<String, Object> portfolio = client.portfolio(owner);
    List<Map<String, Object>> holdings =
        flatten(filteredAccounts(portfolio, accountType, currency));
    holdings.sort(
        (left, right) ->
            decimal(right.get("market_value_gbp"))
                .compareTo(decimal(left.get("market_value_gbp"))));

    Map<String, Object> result = baseResult("holdings", owner, accountType, currency);
    result.put("as_of", portfolio.get("as_of"));
    result.put("holdings", holdings);
    return result;
  }

  private static Map<String, Object> baseResult(
      String action, String owner, String accountType, String currency) {
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("action", action);
    result.put("owner", owner);
    if (accountType != null) {
      result.put(ACCOUNT_TYPE, accountType);
    }
    if (currency != null) {
      result.put(CURRENCY, currency);
    }
    return result;
  }

  @SuppressWarnings("unchecked")
  private static List<Account> filteredAccounts(
      Map<String, Object> portfolio, String accountType, String currency) {
    Object rawAccounts = portfolio.get("accounts");
    if (!(rawAccounts instanceof List<?> list)) {
      return List.of();
    }

    List<Account> result = new ArrayList<>();
    for (Object item : list) {
      if (!(item instanceof Map<?, ?> raw)) {
        continue;
      }
      Map<String, Object> account = (Map<String, Object>) raw;
      String actualAccountType = optionalString(account, "account_type");
      String actualCurrency = optionalString(account, "currency");
      if (!matches(accountType, actualAccountType)) {
        continue;
      }
      List<Map<String, Object>> holdings = new ArrayList<>();
      Object rawHoldings = account.get("holdings");
      if (rawHoldings instanceof List<?> holdingList) {
        for (Object holdingItem : holdingList) {
          if (holdingItem instanceof Map<?, ?> holdingMap) {
            Map<String, Object> holding = (Map<String, Object>) holdingMap;
            String holdingCurrency = optionalString(holding, "currency");
            if (currency == null
                || matches(currency, holdingCurrency)
                || (holdingCurrency == null && matches(currency, actualCurrency))) {
              holdings.add(holding);
            }
          }
        }
      }
      if (currency == null || !holdings.isEmpty()) {
        result.add(new Account(account, actualAccountType, actualCurrency, holdings));
      }
    }
    return result;
  }

  private static List<Map<String, Object>> flatten(List<Account> accounts) {
    List<Map<String, Object>> result = new ArrayList<>();
    for (Account account : accounts) {
      for (Map<String, Object> holding : account.holdings()) {
        Map<String, Object> row = new LinkedHashMap<>(holding);
        row.putIfAbsent("account_type", account.accountType());
        row.putIfAbsent("account_currency", account.currency());
        result.add(row);
      }
    }
    return result;
  }

  private static List<Map<String, Object>> aggregate(
      List<Map<String, Object>> holdings, String field, String unknownLabel) {
    Map<String, BigDecimal> values = new LinkedHashMap<>();
    for (Map<String, Object> holding : holdings) {
      String label = optionalString(holding, field);
      if (label == null && field.equals("asset_class")) {
        label = optionalString(holding, "instrument_type");
      }
      if (label == null) {
        label = unknownLabel;
      }
      values.merge(label, decimal(holding.get("market_value_gbp")), BigDecimal::add);
    }
    BigDecimal total = values.values().stream().reduce(BigDecimal.ZERO, BigDecimal::add);
    List<Map<String, Object>> result = new ArrayList<>();
    for (Map.Entry<String, BigDecimal> entry : values.entrySet()) {
      Map<String, Object> row = new LinkedHashMap<>();
      row.put(field, entry.getKey());
      row.put("market_value_gbp", entry.getValue());
      row.put("weight_pct", percentage(entry.getValue(), total));
      result.add(row);
    }
    result.sort(
        (left, right) ->
            decimal(right.get("market_value_gbp"))
                .compareTo(decimal(left.get("market_value_gbp"))));
    return result;
  }

  private static BigDecimal accountValue(Account account, String currencyFilter) {
    if (currencyFilter == null) {
      return decimal(account.data().get("value_estimate_gbp"));
    }
    return account.holdings().stream()
        .map(holding -> decimal(holding.get("market_value_gbp")))
        .reduce(BigDecimal.ZERO, BigDecimal::add);
  }

  private static BigDecimal decimal(Object value) {
    if (value instanceof BigDecimal decimal) {
      return decimal;
    }
    if (value instanceof Number number) {
      return new BigDecimal(number.toString());
    }
    if (value instanceof String text) {
      try {
        return new BigDecimal(text);
      } catch (NumberFormatException ignored) {
        return BigDecimal.ZERO;
      }
    }
    return BigDecimal.ZERO;
  }

  private static BigDecimal percentage(BigDecimal value, BigDecimal total) {
    if (total.signum() == 0) {
      return BigDecimal.ZERO;
    }
    return value.multiply(BigDecimal.valueOf(100)).divide(total, 2, RoundingMode.HALF_UP);
  }

  private static boolean matches(String expected, String actual) {
    return expected == null || (actual != null && expected.equalsIgnoreCase(actual));
  }

  private static String requiredString(Map<String, Object> values, String key) {
    return optionalString(values, key);
  }

  private static boolean optionalBoolean(Map<String, Object> values, String key) {
    Object value = values.get(key);
    if (value instanceof Boolean bool) {
      return bool;
    }
    if (value instanceof String text) {
      return "true".equalsIgnoreCase(text.trim());
    }
    if (value instanceof Number number) {
      return number.intValue() != 0;
    }
    return false;
  }

  private static int parseLookbackDays(Map<String, Object> arguments) {
    if (!arguments.containsKey(LOOKBACK_DAYS)) {
      return DEFAULT_LOOKBACK_DAYS;
    }
    Object raw = arguments.get(LOOKBACK_DAYS);
    if (raw instanceof Number num) {
      int value = num.intValue();
      if (value <= 0) {
        return 0;
      }
      return Math.min(value, MAX_LOOKBACK_DAYS);
    }
    return DEFAULT_LOOKBACK_DAYS;
  }

  /**
   * Merges historical sector weights from a lookback snapshot into the current sector list. Each
   * current sector gets a {@code weight_pct_year_ago} field when the historical snapshot contains a
   * matching sector name (case-insensitive). Sectors present only in one snapshot are returned
   * unchanged. Original maps are not mutated: the returned list contains new maps.
   */
  /**
   * Result of a year-ago enrichment attempt: the sector rows to return, plus a note explaining why
   * no {@code weight_pct_year_ago} was attached when the rows came back unenriched.
   */
  private record HistoricalWeights(List<Map<String, Object>> sectors, String note) {}

  /**
   * Attaches {@code weight_pct_year_ago} to each sector, or explains why it could not.
   *
   * <p>Reads {@code weight_pct}, an actual share of market value. This previously read {@code
   * contribution_pct}, which is a gain contribution measured against cost ({@code gain_gbp /
   * total_cost * 100}) and not a weight at all; on a real portfolio that produced "sector weights"
   * of ~1e-06 which the research agent then reported as fact.
   *
   * <p>The backend prices a past {@code as_of} from current holdings and the latest price snapshot,
   * so it can legitimately return today's numbers for a historical date. Emitting those as {@code
   * weight_pct_year_ago} would assert "this sector has not moved", a stronger claim than the data
   * supports, so an identical snapshot is reported as unavailable instead.
   */
  private static HistoricalWeights enrichWithHistoricalWeights(
      List<Map<String, Object>> sectors, List<Map<String, Object>> historical, LocalDate asOf) {
    Map<String, BigDecimal> historicalWeights = new LinkedHashMap<>();
    for (Map<String, Object> row : historical) {
      String name = optionalString(row, "sector");
      Object weight = row.get("weight_pct");
      if (name != null && weight != null) {
        historicalWeights.put(name.toLowerCase(Locale.ROOT), decimal(weight));
      }
    }

    if (historicalWeights.isEmpty()) {
      return new HistoricalWeights(
          sectors,
          "Year-ago sector weights are unavailable: the backend returned no weight_pct for "
              + asOf
              + ". Do not report any change in sector weight.");
    }

    List<Map<String, Object>> enriched = new ArrayList<>();
    boolean anyWeightMoved = false;
    for (Map<String, Object> row : sectors) {
      Map<String, Object> enrichedRow = new LinkedHashMap<>(row);
      String name = optionalString(row, "sector");
      if (name != null) {
        BigDecimal histWeight = historicalWeights.get(name.toLowerCase(Locale.ROOT));
        if (histWeight != null) {
          enrichedRow.put("weight_pct_year_ago", histWeight);
          if (histWeight.compareTo(decimal(row.get("weight_pct"))) != 0) {
            anyWeightMoved = true;
          }
        }
      }
      enriched.add(enrichedRow);
    }

    if (!anyWeightMoved) {
      return new HistoricalWeights(
          sectors,
          "Year-ago sector weights are unavailable: the backend returned an identical snapshot for "
              + asOf
              + ", so no historical comparison is possible. Do not report any change in sector "
              + "weight.");
    }
    return new HistoricalWeights(enriched, null);
  }

  private static McpSchema.CallToolResult error(String message) {
    return McpSchema.CallToolResult.builder().addTextContent(message).isError(true).build();
  }

  private record Account(
      Map<String, Object> data,
      String accountType,
      String currency,
      List<Map<String, Object>> holdings) {}
}
