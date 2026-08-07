package com.allotmint.mcp.error;

/**
 * Raised when the AllotMint backend returns a 4xx/5xx response, so callers (MCP tools) can surface
 * a readable message instead of a raw {@code WebClientResponseException} stack trace. {@link
 * #getMessage()} is safe to show directly to an MCP client.
 */
public class AllotMintApiException extends RuntimeException {

  private final int statusCode;

  public AllotMintApiException(int statusCode, String message) {
    super(message);
    this.statusCode = statusCode;
  }

  int statusCode() {
    return statusCode;
  }
}
