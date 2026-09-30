package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.springframework.web.client.RestClientException;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.allotmint.mcp.tool.ToolArguments.optionalString;

/**
 * Read-only data-freshness report: which cached series have not received a data point for a number
 * of days. Built on the per-series metrics the backend already exposes ({@code GET
 * /data-quality/timeseries}), so the age arithmetic and ordering are done here rather than left to
 * the calling model.
 *
 * <p>Staleness is measured in calendar days. A series with no {@code last_date} (empty cache) is
 * reported separately under {@code no_data} rather than dropped.
 */
public final class AllotMintDataFreshnessTool {

  static final String MIN_AGE_DAYS = "min_age_days";
  static final String AS_OF = "as_of";
  static final int DEFAULT_MIN_AGE_DAYS = 7;

  private AllotMintDataFreshnessTool() {}

  public static McpServerFeatures.SyncToolSpecification specification(AllotMintClient client) {
    Map<String, Object> properties = new LinkedHashMap<>();
    properties.put(
        MIN_AGE_DAYS,
        Map.of(
            "type",
            "integer",
            "minimum",
            0,
            "default",
            DEFAULT_MIN_AGE_DAYS,
            "description",
            "Report series whose latest data point is at least this many calendar days old."));
    properties.put(
        AS_OF,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "description",
            "Reference date (YYYY-MM-DD) that age is measured against. Defaults to today."));

    Map<String, Object> inputSchema =
        Map.of("type", "object", "properties", properties, "additionalProperties", false);

    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_data_freshness", inputSchema)
            .description(
                "AllotMint data freshness. Lists cached price series that have not updated for "
                    + "min_age_days or more (default 7), most stale first, with each series' "
                    + "last_date and days_since_last_update. Series with no data are listed "
                    + "separately under no_data. Check truncated: when true the backend cut the "
                    + "series list short, so the result may be incomplete. Read-only.")
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler((exchange, request) -> call(client, request.arguments()))
        .build();
  }

  private static McpSchema.CallToolResult call(
      AllotMintClient client, Map<String, Object> arguments) {
    int minAgeDays;
    try {
      minAgeDays = minAgeDays(arguments);
    } catch (IllegalArgumentException e) {
      return error(e.getMessage());
    }

    LocalDate asOf;
    String asOfText = optionalString(arguments, AS_OF);
    try {
      asOf = asOfText == null ? LocalDate.now() : LocalDate.parse(asOfText);
    } catch (DateTimeParseException e) {
      return error("as_of must be an ISO date (YYYY-MM-DD), got: " + asOfText);
    }

    try {
      return McpSchema.CallToolResult.builder()
          .addTextContent("AllotMint data freshness returned successfully")
          .structuredContent(report(client.dataQualitySeries(), minAgeDays, asOf))
          .build();
    } catch (AllotMintApiException e) {
      return error(e.getMessage());
    } catch (RestClientException e) {
      return error("Unable to reach the AllotMint backend: " + e.getMessage());
    }
  }

  private static int minAgeDays(Map<String, Object> arguments) {
    Object value = arguments.get(MIN_AGE_DAYS);
    if (value == null) {
      return DEFAULT_MIN_AGE_DAYS;
    }
    String message = "min_age_days must be a non-negative integer, got: " + value;
    long parsed;
    if (value instanceof Integer || value instanceof Long || value instanceof Short) {
      parsed = ((Number) value).longValue();
    } else if (value instanceof Number number) {
      // JSON clients may send 7.0; accept it only when it is a whole number.
      if (number.doubleValue() != Math.rint(number.doubleValue())) {
        throw new IllegalArgumentException(message);
      }
      parsed = (long) number.doubleValue();
    } else if (value instanceof String) {
      String normalized = optionalString(arguments, MIN_AGE_DAYS);
      if (normalized == null) {
        return DEFAULT_MIN_AGE_DAYS;
      }
      try {
        parsed = Long.parseLong(normalized);
      } catch (NumberFormatException e) {
        throw new IllegalArgumentException(message, e);
      }
    } else {
      throw new IllegalArgumentException(message);
    }
    if (parsed < 0 || parsed > Integer.MAX_VALUE) {
      throw new IllegalArgumentException(message);
    }
    return (int) parsed;
  }

  private static Map<String, Object> report(
      Map<String, Object> series, int minAgeDays, LocalDate asOf) {
    List<Map<String, Object>> stale = new ArrayList<>();
    List<Map<String, Object>> noData = new ArrayList<>();

    if (series.get("positions") instanceof List<?> positions) {
      for (Object position : positions) {
        if (!(position instanceof Map<?, ?> row)) {
          continue;
        }
        Object ticker = row.get("ticker");
        Object exchange = row.get("exchange");
        LocalDate lastDate = parseDate(row.get("last_date"));

        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("ticker", ticker);
        entry.put("exchange", exchange);
        if (lastDate == null) {
          noData.add(entry);
          continue;
        }
        long age = ChronoUnit.DAYS.between(lastDate, asOf);
        if (age >= minAgeDays) {
          entry.put("last_date", lastDate.toString());
          entry.put("days_since_last_update", age);
          stale.add(entry);
        }
      }
    }

    stale.sort(
        Comparator.<Map<String, Object>>comparingLong(e -> (Long) e.get("days_since_last_update"))
            .reversed()
            .thenComparing(e -> String.valueOf(e.get("ticker")))
            .thenComparing(e -> String.valueOf(e.get("exchange"))));

    Map<String, Object> result = new LinkedHashMap<>();
    result.put("as_of", asOf.toString());
    result.put("min_age_days", minAgeDays);
    result.put("truncated", Boolean.TRUE.equals(series.get("truncated")));
    result.put("count", stale.size());
    result.put("stale", stale);
    result.put("no_data", noData);
    return result;
  }

  private static LocalDate parseDate(Object value) {
    if (!(value instanceof String text) || text.isBlank()) {
      return null;
    }
    try {
      return LocalDate.parse(text.trim());
    } catch (DateTimeParseException e) {
      return null;
    }
  }

  private static McpSchema.CallToolResult error(String message) {
    return McpSchema.CallToolResult.builder().addTextContent(message).isError(true).build();
  }
}
