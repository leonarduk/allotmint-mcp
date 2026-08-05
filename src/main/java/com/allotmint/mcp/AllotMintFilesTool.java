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
import java.util.regex.PatternSyntaxException;

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

  /** Caps the number of matches a single search returns, to bound response size and walk time. */
  private static final int MAX_SEARCH_MATCHES = 500;

  private AllotMintFilesTool() {}

  /**
   * Returns the tool specification bound to the given files root. The caller is responsible for
   * deciding whether to register the returned specification; this method always produces a valid
   * spec.
   *
   * @param filesRoot the files root directory (must exist and be a directory)
   * @return the tool specification
   * @throws IllegalArgumentException if filesRoot is null, blank, does not exist, or is not a
   *     directory
   */
  static McpServerFeatures.SyncToolSpecification specification(Path filesRoot) {
    if (filesRoot == null || filesRoot.toString().isBlank()) {
      throw new IllegalArgumentException(
          "ALLOTMINT_MCP_FILES_ROOT is required when ALLOTMINT_MCP_FILES_ENABLED=true");
    }

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
                "action", Map.of("type", "string", "enum", List.of("read", "list", "search")),
                "path",
                    Map.of(
                        "type", "string",
                        "description",
                            "File or directory path relative to the configured files root"),
                "pattern",
                    Map.of(
                        "type",
                        "string",
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
                default ->
                    error(
                        "Unsupported action '%s'; expected read, list, or search"
                            .formatted(action));
              };
            })
        .build();
  }

  // -- action handlers ----------------------------------------------------

  private static McpSchema.CallToolResult handleRead(Map<String, Object> args, Path resolvedRoot) {
    String rawPath = requireString(args, "path");
    if (rawPath == null) {
      return error("path is required for the read action");
    }

    Path safePath = resolveSafely(rawPath, resolvedRoot);
    if (safePath == null) {
      return error(
          "Path traversal rejected: '%s' resolves outside the configured files root"
              .formatted(rawPath));
    }
    if (!Files.exists(safePath)) {
      return error("File not found: %s".formatted(rawPath));
    }
    if (!Files.isRegularFile(safePath)) {
      return error("Not a regular file: %s".formatted(rawPath));
    }
    try {
      String content = Files.readString(safePath);
      return McpSchema.CallToolResult.builder().addTextContent(content).build();
    } catch (IOException e) {
      return error("Failed to read file '%s': %s".formatted(rawPath, e.getMessage()));
    }
  }

  private static McpSchema.CallToolResult handleList(Map<String, Object> args, Path resolvedRoot) {
    String rawPath = stringArg(args, "path");
    Path dir = resolvedRoot;
    if (rawPath != null && !rawPath.isBlank()) {
      dir = resolveSafely(rawPath, resolvedRoot);
      if (dir == null) {
        return error(
            "Path traversal rejected: '%s' resolves outside the configured files root"
                .formatted(rawPath));
      }
      if (!Files.exists(dir)) {
        return error("Directory not found: %s".formatted(rawPath));
      }
    }
    if (!Files.isDirectory(dir)) {
      return error("Not a directory: %s".formatted(rawPath != null ? rawPath : "(root)"));
    }

    try {
      List<Map<String, Object>> entries = new ArrayList<>();
      try (var stream = Files.list(dir)) {
        for (Path entry :
            stream.sorted(Comparator.comparing(p -> p.getFileName().toString())).toList()) {
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

    // Validate that the pattern itself is not a traversal attempt. While
    // Files.walkFileTree is root-scoped, a confusing pattern like
    // ../../etc/* should be rejected early rather than silently matching nothing.
    String decodedPattern = decodePercentSequences(pattern).replace('\\', '/');
    if (containsTraversal(decodedPattern)) {
      return error(
          "Search pattern rejected: '%s' contains path traversal sequences".formatted(pattern));
    }

    List<String> matches = new ArrayList<>();
    boolean[] truncated = {false};

    try {
      PathMatcher matcher = resolvedRoot.getFileSystem().getPathMatcher("glob:" + pattern);
      Files.walkFileTree(
          resolvedRoot,
          new SimpleFileVisitor<>() {
            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
              Path relative = resolvedRoot.relativize(file);
              if (matcher.matches(relative) || matcher.matches(file.getFileName())) {
                matches.add(relative.toString().replace('\\', '/'));
                if (matches.size() >= MAX_SEARCH_MATCHES) {
                  truncated[0] = true;
                  return FileVisitResult.TERMINATE;
                }
              }
              return FileVisitResult.CONTINUE;
            }

            @Override
            public FileVisitResult visitFileFailed(Path file, IOException exc) {
              // Skip files we can't read (permissions, races) rather than aborting the walk.
              return FileVisitResult.CONTINUE;
            }
          });
    } catch (PatternSyntaxException e) {
      return error("Invalid search pattern '%s': %s".formatted(pattern, e.getMessage()));
    } catch (IOException e) {
      return error("Search failed: %s".formatted(e.getMessage()));
    }

    matches.sort(String::compareTo);

    Map<String, Object> structured = new LinkedHashMap<>();
    structured.put("action", "search");
    structured.put("pattern", pattern);
    structured.put("matches", matches);
    structured.put("truncated", truncated[0]);

    String summary = "Found %d match(es) for '%s'".formatted(matches.size(), pattern);
    if (truncated[0]) {
      summary += " (truncated at %d matches)".formatted(MAX_SEARCH_MATCHES);
    }

    return McpSchema.CallToolResult.builder()
        .addTextContent(summary)
        .structuredContent(structured)
        .build();
  }

  // -- path security ------------------------------------------------------

  /**
   * Resolves a user-supplied relative path against the configured root, verifying containment via
   * normalized-prefix and real-path checks. Symlink escapes are detected by resolving the closest
   * existing ancestor to a real path and checking containment.
   *
   * @return the safe path within the root, or {@code null} if the path is a traversal attempt
   */
  private static Path resolveSafely(String rawPath, Path resolvedRoot) {
    // 1. Decode percent-encoded sequences to defeat URL-encoded traversal
    //    (e.g. %2e%2e%2f → ../).  Preserve literal '+' characters — URLDecoder
    //    treats '+' as a space per application/x-www-form-urlencoded, but file
    //    paths are not form data.
    String decoded = decodePercentSequences(rawPath);

    // 2. Treat backslash as a path separator on every host, not just
    //    Windows. java.nio.file.Path only splits on '\' natively on a
    //    Windows host, so on Linux a payload like ..\..\etc\passwd would
    //    otherwise be parsed as one opaque filename component instead of
    //    a traversal sequence, matching the existing isWindowsAbsolutePath
    //    precedent below of not letting traversal detection depend on
    //    which OS this process happens to run on.
    String forwardSlashes = decoded.replace('\\', '/');

    // 3. Create a Path from the normalized input
    Path userPath = Path.of(forwardSlashes);

    // 4. Reject absolute paths — Path.resolve() would return them verbatim,
    //    bypassing the root entirely (e.g. /etc/passwd, C:\Windows\...).
    //    isAbsolute() only catches Unix-style and native Windows paths; we
    //    also detect Windows drive-letter paths on non-Windows hosts so the
    //    check is not OS-dependent.
    if (userPath.isAbsolute() || isWindowsAbsolutePath(decoded)) {
      return null;
    }

    // 5. Check for traversal sequences (..) in the user-supplied path
    if (containsTraversal(forwardSlashes)) {
      return null;
    }

    // 6. Normalize the user path
    Path normalizedUser = userPath.normalize();

    // 7. Resolve against root and normalize again
    Path resolved = resolvedRoot.resolve(normalizedUser).normalize();

    // 8. Containment check on normalized paths (not string prefix — defeats
    //    sibling-directory bypass like /root-eviltwin)
    if (!resolved.startsWith(resolvedRoot)) {
      return null;
    }

    // 9. Resolve the closest existing ancestor to a real path to catch symlink
    //    escapes, even when the target itself does not exist (e.g.
    //    sub/symlink/nonexistent where sub/symlink → /etc). This also
    //    catches a symlink at the final path component: Files.exists()
    //    follows symlinks, so a symlink to an existing target is its own
    //    "existing ancestor" here, and toRealPath() resolves it (and any
    //    symlink earlier in the chain) to its true canonical location.
    Path existingAncestor = resolved;
    while (existingAncestor != null && !Files.exists(existingAncestor)) {
      existingAncestor = existingAncestor.getParent();
    }

    if (existingAncestor != null) {
      try {
        Path realAncestor = existingAncestor.toRealPath();
        if (!realAncestor.startsWith(resolvedRoot)) {
          return null;
        }
      } catch (IOException e) {
        return null;
      }
    }

    return resolved;
  }

  /**
   * Decodes percent-encoded sequences (like {@code %2e}) in the input while preserving literal
   * {@code +} characters. Standard {@link URLDecoder#decode(String, java.nio.charset.Charset)}
   * treats {@code +} as a space per the {@code application/x-www-form-urlencoded} convention, which
   * corrupts filenames like {@code a+b.txt}.
   */
  private static String decodePercentSequences(String input) {
    // Temporarily encode any literal '+' so URLDecoder leaves them alone
    String guarded = input.replace("+", "%2B");
    try {
      return URLDecoder.decode(guarded, StandardCharsets.UTF_8);
    } catch (IllegalArgumentException e) {
      // Malformed percent-encoding; treat as-is
      return input;
    }
  }

  /**
   * Returns true if the given path string is a Windows absolute path (starts with a drive letter
   * followed by {@code :\} or {@code :/}). This is needed because {@link Path#isAbsolute()} only
   * returns true for Windows paths on a Windows host; on Linux the same string looks like a
   * relative path, which would allow drive-letter paths through the absolute-path check.
   */
  private static boolean isWindowsAbsolutePath(String path) {
    return path.length() >= 3
        && Character.isLetter(path.charAt(0))
        && path.charAt(1) == ':'
        && (path.charAt(2) == '\\' || path.charAt(2) == '/');
  }

  /**
   * Returns true if the given path string contains traversal elements ({@code ..}) after resolving
   * dot-dot segments. Uses {@link Path#normalize()} for regular paths (which collapses {@code
   * sub/../x} to {@code x}), and falls back to string splitting for glob patterns that contain
   * {@code *} or {@code ?} (which {@link Path#of} rejects with {@link
   * java.nio.file.InvalidPathException}).
   */
  private static boolean containsTraversal(String path) {
    if (!path.contains("*") && !path.contains("?")) {
      try {
        Path normalized = Path.of(path).normalize();
        for (Path element : normalized) {
          if ("..".equals(element.toString())) {
            return true;
          }
        }
        return false;
      } catch (Exception e) {
        // Fall through to string-based check for paths Path rejects
      }
    }
    // String-based check for glob patterns or paths that Path rejects
    for (String segment : path.split("[/\\\\]")) {
      if ("..".equals(segment)) {
        return true;
      }
    }
    return false;
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
