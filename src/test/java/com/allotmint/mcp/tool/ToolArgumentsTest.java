package com.allotmint.mcp.tool;

import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ToolArgumentsTest {

  @Test
  void returnsTrimmedValueForAnOrdinaryString() {
    Map<String, Object> values = Map.of("key", "  hello  ");

    assertThat(ToolArguments.optionalString(values, "key")).isEqualTo("hello");
  }

  @Test
  void returnsNullWhenKeyIsAbsent() {
    Map<String, Object> values = Map.of();

    assertThat(ToolArguments.optionalString(values, "key")).isNull();
  }

  @Test
  void returnsNullForAnEmptyString() {
    Map<String, Object> values = Map.of("key", "");

    assertThat(ToolArguments.optionalString(values, "key")).isNull();
  }

  @Test
  void returnsNullForAWhitespaceOnlyString() {
    Map<String, Object> values = Map.of("key", "   ");

    assertThat(ToolArguments.optionalString(values, "key")).isNull();
  }

  @Test
  void returnsNullForTheNullSentinelIgnoringCaseAndPadding() {
    Map<String, Object> values = Map.of("key", " null ");

    assertThat(ToolArguments.optionalString(values, "key")).isNull();
  }

  @Test
  void returnsNullForTheNoneSentinelIgnoringCase() {
    Map<String, Object> values = Map.of("key", "None");

    assertThat(ToolArguments.optionalString(values, "key")).isNull();
  }

  @Test
  void returnsValueThatOnlyResemblesTheSentinel() {
    Map<String, Object> values = Map.of("key", "null-value");

    assertThat(ToolArguments.optionalString(values, "key")).isEqualTo("null-value");
  }

  @Test
  void returnsNullWhenTheStoredValueIsALiteralJsonNull() {
    Map<String, Object> values = new HashMap<>();
    values.put("key", null);

    assertThat(ToolArguments.optionalString(values, "key")).isNull();
  }

  @Test
  void returnsNullWhenTheValueIsNotAString() {
    Map<String, Object> values = Map.of("key", 42);

    assertThat(ToolArguments.optionalString(values, "key")).isNull();
  }
}
