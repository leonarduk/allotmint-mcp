package com.allotmint.mcp.tool;

import java.util.Map;

/** Common normalization for arguments supplied by MCP clients and language models. */
final class ToolArguments {

  private ToolArguments() {}

  /**
   * Returns a trimmed string argument, or {@code null} when it is absent or represents no value.
   * Some language models serialize an unused optional argument as the string "null" or "none"
   * instead of omitting it or emitting a JSON null, so those sentinels are normalized here too.
   */
  static String optionalString(Map<String, Object> values, String key) {
    Object value = values.get(key);
    if (!(value instanceof String text) || text.isBlank()) {
      return null;
    }

    String normalized = text.trim();
    if ("null".equalsIgnoreCase(normalized) || "none".equalsIgnoreCase(normalized)) {
      return null;
    }
    return normalized;
  }
}
