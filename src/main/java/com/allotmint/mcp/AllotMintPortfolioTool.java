package com.allotmint.mcp;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.springframework.web.client.RestClientException;

/** Read-only portfolio queries composed from the per-owner AllotMint endpoints. */
final class AllotMintPortfolioTool {

  static final String ACTION = "action";
  static final String OWNER = "owner";
  static final String ACCOUNT_TYPE = "account_type";
  static final String CURRENCY = "currency";

  private static final List<String> ACTIONS = List.of("summary", "exposure", "holdings");

  private AllotMintPortfolioTool() {}

  static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
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

    Map<String, Object> inputSchema =
        Map.of(
            "type", "object",
            "properties", properties,
            "required", List.of(ACTION, OWNER),
            "additionalProperties", false);

    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_portfolio", inputSchema)
            .description(
                "Reads one owner's AllotMint portfolio. owner is required; call GET /owners "
                    + "through the AllotMint API to discover valid owner slugs. Actions: summary, "
                    + "exposure, or holdings. Optional account_type and currency filters are "
                    + "applied client-side.")
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

    try {
      Map<String, Object> structured =
          switch (action.toLowerCase(Locale.ROOT)) {
            case "summary" -> summary(client, owner, accountType, currency);
            case "exposure" -> exposure(client, owner, accountType, currency);
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
      AllotMintClient client, String owner, String accountType, String currency) {
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
    result.put("performance", performance);
    return result;
  }

  private static Map<String, Object> exposure(
      AllotMintClient client, String owner, String accountType, String currency) {
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

    Map<String, Object> result = baseResult("exposure", owner, accountType, currency);
    result.put("as_of", portfolio.get("as_of"));
    result.put("sectors", sectors);
    result.put("asset_classes", aggregate(filteredHoldings, "asset_class", "Unknown"));
    result.put("currencies", aggregate(filteredHoldings, "currency", "Unknown"));
    return result;
  }

  private static Map<String, Object> holdings(
      AllotMintClient client, String owner, String accountType, String currency) {
    Map<String, Object> portfolio = client.portfolio(owner);
    List<Map<String, Object>> holdings = flatten(filteredAccounts(portfolio, accountType, currency));
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

  private record Account(
      Map<String, Object> data,
      String accountType,
      String currency,
      List<Map<String, Object>> holdings) {}
}
