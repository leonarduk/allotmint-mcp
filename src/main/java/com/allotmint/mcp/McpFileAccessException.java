package com.allotmint.mcp;

/**
 * Thrown by {@link AllotMintFilesTool} when a requested path cannot be resolved within the
 * configured files root directory — for example, {@code ../} traversal, absolute paths pointing
 * outside root, or symlinks that escape.
 */
final class McpFileAccessException extends RuntimeException {

  McpFileAccessException(String message) {
    super(message);
  }

  McpFileAccessException(String message, Throwable cause) {
    super(message, cause);
  }
}
