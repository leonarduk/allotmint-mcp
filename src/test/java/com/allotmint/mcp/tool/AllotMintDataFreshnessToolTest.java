package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.ResourceAccessException;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AllotMintDataFreshnessToolTest {

  private static final String AS_OF = "2026-09-30";

  private AllotMintClient client;
  private McpServerFeatures.SyncToolSpecification specification;

  @BeforeEach
  void setUp() {
    client = mock(AllotMintClient.class);
    specification = AllotMintDataFreshnessTool.specification(client);
  }

  @Test
  void metadataDescribesAReadOnlyToolWithOptionalArguments() {
    McpSchema.Tool tool = specification.tool();

    assertThat(tool.name()).isEqualTo("allotmint_data_freshness");
    assertThat(tool.inputSchema()).containsEntry("additionalProperties", false);
    assertThat(tool.inputSchema()).doesNotContainKey("required");
    assertThat(tool.description()).contains("Read-only").contains("truncated");

    @SuppressWarnings("unchecked")
    Map<String, Object> properties = (Map<String, Object>) tool.inputSchema().get("properties");
    assertThat(properties).containsOnlyKeys("min_age_days", "as_of");
  }

  @Test
  void listsOnlySeriesAtOrBeyondTheThresholdMostStaleFirst() {
    when(client.dataQualitySeries())
        .thenReturn(
            series(
                position("AAA", "L", "2026-09-29"), // 1 day
                position("BBB", "L", "2026-09-23"), // 7 days: exactly at the threshold
                position("CCC", "N", "2026-09-01"), // 29 days
                position("DDD", "L", "2026-09-20"))); // 10 days

    McpSchema.CallToolResult result = call(Map.of("min_age_days", 7, "as_of", AS_OF));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    Map<String, Object> content = structured(result);
    assertThat(content)
        .containsEntry("as_of", AS_OF)
        .containsEntry("min_age_days", 7)
        .containsEntry("count", 3)
        .containsEntry("truncated", false);
    assertThat(rows(content, "stale"))
        .containsExactly(
            row("CCC", "N", "2026-09-01", 29L),
            row("DDD", "L", "2026-09-20", 10L),
            row("BBB", "L", "2026-09-23", 7L));
    assertThat(rows(content, "no_data")).isEmpty();
  }

  @Test
  void ordersTiesByTickerThenExchange() {
    when(client.dataQualitySeries())
        .thenReturn(
            series(
                position("ZZZ", "L", "2026-09-01"),
                position("AAA", "N", "2026-09-01"),
                position("AAA", "L", "2026-09-01")));

    Map<String, Object> content = structured(call(Map.of("as_of", AS_OF)));

    assertThat(rows(content, "stale"))
        .extracting(r -> r.get("ticker") + "." + r.get("exchange"))
        .containsExactly("AAA.L", "AAA.N", "ZZZ.L");
  }

  @Test
  void defaultsToSevenDaysAndToday() {
    when(client.dataQualitySeries())
        .thenReturn(series(position("OLD", "L", "2000-01-01"), position("NEW", "L", "2999-01-01")));

    Map<String, Object> content = structured(call(Map.of()));

    assertThat(content).containsEntry("min_age_days", 7);
    assertThat(content.get("as_of")).isEqualTo(java.time.LocalDate.now().toString());
    assertThat(rows(content, "stale")).extracting(r -> r.get("ticker")).containsExactly("OLD");
  }

  @Test
  void zeroThresholdIncludesSeriesUpdatedTodayButNotFutureDatedOnes() {
    when(client.dataQualitySeries())
        .thenReturn(
            series(
                position("TODAY", "L", AS_OF),
                position("FUTURE", "L", "2026-10-05"),
                position("YESTERDAY", "L", "2026-09-29")));

    Map<String, Object> content = structured(call(Map.of("min_age_days", 0, "as_of", AS_OF)));

    assertThat(rows(content, "stale"))
        .extracting(r -> r.get("ticker"))
        .containsExactly("YESTERDAY", "TODAY");
  }

  @Test
  void reportsSeriesWithMissingOrUnparseableLastDateUnderNoData() {
    Map<String, Object> nullDate = position("NULLD", "L", null);
    Map<String, Object> badDate = position("BADD", "L", "not-a-date");
    Map<String, Object> blankDate = position("BLANK", "L", " ");
    when(client.dataQualitySeries()).thenReturn(series(nullDate, badDate, blankDate));

    Map<String, Object> content = structured(call(Map.of("as_of", AS_OF)));

    assertThat(content).containsEntry("count", 0);
    assertThat(rows(content, "stale")).isEmpty();
    assertThat(rows(content, "no_data"))
        .extracting(r -> r.get("ticker"))
        .containsExactly("NULLD", "BADD", "BLANK");
  }

  @Test
  void passesTheBackendTruncatedFlagThrough() {
    Map<String, Object> response = series(position("OLD", "L", "2026-01-01"));
    response.put("truncated", true);
    when(client.dataQualitySeries()).thenReturn(response);

    assertThat(structured(call(Map.of("as_of", AS_OF)))).containsEntry("truncated", true);
  }

  @Test
  void toleratesAResponseWithoutPositions() {
    when(client.dataQualitySeries()).thenReturn(Map.of("series", List.of()));

    Map<String, Object> content = structured(call(Map.of("as_of", AS_OF)));

    assertThat(content).containsEntry("count", 0);
    assertThat(rows(content, "stale")).isEmpty();
  }

  @Test
  void acceptsWholeNumberFloatsAndNumericStringsForTheThreshold() {
    when(client.dataQualitySeries()).thenReturn(series(position("AAA", "L", "2026-09-20")));

    assertThat(structured(call(Map.of("min_age_days", 10.0, "as_of", AS_OF))))
        .containsEntry("min_age_days", 10)
        .containsEntry("count", 1);
    assertThat(structured(call(Map.of("min_age_days", "11", "as_of", AS_OF))))
        .containsEntry("min_age_days", 11)
        .containsEntry("count", 0);
  }

  @Test
  void treatsNullSentinelsAsTheDefaults() {
    when(client.dataQualitySeries()).thenReturn(series());

    Map<String, Object> content = structured(call(Map.of("min_age_days", "null", "as_of", "none")));

    assertThat(content).containsEntry("min_age_days", 7);
    assertThat(content.get("as_of")).isEqualTo(java.time.LocalDate.now().toString());
  }

  @Test
  void rejectsInvalidThresholds() {
    for (Object bad : List.of(-1, 2.5, "abc", true, List.of(1), 3_000_000_000L)) {
      McpSchema.CallToolResult result = call(Map.of("min_age_days", bad));

      assertThat(result.isError()).as("min_age_days=%s", bad).isEqualTo(Boolean.TRUE);
      assertThat(text(result)).contains("min_age_days must be a non-negative integer");
    }
  }

  @Test
  void rejectsAMalformedAsOfDate() {
    McpSchema.CallToolResult result = call(Map.of("as_of", "30/09/2026"));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(text(result)).contains("as_of must be an ISO date").contains("30/09/2026");
  }

  @Test
  void surfacesBackendApiErrorsAsToolErrors() {
    when(client.dataQualitySeries())
        .thenThrow(new AllotMintApiException(500, "AllotMint backend returned 500: boom"));

    McpSchema.CallToolResult result = call(Map.of());

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(text(result)).contains("returned 500");
  }

  @Test
  void surfacesAnUnreachableBackendAsAToolError() {
    when(client.dataQualitySeries()).thenThrow(new ResourceAccessException("Connection refused"));

    McpSchema.CallToolResult result = call(Map.of());

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(text(result)).contains("Unable to reach the AllotMint backend");
  }

  private static Map<String, Object> position(String ticker, String exchange, String lastDate) {
    Map<String, Object> position = new HashMap<>();
    position.put("ticker", ticker);
    position.put("exchange", exchange);
    position.put("last_date", lastDate);
    position.put("gap_count", 0);
    return position;
  }

  @SafeVarargs
  private static Map<String, Object> series(Map<String, Object>... positions) {
    Map<String, Object> response = new LinkedHashMap<>();
    response.put("count", positions.length);
    response.put("positions", List.of(positions));
    response.put("truncated", false);
    return response;
  }

  private static Map<String, Object> row(
      String ticker, String exchange, String lastDate, long days) {
    Map<String, Object> row = new LinkedHashMap<>();
    row.put("ticker", ticker);
    row.put("exchange", exchange);
    row.put("last_date", lastDate);
    row.put("days_since_last_update", days);
    return row;
  }

  @SuppressWarnings("unchecked")
  private static List<Map<String, Object>> rows(Map<String, Object> content, String key) {
    return (List<Map<String, Object>>) content.get(key);
  }

  private static Map<String, Object> structured(McpSchema.CallToolResult result) {
    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    @SuppressWarnings("unchecked")
    Map<String, Object> content = (Map<String, Object>) result.structuredContent();
    return content;
  }

  private static String text(McpSchema.CallToolResult result) {
    return ((McpSchema.TextContent) result.content().get(0)).text();
  }

  private McpSchema.CallToolResult call(Map<String, Object> arguments) {
    return specification
        .callHandler()
        .apply(null, new McpSchema.CallToolRequest("allotmint_data_freshness", arguments));
  }
}
