package com.allotmint.mcp;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.PathMatcher;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Optional {@code allotmint_files} MCP tool, registered only when {@code
 * ALLOTMINT_MCP_FILES_ENABLED=true}. Provides read-only file access (read, list, search) strictly
 * confined to {@code ALLOTMINT_MCP_FILES_ROOT}. Path-traversal payloads (../, absolute paths,
 * symlink escapes, URL-encoded sequences) are rejected with a clear error rather than silently
 * resolved.
 *
 * <p>This is a security boundary, not a convenience default — the tool is absent from {@code
 * tools/list} when the feature flag is unset or false.
 */
final class AllotMintFilesTool {

  private AllotMintFilesTool() {}

  /**
   * Returns the tool specification bound to the given files root. The caller is responsible for
   * deciding whether to register the returned specification; this method always produces a valid
   * spec.
   *
   * @param filesRoot the resolved (real-path) root directory for all file operations
   * @return the tool specification
   */
  static McpServerFeatures.SyncToolSpecification specification(Path filesRoot) {
    Path resolvedRoot;
    try {
      resolvedRoot = filesRoot.toRealPath();
    } catch (IOException e) {
      throw new IllegalArgumentException(
          "ALLOTMINT_MCP_FILES_ROOT does not exist or is not accessible: " + filesRoot, e);
    }
    if (!Files.isDirectory(resolvedRoot)) {
      throw new IllegalArgumentException(
          "ALLOTMINT_MCP_FILES_ROOT is not a directory: " + resolvedRoot);
    }

    Map<String, Object> inputSchema =
        Map.of(
            "type",
            "object",
            "properties",
            Map.of(
                "action",
                    Map.of(
                        "type", "string",
                        "enum", List.of("read", "list", "search")),
                "path",
                    Map.of(
                        "type", "string",
                        "description",
                            "File or directory path relative to the configured files root"),
                "pattern",
                    Map.of(
                        "type", "string",
                        "description",
                            "Glob pattern for search (e.g. **/*.java, *.md). Searches"
                                + " recursively from the files root; ignored for read/list.")),
            "required",
            List.of("action"),
            "additionalProperties",
            false);

    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_files", inputSchema)
            .description(
                "Read, list, and search files within the configured files root."
                    + " Read-only; write operations are not supported.")
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler(
            (exchange, request) -> {
              Map<String, Object> args = request.arguments();
              String action = requireString(args, "action");
              if (action == null) {
                return error("action is required; expected read, list, or search");
              }
              return switch (action) {
                case "read" -> handleRead(args, resolvedRoot);
                case "list" -> handleList(args, resolvedRoot);
                case "search" -> handleSearch(args, resolvedRoot);
                default -> error("Unsupported action '%s'; expected read, list, or search"
                    .formatted(action));
              };
            })
        .build();
  }

  // -- action handlers ----------------------------------------------------

  private static McpSchema.CallToolResult handleRead(
      Map<String, Object> args, Path resolvedRoot) {
    String rawPath = requireString(args, "path");
    if (rawPath == null) {
      return error("path is required for the read action");
    }

    Path safePath = resolveSafely(rawPath, resolvedRoot);
    if (safePath == null) {
      // resolveSafely returns the error result
      return error(
          "Path traversal rejected: '%s' resolves outside the configured files root"
              .formatted(rawPath));
    }
    if (!Files.isRegularFile(safePath)) {
      return error("Not a regular file: %s".formatted(rawPath));
    }
    try {
      String content = Files.readString(safePath);
      return McpSchema.CallToolResult.builder()
          .addTextContent(content)
          .build();
    } catch (IOException e) {
      return error("Failed to read file '%s': %s".formatted(rawPath, e.getMessage()));
    }
  }

  private static McpSchema.CallToolResult handleList(
      Map<String, Object> args, Path resolvedRoot) {
    String rawPath = stringArg(args, "path");
    Path dir = resolvedRoot;
    if (rawPath != null && !rawPath.isBlank()) {
      dir = resolveSafely(rawPath, resolvedRoot);
      if (dir == null) {
        return error(
            "Path traversal rejected: '%s' resolves outside the configured files root"
                .formatted(rawPath));
      }
    }
    if (!Files.isDirectory(dir)) {
      return error("Not a directory: %s".formatted(rawPath != null ? rawPath : "(root)"));
    }

    try {
      List<Map<String, Object>> entries = new ArrayList<>();
      try (var stream = Files.list(dir)) {
        for (Path entry : stream.sorted(Comparator.comparing(p -> p.getFileName().toString()))
            .toList()) {
          Map<String, Object> info = new LinkedHashMap<>();
          info.put("name", entry.getFileName().toString());
          info.put("type", Files.isDirectory(entry) ? "directory" : "file");
          try {
            info.put("size", Files.size(entry));
          } catch (IOException ignored) {
            // size unavailable
          }
          entries.add(info);
        }
      }

      Map<String, Object> structured = new LinkedHashMap<>();
      structured.put("action", "list");
      structured.put("path", rawPath != null ? rawPath : ".");
      structured.put("entries", entries);

      return McpSchema.CallToolResult.builder()
          .addTextContent("Listed %d entries in %s".formatted(entries.size(), dir))
          .structuredContent(structured)
          .build();
    } catch (IOException e) {
      return error("Failed to list directory '%s': %s".formatted(dir, e.getMessage()));
    }
  }

  private static McpSchema.CallToolResult handleSearch(
      Map<String, Object> args, Path resolvedRoot) {
    String pattern = requireString(args, "pattern");
    if (pattern == null || pattern.isBlank()) {
      return error("pattern is required for the search action");
    }

    PathMatcher matcher = resolvedRoot.getFileSystem().getPathMatcher("glob:" + pattern);
    List<String> matches = new ArrayList<>();

    try {
      Files.walkFileTree(
          resolvedRoot,
          new SimpleFileVisitor<>() {
            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
              Path relative = resolvedRoot.relativize(file);
              if (matcher.matches(relative) || matcher.matches(file.getFileName())) {
                matches.add(relative.toString().replace('\\', '/'));
              }
              return FileVisitResult.CONTINUE;
            }
          });
    } catch (IOException e) {
      return error("Search failed: %s".formatted(e.getMessage()));
    }

    matches.sort(String::compareTo);

    Map<String, Object> structured = new LinkedHashMap<>();
    structured.put("action", "search");
    structured.put("pattern", pattern);
    structured.put("matches", matches);

    return McpSchema.CallToolResult.builder()
        .addTextContent("Found %d match(es) for '%s'".formatted(matches.size(), pattern))
        .structuredContent(structured)
        .build();
  }

  // -- path security ------------------------------------------------------

  /**
   * Resolves a user-supplied relative path against the configured root, following symlinks and
   * verifying containment. Returns the real path if the target exists and is safely within the
   * root, or {@code null} if the path escapes the root.
   */
  private static Path resolveSafely(String rawPath, Path resolvedRoot) {
    // 1. URL-decode to defeat URL-encoded traversal sequences (e.g. %2e%2e%2f)
    String decoded;
    try {
      decoded = URLDecoder.decode(rawPath, StandardCharsets.UTF_8);
    } catch (IllegalArgumentException e) {
      // Malformed percent-encoding; treat as-is
      decoded = rawPath;
    }

    // 2. Create a Path from the decoded input
    Path userPath = Path.of(decoded);

    // 3. Reject absolute paths — Path.resolve() would return them verbatim,
    //    bypassing the root entirely (e.g. /etc/passwd, C:\Windows\...)
    if (userPath.isAbsolute()) {
      return null;
    }

    // 4. Normalize the user path and reject any that still contain ".." after
    //    normalization — this catches non-canonical traversal like foo/../../bar
    Path normalizedUser = userPath.normalize();
    for (Path element : normalizedUser) {
      if ("..".equals(element.toString())) {
        return null;
      }
    }

    // 5. Resolve against root and normalize again
    Path resolved = resolvedRoot.resolve(normalizedUser).normalize();

    // 6. String-prefix check is insufficient (sibling-directory bypass like
    //    /root-eviltwin).  Use startsWith on normalized paths first.
    if (!resolved.startsWith(resolvedRoot)) {
      return null;
    }

    // 7. toRealPath() follows symlinks and resolves case on case-insensitive
    //    filesystems.  If the file does not exist, toRealPath throws — return
    //    null to signal traversal rejection (we can't verify containment of a
    //    non-existent target, so we reject it).
    Path realPath;
    try {
      realPath = resolved.toRealPath();
    } catch (IOException e) {
      return null;
    }

    // 8. Final containment check against the real root
    if (!realPath.startsWith(resolvedRoot)) {
      return null;
    }

    return realPath;
  }

  // -- argument helpers ----------------------------------------------------

  private static String requireString(Map<String, Object> args, String key) {
    Object value = args.get(key);
    if (!(value instanceof String text) || text.isBlank()) {
      return null;
    }
    return text.trim();
  }

  private static String stringArg(Map<String, Object> args, String key) {
    Object value = args.get(key);
    if (!(value instanceof String text)) {
      return null;
    }
    String trimmed = text.trim();
    return trimmed.isEmpty() ? null : trimmed;
  }

  private static McpSchema.CallToolResult error(String message) {
    return McpSchema.CallToolResult.builder().addTextContent(message).isError(true).build();
  }
}
